"""Server-Sent Events chat endpoint.

`POST /chat` accepts a message history and streams the assistant reply as SSE
frames:

    data: {"type":"start"}

    data: {"type":"text-delta","delta":"Hello "}

    data: {"type":"finish","finishReason":"stub"}

The reply is a stub (see ChatService) - no model is called.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...dependencies import get_chat_service
from ...schemas.chat import ChatRequest
from ...services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


@router.post("")
async def chat(
    payload: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        yield _sse({"type": "start"})
        try:
            async for delta in service.stream_reply(payload.messages):
                yield _sse({"type": "text-delta", "delta": delta})
        except Exception as exc:  # noqa: BLE001 - surface as a stream event, not a 500
            yield _sse({"type": "error", "error": str(exc)})
            return
        yield _sse({"type": "finish", "finishReason": "stub"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )
