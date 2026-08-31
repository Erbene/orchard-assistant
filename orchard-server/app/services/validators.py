"""Validation Agent interface + placeholder implementations.

The *contract* is the important part: a validator takes a field name and a
raw free-text string, and returns a :class:`ValidationOutcome` describing
whether the value is domain-valid and what its canonical form is.

Today the default implementation is a deterministic vocabulary/synonym
matcher (:class:`StaticVocabularyValidationAgent`). Tomorrow it can be swapped
for :class:`LLMValidationAgent` - a local model or an MCP tool call - without
any change to the service layer, because both satisfy :class:`ValidationAgent`.

Nothing here imports FastAPI. These helpers are plain async callables and can
be reused directly by an MCP server or a batch job.
"""
from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ValidationOutcome(BaseModel):
    """Result of validating one free-text field value."""

    field: str
    original: str
    canonical: str
    is_valid: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


@runtime_checkable
class ValidationAgent(Protocol):
    """Any object that can canonicalize/validate a free-text domain value."""

    async def validate(self, field: str, value: str) -> ValidationOutcome: ...


# --------------------------------------------------------------------------
# Normalization helpers
# --------------------------------------------------------------------------

def _slug(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", value.strip().lower()).strip("_")


def _titleize(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


# --------------------------------------------------------------------------
# Default placeholder: deterministic vocabulary matcher
# --------------------------------------------------------------------------

class StaticVocabularyValidationAgent:
    """Deterministic stand-in for a real agent/LLM validator.

    - *Closed-vocabulary* fields (``species``, ``soil_drainage``) are matched
      against a known set plus a synonym table. Unknown values are rejected
      (``is_valid=False``) so the service layer can surface a 422.
    - *Open* fields (``variety``) are always accepted; only whitespace/casing
      is normalized. Confidence is < 1.0 to signal "pending agent resolution".

    Replace the body of :meth:`validate` with a call to your model/MCP tool;
    keep the signature identical.
    """

    KNOWN_VOCAB: dict[str, set[str]] = {
        "species": {"mango", "sapodilla", "sugar_apple"},
        "soil_drainage": {"sandy_fast_draining", "loamy"},
    }

    SYNONYMS: dict[str, dict[str, str]] = {
        "species": {
            "sugar_apple": "sugar_apple",
            "custard_apple": "sugar_apple",
            "sweetsop": "sugar_apple",
            "atis": "sugar_apple",
            "chico": "sapodilla",
            "chicoo": "sapodilla",
            "sapote": "sapodilla",
            "naseberry": "sapodilla",
        },
        "soil_drainage": {
            "sandy": "sandy_fast_draining",
            "sand": "sandy_fast_draining",
            "fast_draining": "sandy_fast_draining",
            "well_drained": "sandy_fast_draining",
            "loam": "loamy",
        },
    }

    OPEN_TEXT_FIELDS: set[str] = {"variety"}

    async def validate(self, field: str, value: str) -> ValidationOutcome:
        original = value

        if field in self.KNOWN_VOCAB:
            slug = _slug(value)
            canonical = self.SYNONYMS.get(field, {}).get(slug, slug)
            is_valid = canonical in self.KNOWN_VOCAB[field]
            return ValidationOutcome(
                field=field,
                original=original,
                canonical=canonical if is_valid else slug,
                is_valid=is_valid,
                confidence=1.0 if is_valid else 0.0,
                reason=None
                if is_valid
                else f"{value!r} is not a recognized {field}; "
                f"expected one of {sorted(self.KNOWN_VOCAB[field])}",
            )

        if field in self.OPEN_TEXT_FIELDS:
            return ValidationOutcome(
                field=field,
                original=original,
                canonical=_titleize(value),
                is_valid=True,
                confidence=0.5,
                reason="accepted as free text; canonical form pending agent resolution",
            )

        # Unknown field: pass through untouched but flag low confidence.
        return ValidationOutcome(
            field=field,
            original=original,
            canonical=value.strip(),
            is_valid=True,
            confidence=0.3,
            reason=f"no validation rule registered for field {field!r}",
        )


# --------------------------------------------------------------------------
# Future: LLM / MCP-backed validator (placeholder)
# --------------------------------------------------------------------------

class LLMValidationAgent:
    """Placeholder for an agent-backed validator.

    Wire ``_call_model`` to a local LLM, the Anthropic API, or an MCP tool
    such as ``resolve_domain_term``. On any failure it falls back to
    ``fallback`` (default: the deterministic matcher) so the write path
    degrades gracefully instead of 500-ing.
    """

    def __init__(
        self,
        client: object | None = None,
        model: str = "claude-sonnet-5",
        fallback: ValidationAgent | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._fallback: ValidationAgent = fallback or StaticVocabularyValidationAgent()

    async def _call_model(self, field: str, value: str) -> ValidationOutcome:
        # TODO: real implementation, e.g.
        #   resp = await self._client.messages.create(
        #       model=self._model,
        #       tools=[DOMAIN_RESOLVER_TOOL],
        #       messages=[{"role": "user", "content": _prompt(field, value)}],
        #   )
        #   return ValidationOutcome(**_parse_tool_result(resp))
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
    return StaticVocabularyValidationAgent()
