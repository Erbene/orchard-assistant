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
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from ..config import Settings
from ..core.logging import get_logger
from .care_plan import CATEGORIES, scale
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
        model=settings.agronomist_model,
        base_url=settings.ollama_base_url,
        temperature=0.2,
        client_kwargs={"timeout": 90.0},  # a 14B model on CPU is slow
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


# --------------------------------------------------------------------------
# Care Plan generation
# --------------------------------------------------------------------------

CARE_PLAN_SYSTEM_PROMPT: str = (
    "You are the Orchard Agronomist building a ROUTINE, RECURRING care plan for "
    "ONE tree. Use the context blocks below (linked notes first, then general "
    "knowledge - same authority rules as always).\n\n"
    "Return 4 to 9 recurring maintenance tasks that keep this species/variety "
    "healthy. For each task give:\n"
    "- name: a short imperative label (e.g. 'Nitrogen feed', 'Structural prune').\n"
    "- category: EXACTLY one of "
    f"{', '.join(CATEGORIES)}. Pick 'other' only if nothing else fits.\n"
    "- rate_class: 'light', 'standard' or 'heavy' - how heavy this species is a "
    "feeder / how vigorous its growth (affects amounts, which the SYSTEM "
    "computes - you do NOT).\n"
    "- interval_days: how often it recurs (integer days; seasonal jobs -> ~90/"
    "180/365).\n"
    "- priority_score: 0-10, how important skipping it is (safety/disease high).\n"
    "- baseline_question: if the first due date depends on when it was last "
    "done, a short question to ask the grower (e.g. 'When was copper fungicide "
    "last applied?'); otherwise null.\n\n"
    "Do NOT invent quantities, minutes, or product volumes - the system scales "
    "those from the tree's measured size. Do NOT include one-off establishment "
    "tasks. Prefer the grower's linked notes for timing and product choices."
)


class _PlanItem(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: Literal[
        "fertilize", "mulch", "prune", "scout", "spray",
        "irrigation", "weed", "stake", "soil_test", "other",
    ]
    rate_class: Literal["light", "standard", "heavy"] = "standard"
    interval_days: int = Field(gt=0, le=730)
    priority_score: float = Field(ge=0, le=10, default=5.0)
    baseline_question: str | None = None


class _CarePlanModel(BaseModel):
    items: list[_PlanItem] = Field(min_length=1, max_length=12)


class CarePlanDraft(TypedDict):
    templates: list[dict]      # ready-to-insert task_templates rows (no id/tree_id)
    source_ids: list[int]


async def generate_care_plan(
    *,
    tree: dict,
    sources: SourceService,
    settings: Settings,
) -> CarePlanDraft:
    """Ask the router-grade model (`AGENT_MODEL`) for a recurring task list for
    ``tree``, then scale each item to the tree's canopy size deterministically
    (``app.agent.care_plan``). ``tree`` is a row dict with ``tree_id``,
    ``species``, ``variety``, ``height_m``, ``canopy_spread_m``."""
    tree_id = tree["tree_id"]
    query = (
        f"routine annual care schedule for a {tree.get('variety', '')} "
        f"{tree.get('species', '')} tree: fertilizing, pruning, pest and "
        f"disease management, mulching, irrigation"
    )
    scope = await sources.allowed_source_ids(tree_id)
    groups = await sources.search(query, source_ids=scope or None)
    context = format_priority_context(groups, include_general_knowledge=True)
    if not groups:
        context = "(No linked notes for this tree.)\n\n" + context

    height = tree.get("height_m")
    spread = tree.get("canopy_spread_m")
    profile = (
        f"Tree: {tree.get('variety', '')} {tree.get('species', '')}. "
        f"Height: {height if height is not None else 'not recorded'} m. "
        f"Canopy spread: {spread if spread is not None else 'not recorded'} m."
    )

    llm = ChatOllama(
        model=settings.agent_model,
        base_url=settings.ollama_base_url,
        temperature=0.1,
        client_kwargs={"timeout": 90.0},
    ).with_structured_output(_CarePlanModel)
    try:
        plan: _CarePlanModel = await llm.ainvoke(
            [
                SystemMessage(CARE_PLAN_SYSTEM_PROMPT),
                HumanMessage(f"{profile}\n\nContext:\n{context}"),
            ]
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("agronomist.care_plan.failed", error=str(exc)[:200])
        raise LLMUnavailable from exc

    source_ids = [g["source_id"] for g in groups]
    templates: list[dict] = []
    for item in plan.items:
        scaled = scale(
            item.category,
            item.rate_class,
            height_m=float(height) if height is not None else None,
            spread_m=float(spread) if spread is not None else None,
        )
        templates.append(
            {
                "name": item.name.strip(),
                "category": item.category,
                "rate_class": item.rate_class,
                "interval_days": item.interval_days,
                "estimated_minutes": scaled.estimated_minutes,
                "priority_score": float(item.priority_score),
                "required_resources": scaled.required_resources,
                "resource_plan": [r.as_dict() for r in scaled.resource_plan],
                "baseline_question": (item.baseline_question or "").strip() or None,
                "source_ids": source_ids,
            }
        )

    _log.info("agronomist.care_plan", tree_id=tree_id, count=len(templates))
    return {"templates": templates, "source_ids": source_ids}


def rescale_template(template: dict, tree: dict) -> dict:
    """Recompute ``estimated_minutes`` / ``resource_plan`` / ``required_resources``
    for a template after its ``category`` / ``rate_class`` or the tree's size
    changed. Returns the patch to apply."""
    scaled = scale(
        template["category"],
        template["rate_class"],
        height_m=_num(tree.get("height_m")),
        spread_m=_num(tree.get("canopy_spread_m")),
        fallback_minutes=template.get("estimated_minutes"),
    )
    return {
        "estimated_minutes": scaled.estimated_minutes,
        "required_resources": scaled.required_resources,
        "resource_plan": [r.as_dict() for r in scaled.resource_plan],
    }


def _num(value: object) -> float | None:
    return float(value) if value is not None else None
