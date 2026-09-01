"""会话管理接口:列表 / 历史消息 / 删除。会话在首条消息发送时懒创建。"""

from __future__ import annotations

from fastapi import APIRouter

from ...db import store
from ...models.schemas import ApiResponse

router = APIRouter(tags=["conversations"])


@router.get("/conversations", response_model=ApiResponse)
async def list_conversations():
    return ApiResponse(data=store.list_conversations())


@router.get("/conversations/{conversation_id}/messages", response_model=ApiResponse)
async def get_messages(conversation_id: str):
    return ApiResponse(data=store.get_messages(conversation_id))


@router.delete("/conversations/{conversation_id}", response_model=ApiResponse)
async def delete_conversation(conversation_id: str):
    store.delete_conversation(conversation_id)
    return ApiResponse(message="已删除")
