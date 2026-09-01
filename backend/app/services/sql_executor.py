"""SQL 安全校验与执行服务。

ChatBI 直接对业务库执行 LLM 生成的 SQL,安全层必须硬:
1. 白名单:只允许单条 SELECT;表名必须在语义层注册过;
2. 黑名单:DDL/DML/PRAGMA 等关键词直接拒绝;
3. 兜底:强制注入行数上限,执行前先 EXPLAIN;
4. 执行走线程池,不阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from sqlalchemy import text

from ..config import get_settings
from ..db.database import engine

logger = logging.getLogger(__name__)

ALLOWED_TABLES = {
    "fact_orders", "fact_order_items", "dim_product", "dim_shop",
    "dim_customer", "fact_refunds", "fact_reviews",
}
FORBIDDEN_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "REPLACE",
    "TRUNCATE", "ATTACH", "DETACH", "PRAGMA", "GRANT", "REVOKE", "VACUUM",
    "INTO", "SET", "MERGE", "CALL", "EXECUTE",
}
_WORD_RE = re.compile(r"[A-Za-z_]+")
_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)


def check_sql_safety(sql: str) -> tuple[str, str | None]:
    """返回 (规范化后的 SQL, 错误信息)。错误为 None 表示通过。"""
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        return "", "SQL 为空"
    if not re.match(r"(?is)^\s*(SELECT|WITH)\b", cleaned):
        return cleaned, "只允许执行 SELECT 查询"

    upper = cleaned.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        for word in _WORD_RE.findall(upper):
            if word == keyword:
                return cleaned, f"禁止使用关键字 {keyword}"

    # 多语句防护:分号只可能出现在字符串字面量中,出现顶层分号直接拒绝
    if ";" in cleaned.replace("'", "").replace('"', ""):
        return cleaned, "禁止一次执行多条语句"

    referenced = {name.lower() for name in _TABLE_REF_RE.findall(cleaned)}
    unknown = referenced - ALLOWED_TABLES
    if unknown:
        return cleaned, f"引用了未注册的表: {', '.join(sorted(unknown))}"

    settings = get_settings()
    limit_match = _LIMIT_RE.search(cleaned)
    if limit_match:
        if int(limit_match.group(1)) > settings.sql_max_rows:
            cleaned = _LIMIT_RE.sub(f"LIMIT {settings.sql_max_rows}", cleaned)
    else:
        cleaned = f"{cleaned}\nLIMIT {settings.sql_max_rows}"

    return cleaned, None


def _execute_sync(sql: str, max_rows: int) -> tuple[list[str], list[list]]:
    with engine.connect() as conn:
        conn.execute(text(f"EXPLAIN {sql}" if engine.url.get_backend_name() == "sqlite" else f"EXPLAIN {sql}"))
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [list(row) for row in result.fetchmany(max_rows + 1)]
    return columns, rows[:max_rows]


async def execute_sql(sql: str) -> tuple[list[str], list[list], float]:
    """执行 SQL,返回 (列名, 行数据, 耗时ms)。"""
    settings = get_settings()
    started = time.perf_counter()
    columns, rows = await asyncio.wait_for(
        asyncio.to_thread(_execute_sync, sql, settings.sql_max_rows),
        timeout=settings.sql_timeout_seconds + 5,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("sql_executed rows=%d elapsed_ms=%d", len(rows), elapsed_ms)
    return columns, rows, elapsed_ms
