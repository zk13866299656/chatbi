"""会话管理接口:列表 / 历史消息 / 删除。会话在首条消息发送时懒创建。

注意:所有 store 调用都走 asyncio.to_thread——FastAPI 单事件循环,
同步 DB 调用一旦碰上锁等待(busy_timeout 最长 5 秒)会阻塞全部请求,
表现就是"整个页面时不时卡死"。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from ...db import store
from ...models.schemas import ApiResponse

router = APIRouter(tags=["conversations"])


@router.get("/conversations", response_model=ApiResponse)
async def list_conversations():
    return ApiResponse(data=await asyncio.to_thread(store.list_conversations))


@router.get("/conversations/{conversation_id}/messages", response_model=ApiResponse)
async def get_messages(conversation_id: str):
    return ApiResponse(data=await asyncio.to_thread(store.get_messages, conversation_id))


@router.delete("/conversations/{conversation_id}", response_model=ApiResponse)
async def delete_conversation(conversation_id: str):
    await asyncio.to_thread(store.delete_conversation, conversation_id)
    return ApiResponse(message="已删除")
