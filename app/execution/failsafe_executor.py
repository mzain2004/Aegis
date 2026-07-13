"""Execution backend that correlates a transport executor with the BPF-LSM floor.

This wraps an existing transport executor (the ``KubernetesExecutor``) and adds
no request-time coupling to the kernel failsafe. The failsafe is treated as a
statically-configured, out-of-band, independent floor: Aegis never reconfigures
it, never signals it, and never depends on it being reachable. Instead, around
each approved dispatch this executor reads the failsafe's audit stream over the
execution window and reports whether the kernel had to *block* any syscall the
approved command triggered.

Correlation is best-effort and cgroup-scoped, not per-request: the failsafe keys
on cgroup membership, so a block observed in the window is attributed to the
protected cgroup during that window, not proven to be this exact JSON-RPC call.
That is an honest tripwire signal ("Aegis approved X; the kernel blocked Y in
the protected cgroup meanwhile"), not a claim of causal precision.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.execution.base import ExecutionEngine
from app.execution.failsafe_audit import FailsafeAuditEvent, FailsafeAuditReader
from app.execution.models import ExecutionResult
from app.logger import get_logger

LOGGER = get_logger(__name__)


class FailsafeCorrelatingExecutor(ExecutionEngine):
    """Dispatch through a delegate executor, then correlate kernel block events."""

    def __init__(
        self,
        delegate: ExecutionEngine,
        settings: Settings | None = None,
        *,
        audit_reader: FailsafeAuditReader | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._delegate = delegate
        self._reader = audit_reader or FailsafeAuditReader(
            self.settings.failsafe_audit_log_path
        )
        # 0 disables the cgroup filter (report blocks from any cgroup).
        self._cgroup_id = self.settings.failsafe_cgroup_id
        self._fail_on_block = self.settings.failsafe_fail_on_block

    async def execute(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> ExecutionResult:
        start_offset = self._reader.current_offset()
        result = await self._delegate.execute(body, headers)
        blocks = self._read_blocks(start_offset)

        for event in blocks:
            LOGGER.warning(
                "failsafe_block_observed",
                kind=event.kind,
                comm=event.comm,
                cgid=event.cgid,
                target=event.target,
                dst=event.dst,
            )

        response_headers = dict(result.headers)
        response_headers["x-aegis-failsafe-blocks"] = str(len(blocks))

        update: dict[str, object] = {
            "headers": response_headers,
            "backend": f"{result.backend}+failsafe",
        }
        if blocks and self._fail_on_block:
            update["success"] = False
            update["status_code"] = 502

        return result.model_copy(update=update)

    def _read_blocks(self, start_offset: int) -> list[FailsafeAuditEvent]:
        """Return kernel-blocked events in the window, cgroup-filtered.

        Observability must never break an approved request, so any failure to
        read/parse the audit stream degrades to "no blocks observed" with a
        warning rather than propagating.
        """

        try:
            events, _ = self._reader.read_since(start_offset)
        except Exception:  # pragma: no cover - defensive: never break dispatch
            LOGGER.warning(
                "failsafe_audit_read_failed",
                path=self.settings.failsafe_audit_log_path,
            )
            return []

        return [
            event
            for event in events
            if event.blocked
            and (self._cgroup_id == 0 or event.cgid == self._cgroup_id)
        ]
