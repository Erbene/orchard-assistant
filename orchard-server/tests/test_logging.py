"""Structured logging: redaction, correlation-id propagation, the decorator,
and dual-mode rendering."""
from __future__ import annotations

import asyncio
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.logging import configure_logging, get_logger, redact
from app.main import app
from app.utils.decorators import log_execution_time

_JSON = Settings(log_format="json")
_CONSOLE = Settings(log_format="console")


def test_redact_is_recursive_and_pure():
    src = {"password": "x", "ok": 1, "d": {"api_key": "y"}, "l": [{"token": "z"}]}
    assert redact(src) == {
        "password": "***REDACTED***",
        "ok": 1,
        "d": {"api_key": "***REDACTED***"},
        "l": [{"token": "***REDACTED***"}],
    }
    assert src["password"] == "x"  # input untouched


def test_render_mode_resolution():
    from app.core.logging import _render_mode

    assert _render_mode(Settings(log_format="console")) == "console"
    assert _render_mode(Settings(log_format="json")) == "json"
    assert _render_mode(Settings(environment="production")) == "json"
    assert _render_mode(Settings(environment="development")) == "console"


@pytest.fixture()
def logbuf():
    """Capture JSON log lines from every logger into a buffer."""
    buf = io.StringIO()
    configure_logging(_JSON, stream=buf)
    try:
        yield lambda: [
            json.loads(ln) for ln in buf.getvalue().splitlines() if ln.startswith("{")
        ]
    finally:
        configure_logging(_CONSOLE)  # restore a safe default for later tests


def test_standard_schema(logbuf):
    get_logger("svc.test").info("hello", n=1)
    line = logbuf()[-1]
    for key in ("timestamp", "level", "logger_name", "environment", "process_id", "message"):
        assert key in line, key
    assert (line["message"], line["logger_name"], line["level"]) == ("hello", "svc.test", "info")
    assert line["timestamp"].endswith("Z")


def test_correlation_id_propagates_to_downstream_logs(logbuf):
    @app.get("/_probe")
    async def _probe():  # noqa: ANN202 - test-only route
        get_logger("route.probe").info("inside handler")
        return {"ok": True}

    # no `with` -> lifespan (which would reconfigure logging) does not run
    resp = TestClient(app).get("/_probe", headers={"x-request-id": "corr-123"})

    assert resp.headers["x-request-id"] == "corr-123"
    lines = logbuf()
    handler_line = next(ln for ln in lines if ln["message"] == "inside handler")
    done_line = next(ln for ln in lines if ln["message"] == "request.completed")
    assert handler_line["correlation_id"] == "corr-123"  # inherited via contextvars
    assert (handler_line["method"], handler_line["path"]) == ("GET", "/_probe")
    assert done_line["correlation_id"] == "corr-123"
    assert done_line["status_code"] == 200
    assert isinstance(done_line["duration_ms"], (int, float))


def test_server_failure_logs_full_traceback(logbuf):
    @app.get("/_boom")
    async def _boom():  # noqa: ANN202 - test-only route
        raise RuntimeError("kaboom")

    resp = TestClient(app, raise_server_exceptions=False).get("/_boom")
    assert resp.status_code == 500

    failed = next(ln for ln in logbuf() if ln["message"] == "request.failed")
    assert failed["level"] == "error"
    assert failed["status_code"] == 500
    assert failed["error_type"] == "RuntimeError"
    assert failed["error_detail"] == "kaboom"
    assert "exception" in failed  # traceback captured


def test_decorator_logs_redacted_args_result_and_errors(logbuf):
    @log_execution_time
    async def work(x: int, token: str) -> dict:
        await asyncio.sleep(0)
        if x < 0:
            raise ValueError("negative")
        return {"password": "secret", "x": x}

    asyncio.run(work(2, token="abc"))
    with pytest.raises(ValueError):
        asyncio.run(work(-1, token="abc"))

    lines = logbuf()
    start = next(ln for ln in lines if ln["message"] == "call.start")
    end = next(ln for ln in lines if ln["message"] == "call.end")
    err = next(ln for ln in lines if ln["message"] == "call.error")

    assert start["arguments"]["token"] == "***REDACTED***"
    assert "***REDACTED***" in end["result"]  # nested "password" masked
    assert err["error_type"] == "ValueError"
    assert "exception" in err  # structured traceback (dict_tracebacks)
