from __future__ import annotations

import json
import logging
import sys
from typing import Any

import structlog

_DEBUG = False


def is_debug() -> bool:
    return _DEBUG


def setup_logging(*, debug: bool = False, level: str | None = None) -> None:
    global _DEBUG
    _DEBUG = debug

    if debug:
        log_level = getattr(logging, (level or "DEBUG").upper(), logging.DEBUG)
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    else:
        log_level = getattr(logging, (level or "WARNING").upper(), logging.WARNING)
        renderer = structlog.processors.JSONRenderer()

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
    )

    for name in ("httpx", "httpcore", "websockets", "asyncio"):
        logging.getLogger(name).setLevel(logging.DEBUG if debug else logging.WARNING)


def get_logger(name: str):
    return structlog.get_logger(name)


def debug_data(label: str, data: Any) -> None:
    """Fast terminal dump — only when DEBUG=true."""
    if not _DEBUG:
        return
    if isinstance(data, (dict, list)):
        text = json.dumps(data, default=str, separators=(",", ":"))
    else:
        text = str(data)
    print(f"[DEBUG] {label}: {text}", flush=True)
