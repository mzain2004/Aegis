"""Structured logging configuration for the Aegis proxy.

This module configures JSON logs through structlog so later phases can add
security and request context without changing the logging surface.

TODO: enrich log context with request IDs, approval IDs, and upstream traces
when those concepts exist.
"""

from __future__ import annotations

import logging
from typing import Any, Final

try:
    import structlog  # type: ignore

    _STRUCTLOG_AVAILABLE = True
except Exception:  # pragma: no cover - environment without structlog
    structlog = None  # type: ignore
    _STRUCTLOG_AVAILABLE = False


_LOGGING_CONFIGURED: bool = False
_DEFAULT_LEVEL: Final[str] = "INFO"


def configure_logging(level: str = _DEFAULT_LEVEL) -> None:
    """Configure standard library logging and structlog (if available).

    If `structlog` is not installed, we fall back to the stdlib logger so
    the application remains runnable in constrained environments.
    """

    global _LOGGING_CONFIGURED

    if _LOGGING_CONFIGURED:
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(message)s")

    if _STRUCTLOG_AVAILABLE and structlog is not None:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    _LOGGING_CONFIGURED = True


def get_logger(name: str) -> Any:
    """Return a logger instance.

    Prefer a structlog bound logger when available, otherwise fall back to a
    standard `logging.Logger` instance wrapped with a minimal interface.
    """

    if not _LOGGING_CONFIGURED:
        configure_logging()

    if _STRUCTLOG_AVAILABLE and structlog is not None:
        return structlog.get_logger(name)

    # lightweight fallback that mimics structlog's bound logger methods used
    logger = logging.getLogger(name)

    class _SimpleLogger:
        def __init__(self, _logger: logging.Logger) -> None:
            self._logger = _logger

        def info(self, *args: object, **kwargs: object) -> None:
            if args:
                msg = args[0]
            else:
                msg = ""
            if kwargs:
                msg = f"{msg} | {kwargs}"
            self._logger.info(msg)

        def debug(self, *args: object, **kwargs: object) -> None:
            if args:
                msg = args[0]
            else:
                msg = ""
            if kwargs:
                msg = f"{msg} | {kwargs}"
            self._logger.debug(msg)

        def warning(self, *args: object, **kwargs: object) -> None:
            if args:
                msg = args[0]
            else:
                msg = ""
            if kwargs:
                msg = f"{msg} | {kwargs}"
            self._logger.warning(msg)

        def error(self, *args: object, **kwargs: object) -> None:
            if args:
                msg = args[0]
            else:
                msg = ""
            if kwargs:
                msg = f"{msg} | {kwargs}"
            self._logger.error(msg)

        def bind(self, **kwargs: object) -> _SimpleLogger:
            # no-op for fallback; structlog adds context — phase 1 doesn't need it
            return self

    return _SimpleLogger(logger)
