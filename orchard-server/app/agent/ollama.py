"""Startup diagnostics for the local Ollama models.

Logs which of the configured models (`AGENT_MODEL`, `AGRONOMIST_MODEL`,
`FOREMAN_MODEL`) are actually pulled, so a missing model shows up once at boot
instead of only as a 404 mid-request. Never raises - purely informational.
"""
from __future__ import annotations

import httpx

from ..config import Settings
from ..core.logging import get_logger

_log = get_logger("app.ollama")


async def report_model_availability(settings: Settings) -> None:
    wanted = {
        "AGENT_MODEL": settings.agent_model,
        "AGRONOMIST_MODEL": settings.agronomist_model,
        "FOREMAN_MODEL": settings.foreman_model,
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
        _log.info("ollama.models.ready", models=sorted(set(wanted.values())))
