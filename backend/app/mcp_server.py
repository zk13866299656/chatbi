"""ChatBI MCP Server:把问数能力按 MCP 协议暴露给外部 Agent。

设计原则:
1. 复用而非重写——4 个工具直接调用现有的 LangGraph 工作流 / SQL 安全执行器 / 语义层;
2. 能力放出去,风险关在里面——外部 Agent 拿不到数据库连接,只能过安全闸门;
3. 工具描述即 Prompt——描述里写清楚适用范围,外部 Agent 的 LLM 才能正确决定何时调用。

传输:默认 stdio(Cursor / Claude Desktop 标准接入方式);MCP_TRANSPORT=http 切换流式 HTTP。
启动:python -m app.mcp_server
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import get_settings
from .db.schema_docs import get_examples, get_metrics, get_tables
from .services.sql_executor import check_sql_safety, execute_sql
from .workflows.graph import get_workflow

mcp = FastMCP("chatbi")


def _json_safe(rows: list[list[Any]]) -> list[list[Any]]:
    return [[float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v) for v in row] for row in rows]


def _pack(final: dict) -> dict:
    return {
        "answer": final.get("answer_md", ""),
        "sql": final.get("sql", ""),
        "columns": final.get("columns", []),
        "rows": _json_safe(final.get("rows", []))[:100],
        "row_count": final.get("row_count", 0),
        "chart_type": final.get("chart_type", "table"),
        "mode": final.get("mode", ""),
        "period": [final.get("period_start") or None, final.get("period_end") or None],
    }


@mcp.tool()
async def ask_data(question: str) -> str:
    """对电商经营数据做自然语言问数:返回分析结论、生成的 SQL、查询结果数据与图表建议。

    适用范围(本数据集覆盖的主题):销售额/GMV、订单量、客单价、退款率与退款原因、
    商品销量、店铺、客户与会员等级、支付方式、评价评分。
    支持"上个月/最近N天/具体月份"等时间表达;支持"为什么涨/跌"类归因问题。
    问题请使用中文或英文,一次一个问题。不适用于:写入/修改数据、数据集之外的业务。
    """
    final = await get_workflow().run(question.strip())
    return json.dumps(_pack(final), ensure_ascii=False, default=str)


@mcp.tool()
async def execute_validated_sql(sql: str) -> str:
    """在 ChatBI 数仓上执行一条只读 SELECT 语句并返回结果。

    内置安全闸门:仅允许单条 SELECT、表名白名单、DDL/DML 黑名单、强制行数上限(200)。
    表结构请先调用 list_semantic_layer 获取;时间过滤建议用日期区间。
    传入非查询语句会被直接拒绝。
    """
    checked, error = check_sql_safety(sql)
    if error:
        return json.dumps({"error": error}, ensure_ascii=False)
    columns, rows, elapsed_ms = await execute_sql(checked)
    return json.dumps(
        {"columns": columns, "rows": _json_safe(rows), "row_count": len(rows), "elapsed_ms": elapsed_ms},
        ensure_ascii=False, default=str,
    )


@mcp.tool()
def list_semantic_layer() -> str:
    """列出当前数仓的语义层:所有数据表及其字段含义、表间关联关系。

    写 SQL 之前应先调用本工具了解可用的表与字段,以及业务含义与关联方式。
    """
    tables = [
        {"table": t["table"], "meaning": t["meaning"],
         "fields": {k: v for k, v in t["fields"].items()}}
        for t in get_tables()
    ]
    return json.dumps({"tables": tables}, ensure_ascii=False)


@mcp.tool()
def get_metric_definition(metric: str) -> str:
    """查询某个经营指标的精确计算口径,确保统计数字口径一致。

    可用指标包括:GMV(支付口径销售额)、支付订单数、客单价、退款率、复购率、平均评分等。
    参数 metric 传指标名称或其关键词(如 "退款率"、"GMV")。
    """
    keyword = metric.strip().lower()
    hits = [m for m in get_metrics() if keyword in m["metric"].lower() or any(
        token and token in m["metric"].lower() for token in keyword.split())]
    if not hits:
        available = "、".join(m["metric"] for m in get_metrics())
        return json.dumps({"error": f"未找到指标「{metric}」", "available": available}, ensure_ascii=False)
    return json.dumps({"definitions": hits}, ensure_ascii=False)


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport == "http":
        mcp.run(transport="streamable-http")
    else:
        # stdio 模式:由 MCP 客户端(Cursor/Claude Desktop/Inspector)拉起本进程
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
