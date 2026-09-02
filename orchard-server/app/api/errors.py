"""Translate domain exceptions into HTTP responses.

This is the *only* place that knows both vocabularies. Services stay clean.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from ..services.exceptions import (
    ConflictError,
    DomainValidationError,
    LLMUnavailable,
    NotFoundError,
    RachioError,
    RachioNotConfigured,
)

_STATUS = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    DomainValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    RachioNotConfigured: status.HTTP_503_SERVICE_UNAVAILABLE,
    RachioError: status.HTTP_502_BAD_GATEWAY,
    LLMUnavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    @app.exception_handler(ConflictError)
    @app.exception_handler(DomainValidationError)
    @app.exception_handler(RachioNotConfigured)
    @app.exception_handler(RachioError)
    @app.exception_handler(LLMUnavailable)
    async def _handle(_: Request, exc: Exception) -> JSONResponse:
        code = _STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
        body: dict[str, object] = {"detail": str(exc)}
        if isinstance(exc, DomainValidationError):
            body["field"] = exc.field
        return JSONResponse(status_code=code, content=body)
