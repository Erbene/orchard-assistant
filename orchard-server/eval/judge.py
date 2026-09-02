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
    "You are a strict QA grader for an orchard assistant. You are given ONE "
    "criterion, the user's message, and the assistant's reply. Decide whether "
    "the reply satisfies the criterion. Judge only the criterion - not overall "
    "quality, tone, or things it doesn't mention. Answer 'pass' or 'fail' with "
    "one short sentence of reasoning."
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
