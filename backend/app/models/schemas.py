"""API 层的 Pydantic 模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="用户问题")
    history: List[Dict[str, str]] = Field(default_factory=list, description="最近对话历史")


class ChatFinalData(BaseModel):
    question: str
    intent: str = "query"
    answer_md: str = ""
    sql: str = ""
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    chart_type: str = "table"
    chart_spec: Dict[str, Any] = Field(default_factory=dict)
    mode: str = "llm"
    period: List[Optional[str]] = Field(default_factory=list)

    class Config:
        extra = "allow"


class ApiResponse(BaseModel):
    success: bool = True
    message: str = ""
    data: Any = None
