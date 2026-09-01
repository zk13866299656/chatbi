"""元信息接口:语义层(表结构/指标口径/示例)与系统状态。"""

from __future__ import annotations

from fastapi import APIRouter

from ...config import get_settings
from ...db import store
from ...db.database import health_check
from ...db.schema_docs import get_examples, get_metrics, get_tables
from ...models.schemas import ApiResponse

router = APIRouter(tags=["meta"])


@router.get("/meta/semantic-layer", response_model=ApiResponse)
async def semantic_layer():
    """语义层元数据,前端"数据字典/口径"页直接渲染。"""
    return ApiResponse(data={
        "tables": [
            {"name": t["table"], "meaning": t["meaning"],
             "fields": [{"name": k, "comment": v} for k, v in t["fields"].items()]}
            for t in get_tables()
        ],
        "metrics": get_metrics(),
        "examples": [{"question": e["question"]} for e in get_examples()],
    })


@router.get("/health", response_model=ApiResponse)
async def health():
    settings = get_settings()
    db_ok = health_check()
    return ApiResponse(data={
        "status": "ok" if db_ok else "db_error",
        "db": db_ok,
        "llm_enabled": settings.llm_enabled,
        "mode": "llm" if settings.llm_enabled else "fallback",
        "app": settings.app_name,
    })
