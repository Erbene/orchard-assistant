"""LLM-as-judge for the fuzzy criteria (``rubric``). Advisory - a local model
scoring another local model's text is noisy, so treat a judge failure as a
signal to eyeball the transcript, not a hard gate on its own.
"""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from app.config import Settings

_SYSTEM = (
    "You are a QA grader for an orchard assistant. You are given ONE "
    "criterion, the user's message, and the assistant's reply. Ask yourself "
    "exactly one question: does the reply satisfy this criterion? Nothing "
    "else is in scope.\n\n"
    "The reply may contain correct information the criterion doesn't "
    "mention - extra numbers, extra context, extra explanation. That is NOT "
    "a reason to fail it. Do not penalise the reply for its tone, length, "
    "style, or for content the criterion is silent about; grade only "
    "whether what the criterion asks for is actually present and correct. "
    "A reply that satisfies the criterion passes even if it also says more.\n\n"
    "A reply still fails if it does not actually satisfy the criterion - "
    "e.g. it omits, contradicts, or only vaguely gestures at what the "
    "criterion requires. Answer 'pass' or 'fail' with one short sentence of "
    "reasoning."
)


class JudgeVerdict(BaseModel):
    verdict: Literal["pass", "fail"]
    reason: str = ""


def _client(settings: Settings):
    return ChatOllama(
        model=settings.agent_model,
        base_url=settings.ollama_base_url,
        temperature=0.0,
        client_kwargs={"timeout": 60.0},
    ).with_structured_output(JudgeVerdict)


async def judge(
    settings: Settings, *, criterion: str, user_message: str, reply: str
) -> JudgeVerdict:
    llm = _client(settings)
    prompt = (
        f"Criterion: {criterion}\n\n"
        f"User message:\n{user_message}\n\n"
        f"Assistant reply:\n{reply}"
    )
    try:
        out = await llm.ainvoke([SystemMessage(_SYSTEM), HumanMessage(prompt)])
    except Exception as exc:  # noqa: BLE001
        return JudgeVerdict(verdict="fail", reason=f"judge error: {str(exc)[:120]}")
    return out
