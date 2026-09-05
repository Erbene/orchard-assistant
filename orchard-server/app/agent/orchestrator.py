"""The Orchestrator: classify each chat turn and route it.

Hybrid design - the SSE chat handles agronomy Q&A, task completions, and
refusals directly; a scheduling turn is handed off to the ``/schedule``
wizard (the Foreman's interrupt negotiation never runs in chat). The only
write the chat performs is ``mark_tasks_complete``.

One local-LLM call classifies the turn; only the ``agronomy`` route needs a
second call (retrieval + answer). Ollama is required - callers surface
``LLMUnavailable`` as a 503.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .ollama import chat_model

from ..config import Settings
from ..core.logging import get_logger
from ..core.tracing import traced
from ..services.exceptions import LLMUnavailable

_log = get_logger("app.orchestrator")

Route = Literal["agronomy", "schedule", "complete", "refuse", "smalltalk"]

_HISTORY_WINDOW = 8


class Classification(TypedDict):
    route: Route
    task_ids: list[int]
    reply: str


class _ClassificationModel(BaseModel):
    route: Literal["agronomy", "schedule", "complete", "refuse", "smalltalk"]
    task_ids: list[int] = Field(default_factory=list)
    reply: str = ""


ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the Orchard Assistant's router. Read the conversation and classify "
    "ONLY the user's latest message into exactly one route, and (except for "
    "`agronomy`) write the assistant's reply.\n\n"
    "Routes:\n"
    "- `agronomy`: a horticulture / plant-health / pest / disease / nutrition / "
    "pruning question, or anything the user wants answered from their ingested "
    "notes and sources. Leave `reply` empty - a separate step retrieves the "
    "sources and writes the answer.\n"
    "- `schedule`: the user wants a work plan for their orchard field work - to "
    "organize their day, decide what to do next, or fit orchard tasks into the "
    "time they have. Set `reply` to one sentence that briefly acknowledges the "
    "request and says you're opening the planner (e.g. \"Sure - opening the "
    "planner so you can set up a work session.\"). Do NOT build a schedule here. "
    "This route is ONLY for planning orchard field-work sessions - never for "
    "booking appointments, services, deliveries, or anything off the orchard "
    "(those are `refuse`).\n"
    "- `complete`: the user reports that specific task(s) are already done. "
    "Extract EVERY task number the user wrote - any integer - into `task_ids` "
    "('done with 3 and 5' -> [3, 5]; 'finished 999' -> [999]), and set `reply` "
    "to a plain one-line acknowledgement with NO question (e.g. 'Got it.'). "
    "ONLY when the user names a finished task with no number at all (e.g. 'I "
    "wrapped up the mulching') do you use an EMPTY `task_ids` and make `reply` "
    "ask which task number they mean. Never invent a number the user did not "
    "write.\n"
    "- `refuse`: the request is unsafe, out of scope, or an action the chat "
    "cannot take. Set `reply` to a brief, polite refusal.\n"
    "  * UNSAFE - would harm people, crops, or the environment: exceeding a "
    "pesticide label rate, mixing incompatible / toxic chemicals (bleach + "
    "ammonia), applying pesticides near people or children, or hiding / dropping "
    "/ deleting a safety-critical overdue task so it stops being flagged. "
    "Briefly say why and offer a safe alternative.\n"
    "  * OUT OF SCOPE - not about this orchard's trees, tasks, or ingested "
    "knowledge: weather, travel, errands, appointments, vehicle or equipment "
    "servicing, general chit-chat, coding.\n"
    "  * CANNOT DO HERE - adding / editing / deleting a tree or a knowledge "
    "source, or changing task priorities. Point the user to the Trees / Sources "
    "/ Tasks pages in the app.\n"
    "- `smalltalk`: a greeting or a question about what you can do. Set `reply` "
    "to one sentence: you answer agronomy questions from their notes, mark "
    "tasks complete, and open the planner for scheduling.\n\n"
    "Never invent task ids. A request for a plan is always `schedule`; pick "
    "`agronomy` only for a knowledge question."
)


def _to_lc(messages: Sequence[Any]) -> list[BaseMessage]:
    """``ChatMessageIn``-like {role, content} -> LangChain messages (windowed)."""
    out: list[BaseMessage] = []
    for m in list(messages)[-_HISTORY_WINDOW:]:
        role = getattr(m, "role", None) or m["role"]
        content = getattr(m, "content", None) or m["content"]
        out.append(HumanMessage(content) if role == "user" else AIMessage(content))
    return out


def last_user_text(messages: Sequence[Any]) -> str:
    for m in reversed(list(messages)):
        role = getattr(m, "role", None) or m["role"]
        if role == "user":
            return (getattr(m, "content", None) or m["content"]).strip()
    return ""


@traced("orchestrator.classify")
async def classify(messages: Sequence[Any], *, settings: Settings) -> Classification:
    llm = chat_model(
        settings,
        model=settings.agent_model,
        temperature=0.0,
        timeout=30.0,
    ).with_structured_output(_ClassificationModel)

    try:
        out: _ClassificationModel = await llm.ainvoke(
            [SystemMessage(ORCHESTRATOR_SYSTEM_PROMPT), *_to_lc(messages)]
        )
    except Exception as exc:  # noqa: BLE001 - Ollama down / model missing -> 503
        _log.warning("orchestrator.classify.failed", error=str(exc)[:200])
        raise LLMUnavailable from exc

    _log.info("orchestrator.route", route=out.route, task_ids=out.task_ids)
    return {"route": out.route, "task_ids": list(out.task_ids), "reply": out.reply.strip()}
