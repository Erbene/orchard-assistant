"""The Agronomist agent: system prompt + Consensus Fusion context formatting.

The knowledge sources linked to a tree are an *ordered* list - the order set
in the UI (``tree_sources.priority_order``) is an explicit authority ranking.
:func:`format_priority_context` renders retrieved chunks under numbered
priority headers, and :data:`AGRONOMIST_SYSTEM_PROMPT` tells the model to break
ties in favour of the higher-ranked source.
"""
from __future__ import annotations

from collections.abc import Sequence

from ..services.source_service import FusedSource

AGRONOMIST_SYSTEM_PROMPT: str = (
    "You are the Orchard Agronomist. Answer horticultural questions using ONLY "
    "the retrieved knowledge-base passages provided below; do not fall back on "
    "general knowledge. Always cite the source id(s) you used. If the passages "
    "do not cover the question, say so plainly.\n\n"
    "The sources are ranked by the grower's explicit authority order. If linked "
    "sources provide conflicting advice (e.g. timing, chemical treatments, or "
    "pruning severity), strictly resolve disputes in favour of the source with "
    "the higher priority rank (Priority 1 > Priority 2 > ...). When you override "
    "a lower-priority source, state which source you followed and which you "
    "set aside, and why."
)


def format_priority_context(groups: Sequence[FusedSource]) -> str:
    """Render fused results as priority-headed blocks for the prompt context::

        [PRIORITY 1 SOURCE: Florida Mango Care Guide (ID: 3)]
        - chunk
        - chunk

        [PRIORITY 2 SOURCE: Pruning Basics (ID: 12)]
        - chunk

    ``groups`` must already be in rank order (as returned by
    ``SourceService.search``).
    """
    blocks: list[str] = []
    for group in groups:
        header = (
            f"[PRIORITY {group['rank']} SOURCE: {group['name']} "
            f"(ID: {group['source_id']})]"
        )
        body = "\n".join(f"- {chunk.strip()}" for chunk in group["chunks"])
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)
