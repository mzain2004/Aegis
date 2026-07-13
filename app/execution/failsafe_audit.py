"""Reader for the BPF-LSM failsafe's plaintext audit log.

The kernel failsafe (a separate C/eBPF daemon, out of process and out of band
from Aegis) streams one line per ring-buffer event to a log file, formatted
roughly as::

    [BLOCK] EXEC    tgid=123  pid=456  uid=0  cgid=789  comm=curl  target=/usr/bin/curl
    [AUDIT] CONN    tgid=123  pid=456  uid=0  cgid=789  comm=curl  dst=93.184.216.34:443

Fields are whitespace-padded for human readability, not fixed-width, so this
reader tokenizes on whitespace rather than fixed byte offsets. Aegis never
writes to this file and never signals the failsafe; it only tails it.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

_BLOCK_MARKER = "[BLOCK]"
_AUDIT_MARKER = "[AUDIT]"


class FailsafeAuditEvent(BaseModel):
    """A single parsed line from the failsafe audit log."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    blocked: bool
    comm: str
    cgid: int
    target: str | None = None
    dst: str | None = None


def parse_line(line: str) -> FailsafeAuditEvent | None:
    """Parse one audit-log line, or return None if it doesn't match.

    Non-matching lines (blank lines, truncated writes, log headers, anything
    that doesn't carry the fields this reader needs) are skipped rather than
    raised, since a partially-written line at the tail of the file is a
    routine race with the writer, not an error condition.
    """

    tokens = line.strip().split()
    if len(tokens) < 3:
        return None

    marker = tokens[0]
    if marker == _BLOCK_MARKER:
        blocked = True
    elif marker == _AUDIT_MARKER:
        blocked = False
    else:
        return None

    kind = tokens[1]

    fields: dict[str, str] = {}
    for token in tokens[2:]:
        key, sep, value = token.partition("=")
        if sep:
            fields[key] = value

    if "cgid" not in fields:
        return None
    try:
        cgid = int(fields["cgid"])
    except ValueError:
        return None

    target = fields.get("target")
    dst = fields.get("dst")
    if target is None and dst is None:
        return None

    return FailsafeAuditEvent(
        kind=kind,
        blocked=blocked,
        comm=fields.get("comm", ""),
        cgid=cgid,
        target=target,
        dst=dst,
    )


class FailsafeAuditReader:
    """Tails the failsafe's audit log by byte offset, tolerating rotation."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def current_offset(self) -> int:
        """Return the current end-of-file byte offset, or 0 if missing."""

        try:
            return self._path.stat().st_size
        except OSError:
            return 0

    def read_since(self, offset: int) -> tuple[list[FailsafeAuditEvent], int]:
        """Return parsed events written since ``offset``, and the new offset.

        If the file is missing, this degrades to an empty result rather than
        raising, since the failsafe's kernel enforcement is independent of
        whether its log file happens to exist at read time. The same applies
        if the file exists but cannot be opened for reading (e.g. permission
        denied) -- Aegis never depends on read access to this log to dispatch
        approved requests, so a read failure here must never break dispatch.
        If the file has shrunk since ``offset`` was captured (truncation or
        log rotation, including a stale offset that is now beyond the current
        file size), reading restarts from the beginning instead of seeking
        past the end.
        """

        try:
            size = self._path.stat().st_size
            start = offset if offset <= size else 0

            with self._path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(start)
                content = handle.read()
                new_offset = handle.tell()
        except OSError:
            return [], 0

        events = [
            event
            for line in content.splitlines()
            if (event := parse_line(line)) is not None
        ]
        return events, new_offset
