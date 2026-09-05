"""A2 groundedness grader for the Agronomist's chat answers.

Advisory-only (see ``eval/report.py::THRESHOLDS`` - this metric is
deliberately not in it). Three checks, cheapest first:

1. **Citation validity** - deterministic, no LLM. The Agronomist prompt tells
   the model to cite the source id(s) it used; :func:`extract_cited_ids`
   pulls every id-looking citation out of the answer and
   :func:`fabricated_citations` flags any that aren't among the ids actually
   retrieved. This is the highest-signal check and needs no model call.

2. **Claim extraction** - one LLM call. Breaks the answer into atomic factual
   horticultural claims (capped at :data:`MAX_CLAIMS`), ignoring hedges,
   questions, and pleasantries.

3. **Per-claim verification** - one LLM call per claim, run concurrently via
   ``asyncio.gather`` (so a 5-row agronomy suite doesn't serialize into
   minutes). Each claim gets one of three verdicts:

   - ``supported`` - entailed by the retrieved context.
   - ``general_knowledge`` - not in the retrieved context, but plausible
     general horticulture AND the answer said as much. This bucket exists
     because the Agronomist is explicitly allowed to fall back on its own
     knowledge (:data:`app.agent.agronomist.AGRONOMIST_SYSTEM_PROMPT`) - a
     claim absent from the retrieved passages is not automatically a
     hallucination.
   - ``unsupported`` - not in the retrieved context and not flagged as
     general knowledge either; presented as if it came from the sources.
     This is the actual hallucination bucket.

A model call that raises (timeout, malformed structured output, Ollama
unreachable mid-run) is handled defensively, matching ``eval/judge.py``'s
style: claim extraction fails to an empty claim list, and a failed per-claim
verification is recorded as ``unsupported`` with an error reason - the
conservative (fail-safe, not silently-pass) side, same call ``judge.py``
makes when its own model call errors.

This module intentionally does not import from or edit ``eval/judge.py`` -
see the coordination note in the eval package about a peer session's
in-flight work there.
"""
from __future__ import annotations

import asyncio
import re
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.agronomist import format_priority_context
from app.agent.ollama import chat_model
from app.config import Settings
from app.services.source_service import FusedSource

MAX_CLAIMS = 8

# Liberal citation matcher: catches "ID: 3", "(ID 3)", "source 3",
# "Sources: 3, 5", "sources 3 and 5". First finds an "ID"/"source(s)" cue
# followed by a run of comma/"and"/"&"-separated digits, then pulls every
# number out of that run - so a single citation clause naming several ids is
# not under-counted.
_CITATION_CLUSTER_RE = re.compile(
    r"\b(?:ID|source)s?\s*[:#]?\s*((?:\d+\s*(?:,|and|&)?\s*)+)", re.IGNORECASE
)
_NUM_RE = re.compile(r"\d+")


def extract_cited_ids(answer: str) -> set[int]:
    """Deterministic extraction of the source ids an answer claims to cite."""
    ids: set[int] = set()
    for cluster in _CITATION_CLUSTER_RE.findall(answer):
        ids.update(int(n) for n in _NUM_RE.findall(cluster))
    return ids


def fabricated_citations(answer: str, retrieved_ids: list[int]) -> list[int]:
    """Cited ids that were never among the retrieved sources - a fabricated
    citation. Implements the "zero hallucinated facts / 100% cited claims"
    commitment directly; ``chat-agronomy-04-not-covered`` exists to catch
    exactly this."""
    allowed = set(retrieved_ids)
    return sorted(extract_cited_ids(answer) - allowed)


class _ClaimList(BaseModel):
    claims: list[str] = Field(default_factory=list)


_CLAIM_SYSTEM = (
    "Extract the atomic factual horticultural claims from the assistant's "
    "reply below - one claim per fact, each a short standalone sentence. "
    "Ignore hedges, questions, pleasantries, and meta-statements about what "
    "the notes do or don't cover (e.g. 'my notes don't mention this' is not "
    "a claim). Only factual assertions about plants, care, pests, timing, or "
    f"products. Return at most {MAX_CLAIMS} claims; if there are none, "
    "return an empty list."
)

Verdict = Literal["supported", "general_knowledge", "unsupported"]


class _ClaimVerdict(BaseModel):
    verdict: Verdict
    reason: str = ""


_VERIFY_SYSTEM = (
    "You check ONE factual claim from an orchard assistant's reply against "
    "the retrieved knowledge-base context the assistant was given. Decide "
    "exactly one verdict:\n"
    "- 'supported': the claim is entailed by the retrieved context.\n"
    "- 'general_knowledge': the claim is NOT in the retrieved context, but "
    "is plausible general horticultural knowledge, AND the assistant's "
    "reply makes clear that part comes from general knowledge rather than "
    "the linked notes.\n"
    "- 'unsupported': the claim is not in the retrieved context and the "
    "reply does not flag it as general knowledge - it reads as if it came "
    "from the sources. This is the hallucination case.\n"
    "Answer with the verdict and one short sentence of reasoning."
)


def _client(settings: Settings, schema: type[BaseModel]):
    return chat_model(
        settings,
        model=settings.grounding_model,
        temperature=0.0,
        timeout=60.0,
    ).with_structured_output(schema)


async def _extract_claims(settings: Settings, answer: str) -> list[str]:
    if not answer.strip():
        return []
    llm = _client(settings, _ClaimList)
    try:
        out: _ClaimList = await llm.ainvoke(
            [SystemMessage(_CLAIM_SYSTEM), HumanMessage(answer)]
        )
    except Exception:  # noqa: BLE001 - never crash the eval run
        return []
    return [c.strip() for c in out.claims if c.strip()][:MAX_CLAIMS]


class ClaimDetail(TypedDict):
    claim: str
    verdict: Verdict
    reason: str


async def _verify_claim(
    settings: Settings, claim: str, *, context: str, answer: str
) -> ClaimDetail:
    llm = _client(settings, _ClaimVerdict)
    prompt = (
        f"Claim to check:\n{claim}\n\n"
        f"Retrieved context (ranked, highest priority first):\n{context}\n\n"
        f"Full assistant reply (for tone / flagging cues only):\n{answer}"
    )
    try:
        out: _ClaimVerdict = await llm.ainvoke(
            [SystemMessage(_VERIFY_SYSTEM), HumanMessage(prompt)]
        )
    except Exception as exc:  # noqa: BLE001 - fail safe, not silent-pass
        return {
            "claim": claim,
            "verdict": "unsupported",
            "reason": f"verify error: {str(exc)[:120]}",
        }
    return {"claim": claim, "verdict": out.verdict, "reason": out.reason}


class GroundednessResult(TypedDict):
    claims_total: int
    supported: int
    general_knowledge: int
    unsupported: int
    fabricated_citations: list[int]
    claims: list[ClaimDetail]


async def check_groundedness(
    settings: Settings, *, answer: str, retrieved: list[FusedSource]
) -> GroundednessResult:
    """Run all three checks for one Agronomist answer.

    ``retrieved`` is the ``AgronomistResult.retrieved`` / state ``retrieved``
    provenance - the same ``FusedSource`` groups the model was shown, rendered
    here without the general-knowledge placeholder block (that block carries
    no real information; the verdict logic itself is what decides whether a
    claim is legitimate general knowledge).
    """
    retrieved_ids = [g["source_id"] for g in retrieved]
    context = format_priority_context(retrieved, include_general_knowledge=False)
    if not retrieved:
        context = "(No linked knowledge-base passages were retrieved for this question.)"

    claims = await _extract_claims(settings, answer)
    details: list[ClaimDetail] = []
    if claims:
        details = list(
            await asyncio.gather(
                *(
                    _verify_claim(settings, c, context=context, answer=answer)
                    for c in claims
                )
            )
        )

    counts = {"supported": 0, "general_knowledge": 0, "unsupported": 0}
    for d in details:
        counts[d["verdict"]] += 1

    return {
        "claims_total": len(details),
        "supported": counts["supported"],
        "general_knowledge": counts["general_knowledge"],
        "unsupported": counts["unsupported"],
        "fabricated_citations": fabricated_citations(answer, retrieved_ids),
        "claims": details,
    }
