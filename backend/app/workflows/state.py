"""问数工作流共享状态。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional

from typing_extensions import TypedDict


def add_events(prev: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return prev + new


class ChatState(TypedDict):
    # 输入
    question: str
    history: List[Dict[str, str]]

    # supervisor 产出
    intent: str                    # query | attribution | chitchat
    rewritten_question: str
    period_start: str              # YYYY-MM-DD
    period_end: str                # YYYY-MM-DD(开区间)

    # RAG 检索产出
    schema_docs: List[str]         # 表结构文档
    caliber_docs: List[str]        # 指标口径文档
    example_sqls: List[Dict[str, str]]  # {question, sql, score}

    # SQL 生成与执行
    sql: str
    sql_error: str
    repair_count: int
    columns: List[str]
    rows: List[List[Any]]
    row_count: int

    # 输出
    chart_type: str                # line | bar | pie | table
    chart_spec: Dict[str, Any]     # ECharts option
    answer_md: str
    mode: str                      # llm | fallback
    events: Annotated[List[Dict[str, Any]], add_events]
    error: str


def create_initial_state(question: str, history: List[Dict[str, str]] | None = None) -> ChatState:
    return {
        "question": question,
        "history": history or [],
        "intent": "query",
        "rewritten_question": question,
        "period_start": "",
        "period_end": "",
        "schema_docs": [],
        "caliber_docs": [],
        "example_sqls": [],
        "sql": "",
        "sql_error": "",
        "repair_count": 0,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "chart_type": "table",
        "chart_spec": {},
        "answer_md": "",
        "mode": "llm",
        "events": [],
        "error": "",
    }
