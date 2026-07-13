"""Tests for the BPF-LSM failsafe audit log reader."""

from __future__ import annotations

from pathlib import Path

from app.execution.failsafe_audit import FailsafeAuditReader, parse_line


def test_parse_block_exec_line() -> None:
    line = (
        "[BLOCK] EXEC    tgid=123    pid=456    uid=0     cgid=789    "
        "comm=curl             target=/usr/bin/curl"
    )

    event = parse_line(line)

    assert event is not None
    assert event.blocked is True
    assert event.kind == "EXEC"
    assert event.comm == "curl"
    assert event.cgid == 789
    assert event.target == "/usr/bin/curl"
    assert event.dst is None


def test_parse_audit_conn_line() -> None:
    line = (
        "[AUDIT] CONN    tgid=123    pid=456    uid=0     cgid=42    "
        "comm=curl             dst=93.184.216.34:443"
    )

    event = parse_line(line)

    assert event is not None
    assert event.blocked is False
    assert event.kind == "CONN"
    assert event.cgid == 42
    assert event.dst == "93.184.216.34:443"
    assert event.target is None


def test_parse_non_matching_line_returns_none() -> None:
    assert parse_line("") is None
    assert parse_line("some unrelated log line") is None
    assert parse_line("[INFO] loader started") is None
    assert parse_line("[BLOCK] EXEC tgid=1 pid=1 uid=0 comm=x") is None


def test_reader_missing_file_is_empty_not_error(tmp_path: Path) -> None:
    reader = FailsafeAuditReader(str(tmp_path / "does-not-exist.log"))

    assert reader.current_offset() == 0

    events, offset = reader.read_since(0)

    assert events == []
    assert offset == 0


def test_reader_reads_only_events_after_offset(tmp_path: Path) -> None:
    log_path = tmp_path / "mcp-failsafe.log"
    first_line = (
        "[AUDIT] EXEC    tgid=1    pid=1    uid=0    cgid=1    "
        "comm=first             target=/bin/first\n"
    )
    log_path.write_text(first_line)

    reader = FailsafeAuditReader(str(log_path))
    start_offset = reader.current_offset()

    second_line = (
        "[BLOCK] EXEC    tgid=2    pid=2    uid=0    cgid=2    "
        "comm=second             target=/bin/second\n"
    )
    with log_path.open("a") as handle:
        handle.write(second_line)

    events, new_offset = reader.read_since(start_offset)

    assert len(events) == 1
    assert events[0].comm == "second"
    assert events[0].blocked is True
    assert new_offset > start_offset


def test_reader_restarts_on_truncation(tmp_path: Path) -> None:
    log_path = tmp_path / "mcp-failsafe.log"
    long_content = (
        "[AUDIT] EXEC    tgid=1    pid=1    uid=0    cgid=1    "
        "comm=first             target=/bin/first\n"
        "[AUDIT] EXEC    tgid=2    pid=2    uid=0    cgid=2    "
        "comm=second            target=/bin/second\n"
    )
    log_path.write_text(long_content)

    reader = FailsafeAuditReader(str(log_path))
    stale_offset = reader.current_offset()

    truncated_line = (
        "[BLOCK] EXEC    tgid=3    pid=3    uid=0    cgid=3    "
        "comm=x target=/bin/x\n"
    )
    assert len(truncated_line) < stale_offset
    log_path.write_text(truncated_line)

    events, new_offset = reader.read_since(stale_offset)

    assert len(events) == 1
    assert events[0].comm == "x"
    assert new_offset == len(truncated_line)
