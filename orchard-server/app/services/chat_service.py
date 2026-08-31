"""Stub chat service.

No language model is wired up. This streams a fixed placeholder reply, token
by token, so the SSE transport / Next proxy / chat UI can be exercised end to
end. Replace :meth:`stream_reply` with a real agent loop later - the signature
(message history in, async iterator of text chunks out) is meant to stay.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence

from ..schemas.chat import ChatMessageIn

_STUB_REPLY = (
    "I'm the orchard assistant. I'm not connected to a language model yet, so "
    "this is a streamed placeholder. Once a model is wired into "
    "ChatService.stream_reply I'll be able to read your zones and trees and "
    "help manage them."
)

# Seconds between emitted chunks - just enough to see the stream progress.
_CHUNK_DELAY = 0.02


def _chunks(text: str) -> list[str]:
    """Split into word-ish chunks, keeping trailing whitespace attached so the
    client can concatenate deltas verbatim."""
    return re.findall(r"\S+\s*", text)


class ChatService:
    async def stream_reply(
        self, messages: Sequence[ChatMessageIn]
    ) -> AsyncIterator[str]:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        ).strip()

        preamble = f'You asked: "{last_user}"\n\n' if last_user else ""
        for chunk in _chunks(preamble + _STUB_REPLY):
            yield chunk
            await asyncio.sleep(_CHUNK_DELAY)
