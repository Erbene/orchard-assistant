"""Validation Agent interface + placeholder implementations.

Domain fields (``species``, ``variety``, ``soil_drainage``, ``water_source``) are
**free text**. There are no enums and no closed vocabularies - a value is never
rejected for being "unrecognized". The agent's only job is light normalization
(trim / collapse whitespace) and, in future, enrichment.

The *contract* is what matters: a validator takes a field name and a raw
string and returns a :class:`ValidationOutcome` with a ``canonical`` form. The
service layer awaits this hook before writing, so a smarter implementation
(:class:`LLMValidationAgent`) can later add real resolution without touching
the services.

Nothing here imports FastAPI. These helpers are plain async callables and can
be reused directly by an MCP server or a batch job.
"""
from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ValidationOutcome(BaseModel):
    """Result of normalizing one free-text field value."""

    field: str
    original: str
    canonical: str
    is_valid: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str | None = None


@runtime_checkable
class ValidationAgent(Protocol):
    """Any object that can normalize a free-text domain value."""

    async def validate(self, field: str, value: str) -> ValidationOutcome: ...


def _normalize(value: str) -> str:
    """Trim and collapse internal whitespace. No casing/slug/synonym changes -
    what the user typed is what gets stored."""
    return re.sub(r"\s+", " ", value).strip()


# --------------------------------------------------------------------------
# Default: permissive passthrough
# --------------------------------------------------------------------------

class PassthroughValidationAgent:
    """Accepts any value. Normalizes whitespace only; never rejects."""

    async def validate(self, field: str, value: str) -> ValidationOutcome:
        return ValidationOutcome(
            field=field,
            original=value,
            canonical=_normalize(value),
        )


# --------------------------------------------------------------------------
# Future: LLM / MCP-backed validator (placeholder)
# --------------------------------------------------------------------------

class LLMValidationAgent:
    """Placeholder for an agent-backed validator.

    Wire ``_call_model`` to a local LLM, the Anthropic API, or an MCP tool
    such as ``resolve_domain_term``. On any failure it falls back to
    ``fallback`` (default: the passthrough agent) so the write path degrades
    gracefully instead of 500-ing. A real implementation should still lean
    toward *accepting* free text - enriching, not gatekeeping.
    """

    def __init__(
        self,
        client: object | None = None,
        model: str = "claude-opus-5",
        fallback: ValidationAgent | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._fallback: ValidationAgent = fallback or PassthroughValidationAgent()

    async def _call_model(self, field: str, value: str) -> ValidationOutcome:
        # TODO: real implementation, e.g.
        #   resp = await self._client.messages.create(
        #       model=self._model,
        #       messages=[{"role": "user", "content": _prompt(field, value)}],
        #   )
        #   return ValidationOutcome(**_parse_result(resp))
        raise NotImplementedError("LLMValidationAgent is a placeholder")

    async def validate(self, field: str, value: str) -> ValidationOutcome:
        if self._client is None:
            return await self._fallback.validate(field, value)
        try:
            return await self._call_model(field, value)
        except Exception:  # noqa: BLE001 - deliberate graceful fallback
            return await self._fallback.validate(field, value)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

def get_default_validation_agent() -> ValidationAgent:
    """Swap this out (or make it env-driven) to roll out an agent validator."""
    return PassthroughValidationAgent()
