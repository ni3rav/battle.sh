"""Structured, non-blocking logging for the Relay and networking stack.

Logging is built on :mod:`structlog` rendered through the standard library so
that records flow through a :class:`logging.handlers.QueueListener`. The queue
moves all formatting and I/O onto a background thread, which keeps log calls
non-blocking for the asyncio event loop that runs the Relay and clients.

Output is JSON by default (suitable for production log ingestion) and can be
switched to a human-friendly console renderer. Entry points call
:func:`configure_logging` once; everything else uses :func:`get_logger` and
binds per-connection context (``session_id``, ``conn_id``, ``player_id``).
"""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import os
import queue
import sys
import tempfile
import uuid
from typing import Any, TextIO

import structlog

_DEFAULT_LEVEL = "INFO"
_DEFAULT_FORMAT = "json"

_configured = False
_listener: logging.handlers.QueueListener | None = None


class _PassthroughQueueHandler(logging.handlers.QueueHandler):
    """Queue records without pre-formatting so structlog metadata survives.

    The default ``QueueHandler.prepare`` renders the record to a string, which
    discards the structured event dict that :class:`ProcessorFormatter` needs.
    Records stay in-process, so enqueuing them untouched is safe.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record


def _resolve_level(level: str | None) -> int:
    name = (level or os.environ.get("BATTLE_SH_LOG_LEVEL") or _DEFAULT_LEVEL).upper()
    return logging.getLevelNamesMapping().get(name, logging.INFO)


def _resolve_format(fmt: str | None) -> str:
    return (fmt or os.environ.get("BATTLE_SH_LOG_FORMAT") or _DEFAULT_FORMAT).lower()


def _shared_processors() -> list[structlog.typing.Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging(
    *,
    component: str,
    level: str | None = None,
    fmt: str | None = None,
    stream: TextIO | None = None,
    log_file: str | None = None,
) -> structlog.stdlib.BoundLogger:
    """Configure process-wide structured logging and return a bound logger.

    Records are emitted through a queue so log I/O never blocks the event loop.
    ``log_file`` (or ``BATTLE_SH_LOG_FILE``) routes output to a file, which
    clients use to avoid corrupting the full-screen terminal UI; the Relay logs
    to ``stream`` (stderr by default). Safe to call more than once.
    """
    global _configured, _listener

    resolved_level = _resolve_level(level)
    resolved_format = _resolve_format(fmt)
    resolved_file = log_file or os.environ.get("BATTLE_SH_LOG_FILE")

    shared = _shared_processors()
    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Resolve configuration on every call so loggers created before
        # configure_logging (e.g. at import time) and reconfiguration both work.
        cache_logger_on_first_use=False,
    )

    if resolved_format == "console":
        renderer: structlog.typing.Processor = structlog.dev.ConsoleRenderer(
            colors=False
        )
    else:
        renderer = structlog.processors.JSONRenderer()

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    if resolved_file:
        os.makedirs(os.path.dirname(os.path.abspath(resolved_file)), exist_ok=True)
        terminal_handler: logging.Handler = logging.FileHandler(
            resolved_file, encoding="utf-8"
        )
    else:
        terminal_handler = logging.StreamHandler(stream or sys.stderr)
    terminal_handler.setFormatter(formatter)

    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
    queue_handler = _PassthroughQueueHandler(log_queue)

    root = logging.getLogger()
    if _listener is not None:
        _listener.stop()
        _listener = None
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(queue_handler)
    root.setLevel(resolved_level)

    # Surface the websockets library's own ping/pong/timeout diagnostics through
    # the same pipeline so connection health is observable end to end.
    logging.getLogger("websockets").setLevel(resolved_level)

    listener = logging.handlers.QueueListener(
        log_queue, terminal_handler, respect_handler_level=True
    )
    listener.start()
    _listener = listener
    if not _configured:
        atexit.register(shutdown_logging)
    _configured = True

    return get_logger(component=component)


def configure_client_logging(role: str) -> None:
    """Route client logs to a file so they never corrupt the terminal UI."""
    log_file = os.environ.get("BATTLE_SH_LOG_FILE")
    if not log_file:
        log_dir = os.path.join(tempfile.gettempdir(), "battle-sh")
        log_file = os.path.join(log_dir, f"{role}-{os.getpid()}.log")
    configure_logging(component=f"client-{role}", log_file=log_file)


def shutdown_logging() -> None:
    """Flush and stop the background log listener (idempotent)."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


def get_logger(**initial: Any) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger, optionally pre-bound with context fields."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger()
    if initial:
        return logger.bind(**initial)
    return logger


def new_conn_id() -> str:
    """Short, unique identifier for a single connection/session lifecycle."""
    return uuid.uuid4().hex[:12]
