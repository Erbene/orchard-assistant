"""Framework-agnostic domain errors.

Services raise these. The API layer (and only the API layer) maps them to
HTTP status codes. A future MCP tool layer can map them to tool errors
instead, without touching service code.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all business-rule failures."""


class NotFoundError(DomainError):
    """A requested entity does not exist."""


class ConflictError(DomainError):
    """The operation violates a uniqueness or referential constraint."""


class DomainValidationError(DomainError):
    """A free-text value failed validation-agent checks."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class RachioNotConfigured(DomainError):
    """A Rachio call was attempted but ``RACHIO_API_KEY`` is not set."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "Rachio integration is not configured. Set RACHIO_API_KEY to "
            "connect your irrigation controller."
        )


class RachioError(DomainError):
    """The Rachio API returned an error or was unreachable."""
