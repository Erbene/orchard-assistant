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
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from ..config import Settings
from ..core.logging import get_logger
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
    "- `schedule`: the user wants a work plan / to organize their day / to fit "
    "tasks into available time. Set `reply` to one short sentence telling them "
    "you'll open the planner. Do NOT try to build a schedule here.\n"
    "- `complete`: the user states that specific task(s) are done / finished / "
    "handled (e.g. 'done with task 3 and 5', 'I wrapped up the mulching (task "
    "12)'). Put every referenced task id in `task_ids`. Set `reply` to a short "
    "acknowledgement. If the message clearly reports completion but names no id, "
    "still use `complete` with an empty `task_ids` and ask which tasks in `reply`.\n"
    "- `refuse`: the request is unsafe or out of scope. Set `reply` to a brief, "
    "polite refusal. UNSAFE = anything that would harm people, crops, or the "
    "environment: exceeding a pesticide label rate, mixing incompatible / toxic "
    "chemicals (e.g. bleach + ammonia), applying pesticides where people or "
    "children are, or permanently hiding a safety-critical overdue task. For "
    "unsafe agronomy asks, briefly say why and offer a safe alternative. OUT OF "
    "SCOPE = anything not about this orchard's trees, tasks, or ingested "
    "knowledge (weather, travel, errands, general chit-chat unrelated to the "
    "orchard, coding).\n"
    "- `smalltalk`: a greeting or a question about what you can do. Set `reply` "
    "to one sentence: you answer agronomy questions from their notes, mark "
    "tasks complete, and open the planner for scheduling.\n\n"
    "Never invent task ids. When unsure between `agronomy` and `schedule`, pick "
    "`agronomy` only if it is a knowledge question; a request for a plan is "
    "always `schedule`."
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


async def classify(messages: Sequence[Any], *, settings: Settings) -> Classification:
    llm = ChatOllama(
        model=settings.agent_model,
        base_url=settings.ollama_base_url,
        temperature=0.0,
        client_kwargs={"timeout": 30.0},
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
