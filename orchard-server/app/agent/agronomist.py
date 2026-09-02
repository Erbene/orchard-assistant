"""The Agronomist agent: KB-grounded answers with Consensus-Fusion context.

The knowledge sources linked to a tree are an *ordered* list - the order set
in the UI (``tree_sources.priority_order``) is an explicit authority ranking.
:func:`format_priority_context` renders retrieved chunks under numbered
priority headers, then (for the Agronomist) appends the model's own general
horticultural knowledge as one more block ranked *below* every linked source.
:data:`AGRONOMIST_SYSTEM_PROMPT` tells the model to break ties in favour of the
higher-ranked source - so general knowledge fills gaps but never overrides the
grower's notes. :func:`run_agronomist` is the end-to-end node the Orchestrator
routes ``agronomy`` turns to.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from ..config import Settings
from ..core.logging import get_logger
from ..services.exceptions import LLMUnavailable
from ..services.source_service import FusedSource, SourceService

_log = get_logger("app.agronomist")

GENERAL_KNOWLEDGE_LABEL = "General horticultural knowledge"

AGRONOMIST_SYSTEM_PROMPT: str = (
    "You are the Orchard Agronomist. Answer the grower's horticultural questions "
    "from the context blocks below. They are ranked by the grower's explicit "
    "authority order (Priority 1 > Priority 2 > ...); the final block, "
    f"'{GENERAL_KNOWLEDGE_LABEL}', is your own general knowledge and always "
    "ranks last.\n\n"
    "Use the linked knowledge-base passages first. Fall back on general "
    "knowledge only where those passages do not address the question, and never "
    "to override them - if general knowledge conflicts with any linked source, "
    "the linked source wins.\n\n"
    "Always cite the source id(s) you used; when part of the answer rests on "
    "general knowledge rather than a linked source, say so explicitly. If linked "
    "sources conflict with each other (timing, chemical treatments, pruning "
    "severity), resolve the dispute in favour of the higher-ranked source and "
    "state which source you followed, which you set aside, and why. If nothing "
    "- neither the passages nor general knowledge - covers the question, say so "
    "plainly."
)


def format_priority_context(
    groups: Sequence[FusedSource], *, include_general_knowledge: bool = False
) -> str:
    """Render fused results as priority-headed blocks for the prompt context::

        [PRIORITY 1 SOURCE: Florida Mango Care Guide (ID: 3)]
        - chunk
        - chunk

        [PRIORITY 2 SOURCE: Pruning Basics (ID: 12)]
        - chunk

    ``groups`` must already be in rank order (as returned by
    ``SourceService.search``).

    With ``include_general_knowledge`` (the Agronomist path), a final block is
    appended one rank below the last linked source, standing in for the model's
    own general knowledge so it participates in the same authority ordering
    instead of being forbidden.
    """
    blocks: list[str] = []
    for group in groups:
        header = (
            f"[PRIORITY {group['rank']} SOURCE: {group['name']} "
            f"(ID: {group['source_id']})]"
        )
        body = "\n".join(f"- {chunk.strip()}" for chunk in group["chunks"])
        blocks.append(f"{header}\n{body}")

    if include_general_knowledge:
        rank = len(groups) + 1
        blocks.append(
            f"[PRIORITY {rank} SOURCE: {GENERAL_KNOWLEDGE_LABEL} "
            "(no ID - lowest authority)]\n"
            "- Your own general knowledge of orchard horticulture. Use it only "
            "where the higher-priority sources above are silent; it must not "
            "override them."
        )
    return "\n\n".join(blocks)


class AgronomistResult(TypedDict):
    answer: str
    source_ids: list[int]


async def run_agronomist(
    question: str,
    *,
    tree_id: int | None,
    sources: SourceService,
    settings: Settings,
) -> AgronomistResult:
    """Retrieve the ranked KB passages for ``question`` (scoped to ``tree_id``
    when given) and have the local model answer - linked sources first,
    general knowledge only to fill the gaps they leave."""
    scope = await sources.allowed_source_ids(tree_id) if tree_id else None
    groups = await sources.search(question, source_ids=scope)
    context = format_priority_context(groups, include_general_knowledge=True)
    if not groups:
        context = (
            "(No linked knowledge-base passages matched this question.)\n\n" + context
        )

    llm = ChatOllama(
        model=settings.agent_model,
        base_url=settings.ollama_base_url,
        temperature=0.2,
        client_kwargs={"timeout": 60.0},
    )
    try:
        msg = await llm.ainvoke(
            [
                SystemMessage(AGRONOMIST_SYSTEM_PROMPT),
                HumanMessage(f"Question: {question}\n\nRetrieved sources:\n{context}"),
            ]
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("agronomist.answer.failed", error=str(exc)[:200])
        raise LLMUnavailable from exc

    source_ids = [g["source_id"] for g in groups]
    _log.info("agronomist.answered", sources=source_ids)
    return {"answer": (msg.content or "").strip(), "source_ids": source_ids}
