"""ChatBI 问数工作流(LangGraph 编排)。

主流程:
    supervisor ──query──→ [retrieve_schema ∥ retrieve_caliber] ──→ generate_sql ──→ validate_sql ──→ execute_sql
    │                                                                                    │(失败,限一次)
    ├─attribution──→ retrieve_caliber ──→ attribution_run                                 └─→ repair_sql ──→ validate_sql
    └─chitchat──→ small_talk                                                    成功 ──→ recommend_chart ──→ summarize ──→ END
任何失败出口 ──→ fallback_answer ──→ END
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from ..agents import nodes
from ..config import get_settings
from .state import ChatState, create_initial_state

logger = logging.getLogger(__name__)


class ChatBIWorkflow:
    def __init__(self) -> None:
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(ChatState)

        workflow.add_node("supervisor", nodes.supervisor_node)
        workflow.add_node("dispatch_query", nodes.dispatch_query_node)
        workflow.add_node("retrieve_schema", nodes.retrieve_schema_node)
        workflow.add_node("retrieve_caliber", nodes.retrieve_caliber_node)
        workflow.add_node("retrieve_caliber_attr", nodes.retrieve_caliber_attr_node)
        workflow.add_node("generate_sql", nodes.generate_sql_node)
        workflow.add_node("validate_sql", nodes.validate_sql_node)
        workflow.add_node("repair_sql", nodes.repair_sql_node)
        workflow.add_node("execute_sql", nodes.execute_sql_node)
        workflow.add_node("recommend_chart", nodes.recommend_chart_node)
        workflow.add_node("summarize", nodes.summarize_node)
        workflow.add_node("attribution_run", nodes.attribution_run_node)
        workflow.add_node("small_talk", nodes.small_talk_node)
        workflow.add_node("fallback_answer", nodes.fallback_answer_node)

        workflow.set_entry_point("supervisor")
        workflow.add_conditional_edges(
            "supervisor",
            lambda state: state.get("intent", "query"),
            {
                "query": "dispatch_query",
                "attribution": "retrieve_caliber_attr",
                "chitchat": "small_talk",
            },
        )
        # query 主链路:分发后两路检索并行,屏障汇合(barrier)再生成 SQL
        workflow.add_edge("dispatch_query", "retrieve_schema")
        workflow.add_edge("dispatch_query", "retrieve_caliber")
        workflow.add_edge(["retrieve_schema", "retrieve_caliber"], "generate_sql")
        workflow.add_edge("generate_sql", "validate_sql")

        # attribution 链路:口径检索 → 模板化归因分析
        workflow.add_edge("retrieve_caliber_attr", "attribution_run")

        # 校验失败/执行失败 → 有限次修复 → 否则兜底
        workflow.add_conditional_edges(
            "validate_sql",
            self._route_sql_pipeline,
            {"execute": "execute_sql", "repair": "repair_sql", "fallback": "fallback_answer"},
        )
        workflow.add_conditional_edges(
            "execute_sql",
            self._route_sql_pipeline,
            {"execute": "recommend_chart", "repair": "repair_sql", "fallback": "fallback_answer"},
        )
        workflow.add_edge("repair_sql", "validate_sql")

        workflow.add_edge("recommend_chart", "summarize")
        workflow.add_edge("summarize", END)

        workflow.add_edge("attribution_run", END)
        workflow.add_edge("small_talk", END)
        workflow.add_edge("fallback_answer", END)

        return workflow.compile()

    def _route_sql_pipeline(self, state: Dict[str, Any]) -> str:
        if state.get("sql_error") or state.get("error"):
            if state.get("repair_count", 0) < 1 and get_settings().llm_enabled and not state.get("error"):
                return "repair"
            return "fallback"
        return "execute"

    async def run(self, question: str, history: list[dict] | None = None) -> Dict[str, Any]:
        final: Dict[str, Any] = {}
        async for chunk in self.graph.astream(create_initial_state(question, history), stream_mode="updates"):
            for update in chunk.values():
                if update:  # 无状态变更的节点在 updates 流中为 None
                    final.update(update)
        return final


_workflow: Optional[ChatBIWorkflow] = None


def get_workflow() -> ChatBIWorkflow:
    global _workflow
    if _workflow is None:
        _workflow = ChatBIWorkflow()
    return _workflow
