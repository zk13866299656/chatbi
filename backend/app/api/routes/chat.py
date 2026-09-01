"""对话问数接口:普通 JSON + SSE 流式两种形态。

SSE 事件流:
    {"type":"start"} → {"type":"node",...}(每个节点的进度)→ {"type":"final",...} → [DONE]
前端据此渲染"分析过程时间线 + 最终结论/图表",显著提升长查询的等待体验。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ...models.schemas import ApiResponse, ChatRequest
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


async def _run_workflow(question: str, history: list[dict]) -> dict:
    final: dict = {}
    async for chunk in get_workflow().graph.astream(
        create_initial_state(question, history), stream_mode="updates"
    ):
        for update in chunk.values():
            final.update(update)
    return final


@router.post("/chat", response_model=ApiResponse)
async def chat(req: ChatRequest):
    """非流式接口(评测脚本与联调用)。"""
    final = await _run_workflow(req.question, req.history)
    return ApiResponse(data=_final_payload(final))


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式接口:逐节点推送进度,结束时推送完整结果。"""

    async def event_generator():
        yield _sse({"type": "start", "question": req.question})
        try:
            final: dict = {}
            async for chunk in get_workflow().graph.astream(
                create_initial_state(req.question, req.history), stream_mode="updates"
            ):
                for _node, update in chunk.items():
                    if not update:
                        continue
                    for event in update.get("events", []):
                        yield _sse({"type": "node", **event})
                    final.update(update)
            yield _sse(_final_payload(final))
        except Exception as exc:  # noqa: BLE001
            logger.exception("对话工作流异常")
            yield _sse({"type": "error", "message": f"服务内部错误: {exc}"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
