"""Tests for the failsafe-correlating execution backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import get_settings
from app.execution.base import ExecutionEngine
from app.execution.failsafe_audit import FailsafeAuditEvent, FailsafeAuditReader
from app.execution.failsafe_executor import FailsafeCorrelatingExecutor
from app.execution.models import ExecutionResult


class _StubDelegate(ExecutionEngine):
    """Delegate that returns a canned result, optionally writing a log line first."""

    def __init__(
        self,
        result: ExecutionResult,
        *,
        log_path: Path | None = None,
        line_to_write: str | None = None,
    ) -> None:
        self._result = result
        self._log_path = log_path
        self._line_to_write = line_to_write

    async def execute(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> ExecutionResult:
        if self._log_path is not None and self._line_to_write is not None:
            with self._log_path.open("a") as handle:
                handle.write(self._line_to_write)
        return self._result


class _OnceThenQuietDelegate(ExecutionEngine):
    """Delegate that writes its log line only on the first dispatch.

    Models a shared executor singleton fielding two sequential real requests
    where the kernel failsafe only blocked something during the first one.
    """

    def __init__(
        self,
        result: ExecutionResult,
        log_path: Path,
        line_to_write: str,
    ) -> None:
        self._result = result
        self._log_path = log_path
        self._line_to_write = line_to_write
        self._call_count = 0

    async def execute(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> ExecutionResult:
        self._call_count += 1
        if self._call_count == 1:
            with self._log_path.open("a") as handle:
                handle.write(self._line_to_write)
        return self._result


class _PermissionDeniedAuditReader(FailsafeAuditReader):
    """Reader stub whose read_since simulates a permission-denied log read."""

    def read_since(self, offset: int) -> tuple[list[FailsafeAuditEvent], int]:
        raise PermissionError("permission denied reading failsafe audit log")


def _ok_result() -> ExecutionResult:
    return ExecutionResult(
        status_code=200,
        headers={"content-type": "application/json"},
        body=b'{"ok":true}',
        latency_ms=5,
        backend="kubernetes",
        success=True,
    )


def test_delegates_and_reports_zero_blocks_when_log_missing(tmp_path: Path) -> None:
    settings = get_settings().model_copy(
        update={"failsafe_audit_log_path": str(tmp_path / "missing.log")}
    )
    delegate = _StubDelegate(_ok_result())
    executor = FailsafeCorrelatingExecutor(delegate, settings=settings)

    result = asyncio.run(executor.execute(b"{}", {}))

    assert result.success is True
    assert result.backend == "kubernetes+failsafe"
    assert result.headers["x-aegis-failsafe-blocks"] == "0"


def test_reports_block_observed_during_window(tmp_path: Path) -> None:
    log_path = tmp_path / "mcp-failsafe.log"
    log_path.write_text("")
    settings = get_settings().model_copy(
        update={"failsafe_audit_log_path": str(log_path)}
    )
    block_line = (
        "[BLOCK] EXEC    tgid=1    pid=1    uid=0    cgid=7    "
        "comm=curl             target=/usr/bin/curl\n"
    )
    delegate = _StubDelegate(_ok_result(), log_path=log_path, line_to_write=block_line)
    executor = FailsafeCorrelatingExecutor(
        delegate,
        settings=settings,
        audit_reader=FailsafeAuditReader(str(log_path)),
    )

    result = asyncio.run(executor.execute(b"{}", {}))

    assert result.headers["x-aegis-failsafe-blocks"] == "1"
    assert result.backend == "kubernetes+failsafe"
    assert result.success is True


def test_cgroup_filter_excludes_other_cgroups(tmp_path: Path) -> None:
    log_path = tmp_path / "mcp-failsafe.log"
    log_path.write_text("")
    settings = get_settings().model_copy(
        update={
            "failsafe_audit_log_path": str(log_path),
            "failsafe_cgroup_id": 99,
        }
    )
    block_line = (
        "[BLOCK] EXEC    tgid=1    pid=1    uid=0    cgid=7    "
        "comm=curl             target=/usr/bin/curl\n"
    )
    delegate = _StubDelegate(_ok_result(), log_path=log_path, line_to_write=block_line)
    executor = FailsafeCorrelatingExecutor(
        delegate,
        settings=settings,
        audit_reader=FailsafeAuditReader(str(log_path)),
    )

    result = asyncio.run(executor.execute(b"{}", {}))

    assert result.headers["x-aegis-failsafe-blocks"] == "0"


def test_fail_on_block_downgrades_result(tmp_path: Path) -> None:
    log_path = tmp_path / "mcp-failsafe.log"
    log_path.write_text("")
    settings = get_settings().model_copy(
        update={
            "failsafe_audit_log_path": str(log_path),
            "failsafe_fail_on_block": True,
        }
    )
    block_line = (
        "[BLOCK] CONN    tgid=1    pid=1    uid=0    cgid=7    "
        "comm=curl             dst=1.2.3.4:443\n"
    )
    delegate = _StubDelegate(_ok_result(), log_path=log_path, line_to_write=block_line)
    executor = FailsafeCorrelatingExecutor(
        delegate,
        settings=settings,
        audit_reader=FailsafeAuditReader(str(log_path)),
    )

    result = asyncio.run(executor.execute(b"{}", {}))

    assert result.success is False
    assert result.status_code == 502
    assert result.headers["x-aegis-failsafe-blocks"] == "1"


def test_executor_read_blocks_permission_denied_logs_warning_not_raise(
    tmp_path: Path,
) -> None:
    settings = get_settings().model_copy(
        update={"failsafe_audit_log_path": str(tmp_path / "mcp-failsafe.log")}
    )
    delegate = _StubDelegate(_ok_result())
    reader = _PermissionDeniedAuditReader(str(tmp_path / "mcp-failsafe.log"))
    executor = FailsafeCorrelatingExecutor(
        delegate, settings=settings, audit_reader=reader
    )

    result = asyncio.run(executor.execute(b"{}", {}))

    assert result.success is True
    assert result.backend == "kubernetes+failsafe"
    assert result.headers["x-aegis-failsafe-blocks"] == "0"


def test_correlating_executor_does_not_double_report_across_sequential_dispatches(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "mcp-failsafe.log"
    log_path.write_text("")
    settings = get_settings().model_copy(
        update={"failsafe_audit_log_path": str(log_path)}
    )
    block_line = (
        "[BLOCK] EXEC    tgid=1    pid=1    uid=0    cgid=7    "
        "comm=curl             target=/usr/bin/curl\n"
    )
    delegate = _OnceThenQuietDelegate(_ok_result(), log_path, block_line)
    reader = FailsafeAuditReader(str(log_path))
    executor = FailsafeCorrelatingExecutor(
        delegate, settings=settings, audit_reader=reader
    )

    first_result = asyncio.run(executor.execute(b"{}", {}))
    second_result = asyncio.run(executor.execute(b"{}", {}))

    assert first_result.headers["x-aegis-failsafe-blocks"] == "1"
    assert second_result.headers["x-aegis-failsafe-blocks"] == "0"
