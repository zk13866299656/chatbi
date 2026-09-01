"""问数工作流节点实现。

设计原则(与整个平台一致):
1. LLM 只做语言层的事:意图解析、问题改写、SQL 生成、结论撰写;
2. 数字必须真实:SQL 由安全校验后对库执行,图表与结论都基于真实查询结果;
3. 每个节点都有降级路径:LLM 不可用 / 调用失败时,系统仍能给出可解释的结果。
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from ..config import get_settings
from ..db.database import engine
from ..llm.client import chat_json, chat_text
from ..rag.retriever import get_retriever
from ..services.sql_executor import check_sql_safety, execute_sql
from .prompts import SQL_GENERATE_SYSTEM, SQL_REPAIR_SYSTEM, SUMMARIZE_SYSTEM, SUPERVISOR_SYSTEM

logger = logging.getLogger(__name__)

REGION_NAMES = ["华东", "华北", "华南", "华中", "西南", "东北", "西北"]
GREETINGS = {"你好", "您好", "hi", "hello", "在吗", "你是谁", "你能做什么", "哈喽", "嗨"}
_MONTH_RE = re.compile(r"(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月")
_DAYS_RE = re.compile(r"最近\s*(\d+)\s*天|近\s*(\d+)\s*天")
_DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

_data_end_cache: str | None = None


def _emit(node: str, message: str, **extra: Any) -> dict[str, Any]:
    event = {"node": node, "message": message}
    event.update(extra)
    return event


def _data_end() -> str:
    """数据集最大日期(缓存),供 prompt 与默认时间窗使用。"""
    global _data_end_cache
    if _data_end_cache is None:
        try:
            with engine.connect() as conn:
                value = conn.execute(text("SELECT MAX(order_date) FROM fact_orders")).scalar()
            _data_end_cache = str(value)[:10] if value else date.today().isoformat()
        except Exception:
            _data_end_cache = date.today().isoformat()
    return _data_end_cache


def _clamp_end(end: date) -> date:
    """统计窗口不能超过数据集范围,避免演示时查到空数据。"""
    data_end = date.fromisoformat(_data_end())
    return min(end, data_end + timedelta(days=1))


def parse_period_fallback(question: str) -> tuple[str, str]:
    """规则解析时间窗(LLM 不可用时的兜底),返回 (start, end开区间)。"""
    today = date.today()

    if "上个月" in question or "上月" in question:
        first_of_month = today.replace(day=1)
        start = first_of_month - timedelta(days=1)
        start = start.replace(day=1)
        end = _clamp_end(first_of_month)
        return start.isoformat(), end.isoformat()

    if "本月" in question:
        start = today.replace(day=1)
        return start.isoformat(), _clamp_end(today + timedelta(days=1)).isoformat()

    days_match = _DAYS_RE.search(question)
    if days_match:
        days = int(days_match.group(1) or days_match.group(2) or 30)
        return (today - timedelta(days=days - 1)).isoformat(), _clamp_end(today + timedelta(days=1)).isoformat()

    month_match = _MONTH_RE.search(question)
    if month_match:
        year = int(month_match.group(1)) if month_match.group(1) else today.year
        month = int(month_match.group(2))
        if not month_match.group(1) and month > today.month:
            year -= 1
        start = date(year, month, 1)
        end = date(year + (month == 12), (month % 12) + 1, 1)
        return start.isoformat(), _clamp_end(end).isoformat()

    range_match = _DATE_RANGE_RE.findall(question)
    if len(range_match) >= 2:
        return range_match[0], _clamp_end(date.fromisoformat(range_match[1]) + timedelta(days=1)).isoformat()

    end = _clamp_end(today + timedelta(days=1))
    return (end - timedelta(days=30)).isoformat(), end.isoformat()


def _detect_region(question: str) -> str:
    for region in REGION_NAMES:
        if region in question:
            return region
    return "华东"


def _is_chitchat(question: str) -> bool:
    normalized = question.strip().lower().rstrip("。?!?! ")
    return normalized in GREETINGS or (len(normalized) <= 8 and "你好" in normalized)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_period(start: str, end: str) -> bool:
    return bool(_DATE_RE.match(start or "") and _DATE_RE.match(end or ""))


# ============ 意图解析 ============

async def supervisor_node(state: dict) -> dict:
    question = state["question"]
    settings = get_settings()
    started_events = [_emit("supervisor", "收到问题,开始意图解析")]

    if settings.llm_enabled:
        try:
            system_prompt = SUPERVISOR_SYSTEM.format(today=date.today().isoformat(), data_end=_data_end())
            user_payload = {
                "question": question,
                "recent_history": state.get("history", [])[-2:],
            }
            import json as _json
            data = await chat_json(system_prompt, _json.dumps(user_payload, ensure_ascii=False), max_tokens=300)
            intent = data.get("intent", "query")
            if intent not in ("query", "attribution", "chitchat"):
                intent = "query"
            period_start = data.get("period_start") or ""
            period_end = data.get("period_end") or ""
            # LLM 漏给/给错时间窗时回退规则解析,否则占位符会被替换成空串导致口径放大
            if not _valid_period(period_start, period_end):
                period_start, period_end = parse_period_fallback(question)
            return {
                "intent": intent,
                "rewritten_question": (data.get("rewritten_question") or question).strip(),
                "period_start": period_start,
                "period_end": period_end,
                "mode": "llm",
                "events": started_events + [_emit("supervisor", f"意图识别: {intent}")],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("supervisor LLM 解析失败,降级为规则解析: %s", exc)

    if _is_chitchat(question):
        intent = "chitchat"
    elif any(token in question for token in ("为什么", "为啥", "原因", "归因", "涨", "跌", "下降", "上升")):
        intent = "attribution"
    else:
        intent = "query"
    start, end = parse_period_fallback(question)
    return {
        "intent": intent,
        "rewritten_question": question,
        "period_start": start,
        "period_end": end,
        "mode": "fallback",
        "events": started_events + [_emit("supervisor", f"意图识别: {intent}(规则模式)")],
    }


# ============ RAG 检索(两路并行) ============

def retrieve_schema_node(state: dict) -> dict:
    if state.get("error"):
        return {}
    retriever = get_retriever()
    docs = retriever.search(state["rewritten_question"], kind="table", top_k=4)
    return {
        "schema_docs": [doc.text for doc in docs],
        "events": [_emit("retrieve_schema", f"检索到 {len(docs)} 份表结构文档")],
    }


def retrieve_caliber_node(state: dict) -> dict:
    if state.get("error"):
        return {}
    caliber_docs, example_sqls, events = _retrieve_caliber_data(state["rewritten_question"])
    return {"caliber_docs": caliber_docs, "example_sqls": example_sqls, "events": events}


def _retrieve_caliber_data(question: str) -> tuple[list[str], list[dict], list[dict]]:
    retriever = get_retriever()
    metrics = retriever.search(question, kind="metric", top_k=3)
    examples = retriever.search_with_scores(question, kind="example", top_k=3)
    events = [_emit("retrieve_caliber", f"检索到 {len(metrics)} 条指标口径、{len(examples)} 个参考示例")]
    return (
        [doc.text for doc in metrics],
        [{"question": doc.title, "sql": doc.sql, "score": round(score, 4)} for doc, score in examples if doc.sql],
        events,
    )


def retrieve_caliber_attr_node(state: dict) -> dict:
    """归因路径专用的口径检索(与 query 路径共享检索逻辑,避免与 SQL 链路的屏障汇合串路)。"""
    if state.get("error"):
        return {}
    caliber_docs, _examples, events = _retrieve_caliber_data(state["rewritten_question"])
    return {"caliber_docs": caliber_docs, "events": events}


def dispatch_query_node(state: dict) -> dict:
    """query 路径分发节点:之后扇出到 表结构检索 ∥ 口径检索 两个并行分支。"""
    return {"events": [_emit("dispatch_query", "进入查数链路,并行检索表结构与指标口径")]}


# ============ SQL 生成 / 校验 / 修复 ============

def _finalize_sql(sql: str, state: dict) -> str:
    region = _detect_region(state["rewritten_question"])
    return (
        sql.replace("__PSTART__", state.get("period_start") or "")
        .replace("__PEND__", state.get("period_end") or "")
        .replace("{REGION}", region)
        .strip().rstrip(";").strip()
    )


def _extract_sql(raw: str) -> str:
    fence = re.search(r"```(?:sql)?\s*(.*?)```", raw or "", re.IGNORECASE | re.DOTALL)
    text = fence.group(1).strip() if fence else (raw or "").strip()
    for line in text.splitlines():
        stripped = line.strip().rstrip(";")
        if re.match(r"(?i)^(SELECT|WITH)\b", stripped):
            return stripped
    return text.strip().rstrip(";")


async def generate_sql_node(state: dict) -> dict:
    if state.get("error"):
        return {}
    settings = get_settings()
    events: list[dict] = []

    # 域外拒答:最高示例相似度低于阈值,说明问题大概率超出语义层覆盖范围。
    # 无论 LLM 是否可用都拒绝作答——宁可说"不会",不给自信的错答案,还省一次 LLM 调用。
    all_examples = sorted(state.get("example_sqls", []), key=lambda item: item["score"], reverse=True)
    best_score = all_examples[0]["score"] if all_examples else 0.0
    if best_score < settings.example_abstain_threshold:
        return {
            "error": "out_of_domain",
            "events": [_emit("generate_sql", f"问题超出语义层覆盖范围(最高相似度 {best_score:.2f}),拒绝作答")],
        }

    if settings.llm_enabled:
        try:
            context_parts = [
                "【表结构】\n" + "\n\n".join(state.get("schema_docs", [])),
                "【指标口径】\n" + "\n".join(state.get("caliber_docs", [])),
            ]
            examples = state.get("example_sqls", [])
            if examples:
                example_text = "\n\n".join(
                    f"示例问题: {item['question']}\n参考SQL:\n{item['sql']}" for item in examples
                )
                context_parts.append("【类似问题的参考SQL】\n" + example_text)
            context_parts.append(
                f"【时间窗】start={state.get('period_start')} end={state.get('period_end')}(end 为开区间)"
            )
            context_parts.append(f"【用户问题】{state['rewritten_question']}")
            sql = _extract_sql(await chat_text(SQL_GENERATE_SYSTEM, "\n\n".join(context_parts)))
            sql = _finalize_sql(sql, state)
            events.append(_emit("generate_sql", "LLM 已生成 SQL", mode="llm"))
            return {"sql": sql, "mode": "llm", "events": events}
        except Exception as exc:  # noqa: BLE001
            logger.warning("SQL 生成失败,降级为示例匹配: %s", exc)
            events.append(_emit("generate_sql", "LLM 生成失败,启用示例匹配兜底"))

    examples = sorted(state.get("example_sqls", []), key=lambda item: item["score"], reverse=True)
    threshold = getattr(get_retriever(), "example_threshold", 0.35)
    if examples and examples[0]["score"] >= threshold:
        sql = _finalize_sql(examples[0]["sql"], state)
        events.append(_emit(
            "generate_sql",
            f"匹配到相似示例「{examples[0]['question']}」(相似度 {examples[0]['score']:.2f}),复用其 SQL",
            mode="fallback",
        ))
        return {"sql": sql, "mode": "fallback", "events": events}

    return {
        "error": "no_sql",
        "events": events + [_emit("generate_sql", "没有匹配到可复用的示例 SQL")],
    }


def validate_sql_node(state: dict) -> dict:
    if state.get("error"):
        return {}
    sql, error = check_sql_safety(state["sql"])
    if error:
        return {
            "sql": sql,
            "sql_error": error,
            "events": [_emit("validate_sql", f"安全校验未通过: {error}")],
        }
    return {
        "sql": sql,
        "sql_error": "",
        "events": [_emit("validate_sql", "安全校验通过(白名单/黑名单/行数上限)")],
    }


async def repair_sql_node(state: dict) -> dict:
    settings = get_settings()
    base = {"repair_count": state.get("repair_count", 0) + 1}
    if not settings.llm_enabled:
        return {**base, "error": "repair_unavailable", "events": [_emit("repair_sql", "降级模式无修复能力")]}

    try:
        user_prompt = (
            f"【被拒绝的SQL】\n{state['sql']}\n\n【失败原因】\n{state['sql_error']}\n\n"
            f"【表结构】\n" + "\n\n".join(state.get("schema_docs", []))
        )
        sql = _extract_sql(await chat_text(SQL_REPAIR_SYSTEM, user_prompt))
        sql = _finalize_sql(sql, state)
        return {**base, "sql": sql, "sql_error": "", "events": [_emit("repair_sql", "LLM 已尝试修复 SQL")]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQL 修复失败: %s", exc)
        return {**base, "error": "repair_failed", "events": [_emit("repair_sql", "SQL 修复失败")]}


# ============ SQL 执行 ============

async def execute_sql_node(state: dict) -> dict:
    if state.get("error") or state.get("sql_error"):
        return {}
    try:
        columns, rows, elapsed_ms = await execute_sql(state["sql"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQL 执行失败: %s", exc)
        return {
            "sql_error": f"执行失败: {exc}",
            "events": [_emit("execute_sql", "SQL 执行报错,尝试修复或兜底")],
        }
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "events": [_emit("execute_sql", f"查询完成,返回 {len(rows)} 行(耗时 {elapsed_ms}ms)")],
    }


# ============ 图表推荐(规则引擎) ============

_DATE_VALUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_DATE_COL_RE = re.compile(r"(日期|时间|date|dt|月|day)", re.IGNORECASE)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_chart_spec(columns: list[str], rows: list[list]) -> tuple[str, dict]:
    """基于结果集形状的图表推荐规则。"""
    if not rows or len(columns) < 2:
        return "table", {}

    def col_is_date(idx: int) -> bool:
        if _DATE_COL_RE.search(columns[idx]):
            return True
        return all(_DATE_VALUE_RE.match(str(row[idx])) for row in rows[:5])

    numeric_idx = [i for i in range(1, len(columns)) if all(_is_number(row[i]) for row in rows)]
    if not numeric_idx:
        return "table", {}

    value_idx = numeric_idx[0]
    value_name = columns[value_idx]
    sample = [row[value_idx] for row in rows if _is_number(row[value_idx])]

    if col_is_date(0) and len(rows) >= 2:
        option = {
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 48, "right": 24, "top": 32, "bottom": 32},
            "xAxis": {"type": "category", "data": [str(row[0])[:10] for row in rows]},
            "yAxis": {"type": "value"},
            "series": [{"name": value_name, "type": "line", "smooth": True, "data": sample,
                        "areaStyle": {"opacity": 0.12}}],
        }
        return "line", option

    if len(columns) == 2 and 2 <= len(rows) <= 6 and all(row[value_idx] >= 0 for row in rows):
        option = {
            "tooltip": {"trigger": "item"},
            "legend": {"bottom": 0},
            "series": [{
                "name": value_name,
                "type": "pie",
                "radius": ["38%", "62%"],
                "data": [{"name": str(row[0]), "value": row[value_idx]} for row in rows],
                "label": {"formatter": "{b}: {d}%"},
            }],
        }
        return "pie", option

    option = {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 48, "right": 24, "top": 32, "bottom": 80},
        "xAxis": {"type": "category", "data": [str(row[0])[:12] for row in rows[:12]],
                  "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value"},
        "series": [{"name": value_name, "type": "bar", "data": [row[value_idx] for row in rows[:12]]}],
    }
    return "bar", option


def recommend_chart_node(state: dict) -> dict:
    if state.get("error"):
        return {}
    chart_type, chart_spec = build_chart_spec(state.get("columns", []), state.get("rows", []))
    return {
        "chart_type": chart_type,
        "chart_spec": chart_spec,
        "events": [_emit("recommend_chart", f"推荐图表类型: {chart_type}")],
    }


# ============ 结论生成 ============

def _preview_table(columns: list[str], rows: list[list], limit: int = 10) -> str:
    head = " | ".join(columns)
    body = "\n".join(" | ".join(str(v) for v in row) for row in rows[:limit])
    return f"列: {head}\n前 {min(limit, len(rows))} 行:\n{body}"


def _rule_summary(columns: list[str], rows: list[list]) -> str:
    if not rows:
        return "查询没有返回数据:可能是所选时间段内没有符合条件的记录,建议调整时间范围或换一个指标。"
    text = f"查询共返回 {len(rows)} 行结果。"
    numeric_idx = [i for i in range(1, len(columns)) if all(_is_number(row[i]) for row in rows)]
    if numeric_idx and rows:
        idx = numeric_idx[0]
        values = [row[idx] for row in rows]
        best = max(rows, key=lambda row: row[idx])
        text += f"「{columns[idx]}」最高的是 {best[0]},数值为 {best[idx]:.2f}。"
        if all(_is_number(v) for v in values):
            text += f"合计 {sum(values):.2f}。"
    return text


async def summarize_node(state: dict) -> dict:
    if state.get("error"):
        return {}
    columns, rows = state.get("columns", []), state.get("rows", [])
    settings = get_settings()

    if settings.llm_enabled:
        try:
            user_prompt = (
                f"【用户问题】{state['rewritten_question']}\n"
                f"【查询结果】\n{_preview_table(columns, rows)}\n共 {len(rows)} 行。"
            )
            summary = await chat_text(SUMMARIZE_SYSTEM, user_prompt, max_tokens=400)
            return {"answer_md": summary, "events": [_emit("summarize", "LLM 已生成分析结论", mode="llm")]}
        except Exception as exc:  # noqa: BLE001
            logger.warning("结论生成失败,降级为规则摘要: %s", exc)

    return {
        "answer_md": _rule_summary(columns, rows),
        "events": [_emit("summarize", "已生成规则摘要(降级模式)", mode="fallback")],
    }


# ============ 归因分析(模板 SQL + 贡献度计算) ============

_BREAKDOWN_SQL = (
    "SELECT d.{dim} AS dim_name, "
    "SUM(CASE WHEN o.order_date >= '{ps}' AND o.order_date < '{pe}' THEN o.pay_amount ELSE 0 END) AS cur_gmv, "
    "SUM(CASE WHEN o.order_date >= '{ps2}' AND o.order_date < '{pe2}' THEN o.pay_amount ELSE 0 END) AS prev_gmv "
    "FROM fact_orders o {joins} "
    "WHERE o.order_status IN ('已完成','已支付','已退款') "
    "GROUP BY d.{dim} ORDER BY cur_gmv DESC"
)


async def _run_breakdown(dim: str, joins: str, ps: str, pe: str, ps2: str, pe2: str) -> list[list]:
    sql = _BREAKDOWN_SQL.format(dim=dim, joins=joins, ps=ps, pe=pe, ps2=ps2, pe2=pe2)
    checked, error = check_sql_safety(sql)
    if error:
        raise RuntimeError(error)
    columns, rows, _ = await execute_sql(checked)
    return rows


def _contribution_rows(rows: list[list]) -> list[list]:
    result = []
    for name, cur, prev in rows:
        delta = (cur or 0) - (prev or 0)
        result.append([name, round(cur or 0, 2), round(prev or 0, 2), round(delta, 2)])
    result.sort(key=lambda item: item[3])
    return result


async def attribution_run_node(state: dict) -> dict:
    if state.get("error"):
        return {}
    ps, pe = state.get("period_start"), state.get("period_end")
    if not ps or not pe:
        ps, pe = parse_period_fallback(state["rewritten_question"])
    end_date = date.fromisoformat(pe) - timedelta(days=1)
    span = (end_date - date.fromisoformat(ps)).days + 1
    ps2 = (date.fromisoformat(ps) - timedelta(days=span)).isoformat()
    pe2 = ps

    events = [_emit("attribution_run", f"对比窗口: {ps}~{end_date} 与 {ps2}~{date.fromisoformat(ps2) - timedelta(days=1)}")]
    try:
        category_rows = await _run_breakdown(
            "category",
            "JOIN fact_order_items i ON i.order_id = o.order_id "
            "JOIN dim_product d ON i.product_id = d.product_id",
            ps, pe, ps2, pe2,
        )
    except Exception:
        logger.warning("品类维度归因查询失败", exc_info=True)
        category_rows = []
    try:
        region_rows = await _run_breakdown(
            "region",
            "JOIN dim_shop d ON o.shop_id = d.shop_id",
            ps, pe, ps2, pe2,
        )
    except Exception:
        logger.warning("区域维度归因查询失败", exc_info=True)
        region_rows = []

    category_rows = _contribution_rows(category_rows)
    region_rows = _contribution_rows(region_rows)
    if not category_rows and not region_rows:
        return {"error": "attribution_failed", "events": events}

    all_rows = category_rows + region_rows
    total_delta = sum(row[3] for row in all_rows)
    total_prev = sum(row[2] for row in category_rows) or 1
    change_pct = total_delta / total_prev * 100

    def fmt(row: list) -> str:
        direction = "贡献" if row[3] > 0 else "拖累"
        share = abs(row[3]) / max(abs(total_delta), 1) * 100
        return f"{row[0]}({direction} {row[3]:+.0f},占变化幅度 {share:.0f}%)"

    drivers = [fmt(row) for row in sorted(all_rows, key=lambda item: item[3], reverse=True)[:2]]
    drags = [fmt(row) for row in all_rows[:2] if row[3] < 0]
    answer = (
        f"本期 GMV 环比变化 {total_delta:+,.0f} 元({change_pct:+.1f}%)。"
        f"正向拉动主要来自:{'、'.join(drivers) or '无明显正向因素'}。"
    )
    if drags:
        answer += f"主要拖累项:{'、'.join(drags)}。"

    top_rows = sorted(all_rows, key=lambda item: abs(item[3]), reverse=True)[:8]
    chart_spec = {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 60, "right": 24, "top": 32, "bottom": 80},
        "xAxis": {"type": "category", "data": [f"{row[0]}" for row in top_rows], "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value"},
        "series": [{"name": "GMV变化", "type": "bar", "data": [row[3] for row in top_rows]}],
    }

    columns = ["维度", "本期GMV", "上期GMV", "变化"]
    preview = _preview_table(columns, top_rows)
    if get_settings().llm_enabled:
        try:
            extra = await chat_text(
                SUMMARIZE_SYSTEM,
                f"【用户问题】{state['rewritten_question']}\n【分维度对比结果】\n{preview}",
                max_tokens=300,
            )
            answer += "\n\n" + extra
        except Exception as exc:  # noqa: BLE001
            logger.warning("归因结论润色失败: %s", exc)

    return {
        "answer_md": answer,
        "chart_type": "bar",
        "chart_spec": chart_spec,
        "columns": columns,
        "rows": top_rows,
        "row_count": len(top_rows),
        "events": events + [_emit("attribution_run", "归因拆解完成(品类/区域两个维度)")],
    }


# ============ 兜底与闲聊 ============

def small_talk_node(state: dict) -> dict:
    return {
        "answer_md": (
            "你好!我是 ChatBI 数据助手,可以直接问我经营数据,例如:\n"
            "- 最近30天各品类的销售额排名\n- 上个月各区域的退款率\n- 2026年6月每天的销售趋势\n"
            "- 上个月GMV为什么下降"
        ),
        "events": [_emit("small_talk", "闲聊应答")],
    }


def fallback_answer_node(state: dict) -> dict:
    if state.get("error") == "out_of_domain":
        return {
            "answer_md": (
                "这个问题超出了当前语义层覆盖的范围,我无法可靠作答。\n"
                "当前可查询的主题包括:销售额/GMV、订单量、客单价、退款率与退款原因、"
                "商品销量、店铺、客户与会员等级、支付方式、评价评分。\n"
                "建议换个问法,或先在「数据字典」页了解可查询的数据范围。"
            ),
            "events": [_emit("fallback_answer", "域外问题,已拒答并给出引导")],
        }
    return {
        "answer_md": (
            "这个问题暂时没能完成查询。常见原因:\n"
            "1. 问题涉及的数据不在当前语义层(目前覆盖 订单/商品/店铺/客户/退款/评价 六个主题);\n"
            "2. 时间范围超出数据集统计区间;\n"
            "3. 生成的 SQL 未通过安全校验。\n"
            "建议换个更具体的问法,例如「最近30天各品类销售额排名」。"
        ),
        "events": [_emit("fallback_answer", "已返回兜底应答")],
    }


async def data_end_probe() -> None:
    await asyncio.to_thread(_data_end)
