"""Per-request context + performance middleware.

A **pure ASGI** middleware (not ``BaseHTTPMiddleware``) — no extra task group,
streaming-safe, minimal overhead under load. For every HTTP request it:

* clears ``structlog`` contextvars, then binds ``correlation_id`` (from an
  inbound ``X-Request-ID`` / ``X-Correlation-ID`` header, else a fresh UUID4),
  ``method``, ``path`` and ``client_ip`` — so every downstream log inherits
  the request context automatically;
* echoes the id back as ``X-Request-ID``;
* logs ``request.started`` and ``request.completed`` (``status_code``,
  ``duration_ms``);
* logs ``request.failed`` with the full traceback for anything that escapes
  the route, then re-raises so Starlette still returns its 500.
"""
from __future__ import annotations

import time
import uuid
from urllib.parse import parse_qs

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .logging import correlation_id_var, get_logger, redact

_log = get_logger("app.request")
_ID_HEADERS = (b"x-request-id", b"x-correlation-id")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = _correlation_id(scope)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            method=scope["method"],
            path=scope["path"],
            client_ip=_client_ip(scope),
        )
        token = correlation_id_var.set(correlation_id)

        status = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-request-id", correlation_id.encode()),
                    ],
                }
            await send(message)

        _log.info(
            "request.started",
            query=redact(_query(scope)) or None,
            user_agent=_header(scope, b"user-agent"),
        )
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            _log.exception(
                "request.failed",
                status_code=500,
                duration_ms=_ms(start),
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
            raise
        else:
            _log.info(
                "request.completed",
                status_code=status,
                duration_ms=_ms(start),
            )
        finally:
            structlog.contextvars.clear_contextvars()
            correlation_id_var.reset(token)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _correlation_id(scope: Scope) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() in _ID_HEADERS and value:
            return value.decode()[:128]
    return str(uuid.uuid4())


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode()
    return None


def _client_ip(scope: Scope) -> str | None:
    forwarded = _header(scope, b"x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else None


def _query(scope: Scope) -> dict[str, object]:
    raw = scope.get("query_string", b"")
    if not raw:
        return {}
    parsed = parse_qs(raw.decode(), keep_blank_values=True)
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
