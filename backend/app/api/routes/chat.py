"""对话问数接口:普通 JSON + SSE 流式两种形态。

SSE 事件流:
    {"type":"start"} → {"type":"node",...}(每个节点的进度)→ {"type":"final",...} → [DONE]
前端据此渲染"分析过程时间线 + 最终结论/图表",显著提升长查询的等待体验。
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ...models.schemas import ApiResponse, ChatRequest
from ...db import store
from ...workflows.graph import get_workflow
from ...workflows.state import create_initial_state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _final_payload(state: dict) -> dict:
    return {
        "type": "final",
        "question": state.get("question", ""),
        "intent": state.get("intent", "query"),
        "answer_md": state.get("answer_md", ""),
        "sql": state.get("sql", ""),
        "columns": state.get("columns", []),
        "rows": state.get("rows", []),
        "row_count": state.get("row_count", 0),
        "chart_type": state.get("chart_type", "table"),
        "chart_spec": state.get("chart_spec", {}),
        "mode": state.get("mode", "llm"),
        "period": [state.get("period_start") or None, state.get("period_end") or None],
    }


def _ensure_conversation(req: ChatRequest) -> str:
    """取现有会话 ID 或懒创建新会话(标题取首问截断)。"""
    if req.conversation_id:
        return req.conversation_id
    return store.create_conversation(title=req.question)["id"]


def _persist_final(conversation_id: str, question: str, final: dict) -> None:
    """工作流结束后,把 assistant 最终结果(含图表/SQL/节点事件)落库。

    字段统一补默认值:历史上曾因闲聊/兜底消息缺 rows 等字段,
    前端渲染历史时抛异常导致整个应用假死。
    """
    payload = {
        "question": question,
        "intent": final.get("intent") or "query",
        "answer_md": final.get("answer_md") or "",
        "sql": final.get("sql") or "",
        "columns": final.get("columns") or [],
        "rows": final.get("rows") or [],
        "row_count": final.get("row_count") or 0,
        "chart_type": final.get("chart_type") or "table",
        "chart_spec": final.get("chart_spec") or {},
        "mode": final.get("mode") or "fallback",
        "period": [final.get("period_start") or None, final.get("period_end") or None],
        "events": final.get("events") or [],
    }
    store.append_messages(conversation_id, [
        ("assistant", payload["answer_md"], payload),
    ])


async def _run_workflow(question: str, history: list[dict]) -> dict:
    final: dict = {}
    all_events: list = []
    async for chunk in get_workflow().graph.astream(
        create_initial_state(question, history), stream_mode="updates"
    ):
        for update in chunk.values():
            if not update:
                continue
            all_events.extend(update.get("events", []))
            final.update(update)
    final["events"] = all_events
    return final


@router.post("/chat", response_model=ApiResponse)
async def chat(req: ChatRequest):
    """非流式接口(评测脚本与联调用)。"""
    conversation_id = await asyncio.to_thread(_ensure_conversation, req)
    await asyncio.to_thread(store.append_messages, conversation_id, [("user", req.question, None)])
    final = await _run_workflow(req.question, req.history)
    await asyncio.to_thread(_persist_final, conversation_id, req.question, final)
    data = _final_payload(final)
    data["conversation_id"] = conversation_id
    return ApiResponse(data=data)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式接口:逐节点推送进度,结束时推送完整结果。

    会话在首条消息时懒创建;用户消息在工作流启动前先落库,
    即使请求中断,提问记录也不丢失。
    """
    conversation_id = await asyncio.to_thread(_ensure_conversation, req)
    await asyncio.to_thread(store.append_messages, conversation_id, [("user", req.question, None)])

    async def event_generator():
        yield _sse({"type": "start", "question": req.question, "conversation_id": conversation_id})
        try:
            final: dict = {}
            all_events: list = []
            async for chunk in get_workflow().graph.astream(
                create_initial_state(req.question, req.history), stream_mode="updates"
            ):
                for _node, update in chunk.items():
                    if not update:
                        continue
                    for event in update.get("events", []):
                        all_events.append(event)
                        yield _sse({"type": "node", **event})
                    final.update(update)
            final["events"] = all_events
            await asyncio.to_thread(_persist_final, conversation_id, req.question, final)
            data = _final_payload(final)
            data["conversation_id"] = conversation_id
            yield _sse(data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("对话工作流异常")
            yield _sse({"type": "error", "message": f"服务内部错误: {exc}"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
