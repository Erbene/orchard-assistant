"""``structlog`` pipeline with environment-aware **dual rendering**.

Render mode is resolved once, in this order:

1. ``LOG_FORMAT=console`` / ``LOG_FORMAT=json``      (explicit override)
2. ``ENVIRONMENT`` — ``production`` / ``staging`` -> json, ``development`` /
   ``local`` / ``test`` -> console
3. ``sys.stdout.isatty()`` — True -> console, else json

Everything (app code, ``uvicorn``, third-party libs) is routed through one
handler on ``stdout``. ``uvicorn.access`` is silenced — the request middleware
is the single source of access logs.

Performance
-----------
* ``make_filtering_bound_logger`` drops sub-level calls *before* the event dict
  is built — the cheap path for high-throughput services.
* ``cache_logger_on_first_use`` avoids re-resolving the pipeline per call.
* Rendering is synchronous; the only I/O is one ``write`` to ``stdout``. Run
  behind a container runtime / log shipper (12-Factor).
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any, Literal

import structlog
from structlog.types import EventDict, Processor

from ..config import Settings

__all__ = [
    "configure_logging",
    "get_logger",
    "redact",
    "SENSITIVE_KEYS",
    "correlation_id_var",
    "get_correlation_id",
]

# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password", "passwd", "pwd", "secret", "client_secret",
        "token", "access_token", "refresh_token", "id_token",
        "api_key", "apikey", "x-api-key",
        "authorization", "auth", "proxy-authorization",
        "cookie", "set-cookie", "session", "sessionid",
        "credentials", "private_key", "card_number", "cvv", "ssn",
    }
)
_REDACTED = "***REDACTED***"
_MAX_DEPTH = 8


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEYS)


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return a copy of *value* with anything under a sensitive key masked.

    Pure (never mutates input); recurses into mappings and sequences.
    """
    if _depth >= _MAX_DEPTH:
        return value
    if isinstance(value, Mapping):
        return {
            key: _REDACTED
            if _is_sensitive(str(key))
            else redact(item, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return type(value)(redact(item, _depth=_depth + 1) for item in value)
    return value


def _redact_processor(_: Any, __: str, event_dict: EventDict) -> EventDict:
    return redact(event_dict)  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Standard fields / helpers
# --------------------------------------------------------------------------

_PROCESS_ID = os.getpid()


def _standard_fields(environment: str) -> Processor:
    def processor(_: Any, __: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("environment", environment)
        event_dict.setdefault("process_id", _PROCESS_ID)
        return event_dict

    return processor


def _rename_logger(_: Any, __: str, event_dict: EventDict) -> EventDict:
    if "logger" in event_dict:  # emitted by add_logger_name
        event_dict["logger_name"] = event_dict.pop("logger")
    return event_dict


# --------------------------------------------------------------------------
# Correlation id (contextvars)
# --------------------------------------------------------------------------

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """The current request's correlation id (empty outside a request)."""
    return correlation_id_var.get()


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

_LEVELS: Mapping[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}

# Chatty third-party loggers whose DEBUG stream is rarely useful; floored at
# INFO even when the app runs at DEBUG.
_NOISY_FLOOR_INFO = (
    "asyncio", "watchfiles", "httpcore", "httpx", "urllib3",
    "chromadb", "mcp", "openai", "anthropic",
)

RenderMode = Literal["console", "json"]


def _render_mode(settings: Settings) -> RenderMode:
    fmt = (settings.log_format or "").strip().lower()
    if fmt in ("console", "json"):
        return fmt  # type: ignore[return-value]
    env = settings.environment.strip().lower()
    if env in ("production", "prod", "staging"):
        return "json"
    if env in ("development", "dev", "local", "test"):
        return "console"
    return "console" if sys.stdout.isatty() else "json"


def configure_logging(settings: Settings, *, stream: Any | None = None) -> None:
    """Install the dual-mode logging pipeline on the root logger (idempotent)."""
    level = _LEVELS.get(settings.log_level.upper(), logging.DEBUG)
    mode = _render_mode(settings)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        _standard_fields(settings.environment),
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        _redact_processor,
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    if mode == "console":
        render: list[Processor] = [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        render = [
            structlog.processors.dict_tracebacks,  # structured `exception` list
            _rename_logger,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *render],
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]  # single sink -> stdout, one schema
    root.setLevel(level)

    # Unify uvicorn into our pipeline; the middleware owns access logging.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").propagate = False

    noisy_floor = max(level, logging.INFO)
    for name in _NOISY_FLOOR_INFO:
        logging.getLogger(name).setLevel(noisy_floor)

    get_logger("app.core.logging").info(
        "logging.configured",
        level=settings.log_level.upper(),
        format=mode,
        environment=settings.environment,
    )


def get_logger(name: str | None = None) -> Any:
    """A bound, contextvars-aware structlog logger."""
    return structlog.get_logger(name)
