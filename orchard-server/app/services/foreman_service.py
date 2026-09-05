"""Drives the Foreman LangGraph negotiation for the REST layer.

Seeds the graph with the pending-task backlog, starts / resumes a
checkpointed session by ``thread_id``, and maps the paused-or-finished graph
state onto a flat :class:`ScheduleState` DTO. Never mutates the DB itself -
completions go through ``mark_many_complete`` (explicit user action only).
"""
from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Sequence
from typing import Any

from langgraph.types import Command

from ..agent.foreman import _minutes
from ..schemas.schedule import (
    ScheduleEscalation,
    ScheduleState,
    ScheduleStep,
    ScheduleTask,
)
from ..schemas.task import TaskRead
from .task_service import TaskService

_COMPLETION_HINT = re.compile(r"\b(done|finish|complet|did|mark|wrapped)\w*", re.I)


class ForemanService:
    def __init__(self, tasks: TaskService, graph: Any) -> None:
        self._tasks = tasks
        self._graph = graph

    # -- the negotiation loop -----------------------------------------

    async def start(self, available_minutes: int | None) -> ScheduleState:
        thread_id = f"jit-{uuid.uuid4().hex[:12]}"
        pending = [t.model_dump(mode="json") for t in await self._tasks.get_pending_queue()]
        completions = await self._tasks.recent_completions_for_scheduling()
        result = await asyncio.to_thread(
            self._graph.invoke,
            {
                "pending_tasks": pending,
                "recent_completions": completions,
                "available_minutes": available_minutes,
            },
            self._cfg(thread_id),
        )
        return self._to_state(thread_id, result)

    async def resume(self, thread_id: str, value: Any) -> ScheduleState:
        result = await asyncio.to_thread(
            self._graph.invoke, Command(resume=value), self._cfg(thread_id)
        )
        return self._to_state(thread_id, result)

    # -- explicit completion (UI button or natural language) ---------

    async def complete(self, task_ids: Sequence[int]) -> list[TaskRead]:
        return await self._tasks.mark_many_complete(task_ids)

    async def report(self, text: str) -> tuple[list[int], str]:
        ids = self._extract_ids(text)
        if not ids:
            return [], "Couldn't find any task numbers in that. Try 'finished task 3 and 5'."
        marked = await self._tasks.mark_many_complete(ids)
        done = [t.id for t in marked]
        missed = sorted(set(ids) - set(done))
        note = f"Marked {done} complete." + (f" Unknown: {missed}." if missed else "")
        return done, note

    @staticmethod
    def _extract_ids(text: str) -> list[int]:
        if _COMPLETION_HINT.search(text):
            return sorted({int(n) for n in re.findall(r"\d+", text)})
        return sorted({int(n) for n in re.findall(r"(?:task|#)\s*#?\s*(\d+)", text, re.I)})

    # -- graph <-> DTO ----------------------------------------------

    @staticmethod
    def _cfg(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _to_state(self, thread_id: str, result: dict) -> ScheduleState:
        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = interrupts[0].value
            if payload.get("ask") == "available_minutes":
                return ScheduleState(thread_id=thread_id, step="need_time")
            return ScheduleState(
                thread_id=thread_id,
                step="need_resources",
                available_minutes=result.get("available_minutes"),
                required_resources=list(payload.get("resources", [])),
            )

        step: ScheduleStep = "done"
        escalated_ids = {e["task_id"] for e in result.get("escalations", [])}
        return ScheduleState(
            thread_id=thread_id,
            step=step,
            available_minutes=result.get("available_minutes"),
            required_resources=result.get("required_resources", []),
            proposed_tasks=[
                self._task(t, escalated_ids) for t in result.get("proposed_tasks", [])
            ],
            dropped_tasks=[
                self._task(t, escalated_ids) for t in result.get("dropped_tasks", [])
            ],
            escalations=[ScheduleEscalation(**e) for e in result.get("escalations", [])],
            summary=result.get("summary"),
            warnings=result.get("warnings", []),
        )

    @staticmethod
    def _task(t: dict, escalated_ids: set[int]) -> ScheduleTask:
        return ScheduleTask(
            id=t["id"],
            tree_id=t["tree_id"],
            action_type=t["action_type"],
            estimated_minutes=t.get("estimated_minutes") or _minutes(t),
            priority_score=float(t.get("priority_score") or 0.0),
            effective_score=t.get("_effective_score"),
            required_resources=list(t.get("required_resources") or []),
            escalated=t["id"] in escalated_ids,
            drop_reason=t.get("_drop_reason"),
            tree_species=t.get("tree_species"),
            tree_variety=t.get("tree_variety"),
            template_category=t.get("template_category"),
            last_completed=t.get("last_completed"),
        )
