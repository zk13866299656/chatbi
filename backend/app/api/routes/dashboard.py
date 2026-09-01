"""经营看板接口:核心 KPI、销售趋势、品类结构。

看板走固定 SQL(不经 LLM),与问数链路互补:
看板要的是稳定与秒开,问数要的是灵活。
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import text

from ...agents.nodes import _data_end
from ...db.database import engine
from ...models.schemas import ApiResponse

router = APIRouter(tags=["dashboard"])

PAID_STATUS = "('已完成','已支付','已退款')"


def _windows(days: int) -> dict:
    data_end = date.fromisoformat(_data_end())
    cur_end = data_end + timedelta(days=1)
    cur_start = cur_end - timedelta(days=days)
    prev_start = cur_start - timedelta(days=days)
    return {"ps": cur_start.isoformat(), "pe": cur_end.isoformat(), "pps": prev_start.isoformat()}


@router.get("/dashboard/overview", response_model=ApiResponse)
async def overview(days: int = Query(30, ge=7, le=90)):
    params = _windows(days)
    sql = text(f"""
        SELECT
            SUM(CASE WHEN o.order_date >= :ps THEN o.pay_amount ELSE 0 END) AS cur_gmv,
            SUM(CASE WHEN o.order_date >= :pps AND o.order_date < :ps THEN o.pay_amount ELSE 0 END) AS prev_gmv,
            COUNT(DISTINCT CASE WHEN o.order_date >= :ps THEN o.order_id END) AS cur_orders,
            COUNT(DISTINCT CASE WHEN o.order_date >= :pps AND o.order_date < :ps THEN o.order_id END) AS prev_orders,
            COUNT(DISTINCT CASE WHEN o.order_date >= :ps AND o.order_status = '已退款' THEN o.order_id END) AS cur_refunds,
            COUNT(DISTINCT CASE WHEN o.order_date >= :pps AND o.order_date < :ps
                    AND o.order_status = '已退款' THEN o.order_id END) AS prev_refunds
        FROM fact_orders o
        WHERE o.order_status IN {PAID_STATUS} AND o.order_date >= :pps AND o.order_date < :pe
    """)
    with engine.connect() as conn:
        row = conn.execute(sql, params).mappings().one()

    def pct(cur: float, prev: float) -> float | None:
        if not prev:
            return None
        return round((cur - prev) / prev * 100, 1)

    cur_gmv, prev_gmv = float(row["cur_gmv"] or 0), float(row["prev_gmv"] or 0)
    cur_orders, prev_orders = int(row["cur_orders"] or 0), int(row["prev_orders"] or 0)
    cur_aov = cur_gmv / cur_orders if cur_orders else 0
    prev_aov = prev_gmv / prev_orders if prev_orders else 0
    cur_refund = (int(row["cur_refunds"] or 0) / cur_orders * 100) if cur_orders else 0
    prev_refund = (int(row["prev_refunds"] or 0) / prev_orders * 100) if prev_orders else 0

    return ApiResponse(data={
        "days": days,
        "gmv": {"value": round(cur_gmv, 2), "delta_pct": pct(cur_gmv, prev_gmv)},
        "orders": {"value": cur_orders, "delta_pct": pct(cur_orders, prev_orders)},
        "aov": {"value": round(cur_aov, 2), "delta_pct": pct(cur_aov, prev_aov)},
        "refund_rate": {"value": round(cur_refund, 2), "delta_pct": pct(cur_refund, prev_refund)},
        "period": [params["ps"], params["pe"]],
    })


@router.get("/dashboard/trend", response_model=ApiResponse)
async def trend(days: int = Query(30, ge=7, le=90)):
    params = _windows(days)
    sql = text(f"""
        SELECT DATE(o.order_date) AS dt, SUM(o.pay_amount) AS gmv,
               COUNT(DISTINCT o.order_id) AS orders
        FROM fact_orders o
        WHERE o.order_status IN {PAID_STATUS} AND o.order_date >= :ps AND o.order_date < :pe
        GROUP BY DATE(o.order_date) ORDER BY dt
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return ApiResponse(data={
        "dates": [str(row[0])[:10] for row in rows],
        "gmv": [float(row[1] or 0) for row in rows],
        "orders": [int(row[2] or 0) for row in rows],
    })


@router.get("/dashboard/category", response_model=ApiResponse)
async def category(days: int = Query(30, ge=7, le=90)):
    params = _windows(days)
    sql = text(f"""
        SELECT s.category AS category, SUM(o.pay_amount) AS gmv
        FROM fact_orders o JOIN dim_shop s ON o.shop_id = s.shop_id
        WHERE o.order_status IN {PAID_STATUS} AND o.order_date >= :ps AND o.order_date < :pe
        GROUP BY s.category ORDER BY gmv DESC
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return ApiResponse(data={
        "categories": [row[0] for row in rows],
        "gmv": [float(row[1] or 0) for row in rows],
    })
