"""Shared Ollama client construction and startup diagnostics.

Every application and evaluation call uses :func:`chat_model` so model
placement options are applied consistently. Startup diagnostics log which
configured role models are pulled; they never raise.
"""
from __future__ import annotations

from typing import Any

import httpx
from langchain_ollama import ChatOllama

from ..config import Settings
from ..core.logging import get_logger

_log = get_logger("app.ollama")


def chat_model(
    settings: Settings,
    *,
    model: str,
    temperature: float,
    timeout: float,
    num_predict: int | None = None,
) -> ChatOllama:
    """Build a ChatOllama client with the configured execution profile."""
    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": settings.ollama_base_url,
        "temperature": temperature,
        "client_kwargs": {"timeout": timeout},
    }
    if settings.ollama_num_gpu is not None:
        kwargs["num_gpu"] = settings.ollama_num_gpu
    if settings.ollama_num_thread is not None:
        kwargs["num_thread"] = settings.ollama_num_thread
    if settings.ollama_keep_alive is not None:
        kwargs["keep_alive"] = settings.ollama_keep_alive
    if num_predict is not None:
        kwargs["num_predict"] = num_predict
    return ChatOllama(**kwargs)


async def report_model_availability(settings: Settings) -> None:
    wanted = {
        "AGENT_MODEL": settings.agent_model,
        "AGRONOMIST_MODEL": settings.agronomist_model,
        "FOREMAN_MODEL": settings.foreman_model,
        "CARE_PLAN_MODEL": settings.care_plan_model,
        "IRRIGATION_MODEL": settings.irrigation_model,
        "JUDGE_MODEL": settings.judge_model,
        "GROUNDING_MODEL": settings.grounding_model,
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            present = {m.get("name", "") for m in resp.json().get("models", [])}
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        _log.warning(
            "ollama.unreachable",
            base_url=settings.ollama_base_url,
            error=str(exc)[:160],
        )
        return

    def _has(name: str) -> bool:
        return name in present or f"{name}:latest" in present

    missing = {env: model for env, model in wanted.items() if not _has(model)}
    if missing:
        _log.warning("ollama.models.missing", missing=missing, hint="ollama pull <model>")
    else:
        _log.info(
            "ollama.models.ready",
            models=sorted(set(wanted.values())),
            num_gpu=settings.ollama_num_gpu,
            num_thread=settings.ollama_num_thread,
        )
