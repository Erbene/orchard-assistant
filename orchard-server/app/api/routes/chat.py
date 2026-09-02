"""Server-Sent Events chat endpoint - the Orchestrator assistant.

`POST /chat` accepts ``{conversation_id?, message}`` and streams the turn.
History is server-owned: omit ``conversation_id`` on the first turn and read
the new id from the ``conversation`` event.

    data: {"type":"start"}
    data: {"type":"conversation","id":7,"title":"why are my leaves yellow","new":true}
    data: {"type":"tool","toolName":"mark_tasks_complete","args":{...},"result":[3,5]}
    data: {"type":"text-delta","delta":"Marked "}
    data: {"type":"redirect","href":"/schedule","label":"Open the scheduler"}
    data: {"type":"finish","finishReason":"ok"}

Requires the local LLM (Ollama). If it's unreachable the endpoint returns
**503** before the stream starts.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...config import Settings
from ...dependencies import get_chat_service, get_settings_dep
from ...schemas.chat import ChatRequest
from ...services.chat_service import ChatService
from ...services.exceptions import LLMUnavailable

router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _require_ollama(settings: Settings) -> None:
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/version")
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable from exc


@router.post("")
async def chat(
    payload: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings_dep),
) -> StreamingResponse:
    await _require_ollama(settings)  # -> 503 before the stream opens

    async def event_stream() -> AsyncIterator[str]:
        yield _sse({"type": "start"})
        try:
            async for event in service.stream_reply(
                conversation_id=payload.conversation_id, message=payload.message
            ):
                yield _sse(event)
        except LLMUnavailable as exc:
            yield _sse({"type": "error", "error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - surface as a stream event, not a 500
            yield _sse({"type": "error", "error": str(exc)})
            return
        yield _sse({"type": "finish", "finishReason": "ok"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
