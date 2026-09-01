"""``@log_execution_time`` - trace an internal call's inputs, output, and
wall-clock duration at ``DEBUG`` (errors at ``ERROR`` with a traceback).

Works transparently on ``def`` and ``async def``. Arguments and results are
redacted and length-capped before they hit the log.

    from app.utils.decorators import log_execution_time

    @log_execution_time
    async def create_task(self, payload: TaskCreate) -> TaskRead: ...

    @log_execution_time(log_result=False)          # noisy return value
    def list_pending(self, *, before: str | None = None) -> list[Row]: ...
"""
from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar, cast, overload

from ..core.logging import get_logger, redact

P = ParamSpec("P")
R = TypeVar("R")

_MAX_REPR = 512


def _preview(value: Any) -> Any:
    safe = redact(value) if isinstance(value, (dict, list, tuple, set)) else value
    text = repr(safe)
    return text if len(text) <= _MAX_REPR else f"{text[:_MAX_REPR]}…({len(text)} chars)"


def _arguments(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
    except TypeError:
        return {"args": [_preview(a) for a in args], "kwargs": redact(kwargs)}
    data = dict(bound.arguments)
    data.pop("self", None)
    data.pop("cls", None)
    return {key: _preview(val) for key, val in redact(data).items()}


@overload
def log_execution_time(func: Callable[P, R], /) -> Callable[P, R]: ...
@overload
def log_execution_time(
    *,
    log_args: bool = ...,
    log_result: bool = ...,
    logger_name: str | None = ...,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def log_execution_time(
    func: Callable[P, R] | None = None,
    /,
    *,
    log_args: bool = True,
    log_result: bool = True,
    logger_name: str | None = None,
) -> Any:
    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        log = get_logger(logger_name or fn.__module__)
        name = fn.__qualname__

        def _start(args: tuple[Any, ...], kwargs: dict[str, Any]) -> float:
            if log_args:
                log.debug("call.start", function=name, arguments=_arguments(fn, args, kwargs))
            return time.perf_counter()

        def _ok(started: float, result: R) -> None:
            extra = {"result": _preview(result)} if log_result else {}
            log.debug("call.end", function=name, duration_ms=_ms(started), **extra)

        def _fail(started: float, exc: BaseException) -> None:
            log.error(
                "call.error",
                function=name,
                duration_ms=_ms(started),
                error_type=type(exc).__name__,
                error_detail=str(exc),
                exc_info=exc,
            )

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                started = _start(args, kwargs)
                try:
                    result = await cast(Callable[P, Awaitable[R]], fn)(*args, **kwargs)
                except BaseException as exc:
                    _fail(started, exc)
                    raise
                _ok(started, result)
                return result

            return cast(Callable[P, R], awrapper)

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = _start(args, kwargs)
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                _fail(started, exc)
                raise
            _ok(started, result)
            return result

        return wrapper

    return decorate(func) if func is not None else decorate


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
