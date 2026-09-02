"""HTTP surface for persisted assistant conversations.

    GET    /conversations          -> list (most recently updated first)
    GET    /conversations/{id}     -> the thread with all messages
    PATCH  /conversations/{id}     -> rename
    DELETE /conversations/{id}     -> 204

Conversations are created implicitly by ``POST /chat`` (the new id comes back
in the stream's ``conversation`` event).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...dependencies import get_conversation_service
from ...schemas.conversation import (
    ConversationDetail,
    ConversationRead,
    ConversationRename,
)
from ...services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationRead])
async def list_conversations(
    svc: ConversationService = Depends(get_conversation_service),
):
    return await svc.list()


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    svc: ConversationService = Depends(get_conversation_service),
):
    return await svc.detail(conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def rename_conversation(
    conversation_id: int,
    payload: ConversationRename,
    svc: ConversationService = Depends(get_conversation_service),
):
    return await svc.rename(conversation_id, payload.title)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int,
    svc: ConversationService = Depends(get_conversation_service),
):
    await svc.delete(conversation_id)
