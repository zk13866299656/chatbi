"""表结构文档与指标口径文档(统一的 RAG 语料源)。

语义层(Semantic Layer)是 ChatBI 准确率的关键:
- 表结构文档:让 LLM 知道有哪些表、字段含义、JOIN 关系;
- 指标口径文档:统一 GMV / 退款率 / 客单价等指标的计算口径,避免"同名不同数";
- few-shot 示例:高质量问数样例,既是 RAG 语料,也是 SQL 生成的上下文,还是降级模式的兜底答案。

来源双轨:默认使用内置语义层(本项目电商数据集);配置 SEMANTIC_LAYER_FILE 指向 YAML
后加载外部语义层——这是 MCP 私有化部署接入"自己的数据库"的前置能力。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CorpusDoc:
    doc_id: str
    kind: str  # table | metric | example
    title: str
    text: str
    # example 类语料附带标准 SQL,降级模式可直接复用
    sql: str = ""


TABLE_DOCS: list[dict] = [
    {
        "table": "fact_orders",
        "meaning": "订单主表,一行代表一笔订单,是销售额/GMV/客单价等核心指标的主表",
        "fields": {
            "order_id": "订单号(主键)",
            "customer_id": "客户ID,关联 dim_customer",
            "shop_id": "店铺ID,关联 dim_shop",
            "order_date": "下单时间,格式 YYYY-MM-DD HH:MM:SS",
            "order_status": "订单状态:已完成/已支付/待支付/已取消/已退款",
            "pay_method": "支付方式:微信支付/支付宝/银联云闪付/货到付款;未支付订单为空",
            "item_amount": "商品原价总额",
            "discount_amount": "优惠总额",
            "pay_amount": "实付金额;仅 已完成/已支付/已退款 订单大于 0,待支付/已取消为 0",
        },
    },
    {
        "table": "fact_order_items",
        "meaning": "订单明细表,一行代表订单中的一个商品,分析品类/商品维度从这里出发",
        "fields": {
            "item_id": "明细ID(主键)",
            "order_id": "订单号,关联 fact_orders",
            "product_id": "商品ID,关联 dim_product",
            "quantity": "购买数量",
            "unit_price": "成交单价",
            "discount_amount": "该商品优惠金额",
            "subtotal": "该商品小计 = 数量×单价 - 优惠",
        },
    },
    {
        "table": "dim_product",
        "meaning": "商品维表",
        "fields": {
            "product_id": "商品ID(主键)",
            "product_name": "商品名称(品牌+品名)",
            "category": "品类:手机数码/服饰鞋包/美妆个护/食品饮料/家居日用/家用电器/运动户外/图书文娱/母婴用品/宠物生活",
            "brand": "品牌",
            "unit_price": "标准单价",
            "status": "上架状态",
        },
    },
    {
        "table": "dim_shop",
        "meaning": "店铺维表,店铺按品牌+城市开设,销售单一品类",
        "fields": {
            "shop_id": "店铺ID(主键)",
            "shop_name": "店铺名称(如 华为上海旗舰店)",
            "brand": "品牌",
            "category": "主营品类",
            "region": "大区:华东/华北/华南/华中/西南/东北/西北",
            "city": "城市",
            "shop_rating": "店铺服务评分",
        },
    },
    {
        "table": "dim_customer",
        "meaning": "客户维表",
        "fields": {
            "customer_id": "客户ID(主键)",
            "customer_name": "脱敏昵称",
            "region": "所在大区",
            "city": "所在城市",
            "member_level": "会员等级:普通会员/银卡会员/金卡会员/钻石会员",
            "register_date": "注册日期",
        },
    },
    {
        "table": "fact_refunds",
        "meaning": "退款记录表,一行代表一次退款,分析退款率/退款原因从这里出发",
        "fields": {
            "refund_id": "退款单号(主键)",
            "order_id": "订单号,关联 fact_orders",
            "refund_amount": "退款金额",
            "refund_date": "退款日期",
            "refund_reason": "退款原因:七日无理由退货/质量问题/描述不符/尺码或规格不合适/物流损坏",
        },
    },
    {
        "table": "fact_reviews",
        "meaning": "订单评价表,一行代表一条已确认收货订单的评价",
        "fields": {
            "review_id": "评价ID(主键)",
            "order_id": "订单号,关联 fact_orders",
            "star": "星级 1-5",
            "tags": "评价标签,分号分隔,如 物流快;包装好",
            "created_at": "评价时间",
        },
    },
]

JOIN_HINTS = [
    "订单-明细: fact_order_items.order_id = fact_orders.order_id",
    "明细-商品: fact_order_items.product_id = dim_product.product_id",
    "订单-店铺: fact_orders.shop_id = dim_shop.shop_id",
    "订单-客户: fact_orders.customer_id = dim_customer.customer_id",
    "订单-退款: fact_refunds.order_id = fact_orders.order_id",
    "订单-评价: fact_reviews.order_id = fact_orders.order_id",
]

METRIC_DOCS: list[dict] = [
    {
        "metric": "GMV(支付口径销售额)",
        "definition": "SUM(fact_orders.pay_amount),统计范围 order_status IN ('已完成','已支付','已退款')",
        "note": "已退款订单计入 GMV(钱曾收进);若用户问'净销售额'再剔除已退款",
    },
    {
        "metric": "支付订单数",
        "definition": "COUNT(DISTINCT order_id),order_status IN ('已完成','已支付','已退款')",
    },
    {
        "metric": "客单价",
        "definition": "GMV / 支付订单数,即 SUM(pay_amount) / COUNT(DISTINCT order_id)",
    },
    {
        "metric": "退款率(订单维度)",
        "definition": "有退款记录的订单数 / 支付订单数,即 COUNT(DISTINCT fact_refunds.order_id) / 支付订单数",
    },
    {
        "metric": "复购率",
        "definition": "支付订单数 ≥ 2 的客户数 / 支付客户数",
    },
    {
        "metric": "平均评分",
        "definition": "AVG(fact_reviews.star)",
    },
]

FEW_SHOT_EXAMPLES: list[dict] = [
    {
        "question": "上个月华南大区的GMV是多少",
        "sql": (
            "SELECT SUM(o.pay_amount) AS gmv FROM fact_orders o "
            "JOIN dim_shop s ON o.shop_id = s.shop_id "
            "WHERE o.order_status IN ('已完成','已支付','已退款') "
            "AND s.region = '{REGION}' "
            "AND o.order_date >= '__PSTART__' AND o.order_date < '__PEND__'"
        ),
        "note": "月份用日期区间而不是函数,兼容 SQLite/MySQL;__PSTART__/__PEND__ 由系统按问题时间替换",
    },
    {
        "question": "最近30天各品类的销售额排名",
        "sql": (
            "SELECT p.category AS category, SUM(i.subtotal) AS sales "
            "FROM fact_order_items i "
            "JOIN dim_product p ON i.product_id = p.product_id "
            "JOIN fact_orders o ON i.order_id = o.order_id "
            "WHERE o.order_status IN ('已完成','已支付','已退款') "
            "AND o.order_date >= '__PSTART__' AND o.order_date < '__PEND__' "
            "GROUP BY p.category ORDER BY sales DESC"
        ),
    },
    {
        "question": "上个月各区域的退款率",
        "sql": (
            "SELECT s.region AS region, "
            "COUNT(DISTINCT r.order_id) * 1.0 / COUNT(DISTINCT o.order_id) AS refund_rate "
            "FROM fact_orders o "
            "JOIN dim_shop s ON o.shop_id = s.shop_id "
            "LEFT JOIN fact_refunds r ON r.order_id = o.order_id "
            "WHERE o.order_status IN ('已完成','已支付','已退款') "
            "AND o.order_date >= '__PSTART__' AND o.order_date < '__PEND__' "
            "GROUP BY s.region ORDER BY refund_rate DESC"
        ),
    },
    {
        "question": "2026年6月每天的销售趋势",
        "sql": (
            "SELECT DATE(o.order_date) AS dt, SUM(o.pay_amount) AS gmv "
            "FROM fact_orders o "
            "WHERE o.order_status IN ('已完成','已支付','已退款') "
            "AND o.order_date >= '2026-06-01' AND o.order_date < '2026-07-01' "
            "GROUP BY DATE(o.order_date) ORDER BY dt"
        ),
    },
    {
        "question": "金卡会员的客单价是多少",
        "sql": (
            "SELECT SUM(o.pay_amount) * 1.0 / COUNT(DISTINCT o.order_id) AS avg_order_value "
            "FROM fact_orders o "
            "JOIN dim_customer c ON o.customer_id = c.customer_id "
            "WHERE o.order_status IN ('已完成','已支付','已退款') AND c.member_level = '金卡会员'"
        ),
    },
    {
        "question": "销量最高的10个商品",
        "sql": (
            "SELECT p.product_name AS product_name, SUM(i.quantity) AS total_qty "
            "FROM fact_order_items i "
            "JOIN dim_product p ON i.product_id = p.product_id "
            "JOIN fact_orders o ON i.order_id = o.order_id "
            "WHERE o.order_status IN ('已完成','已支付','已退款') "
            "AND o.order_date >= '__PSTART__' AND o.order_date < '__PEND__' "
            "GROUP BY p.product_name ORDER BY total_qty DESC LIMIT 10"
        ),
    },
    {
        "question": "各支付方式的订单占比",
        "sql": (
            "SELECT pay_method, COUNT(*) AS order_count "
            "FROM fact_orders "
            "WHERE order_status IN ('已完成','已支付','已退款') "
            "AND order_date >= '__PSTART__' AND order_date < '__PEND__' "
            "GROUP BY pay_method ORDER BY order_count DESC"
        ),
    },
    {
        "question": "上个月的平均评分和评价数",
        "sql": (
            "SELECT AVG(star) AS avg_star, COUNT(*) AS review_count "
            "FROM fact_reviews WHERE created_at >= '__PSTART__' AND created_at < '__PEND__'"
        ),
    },
    {
        "question": "最近30天各城市的销售额TOP10",
        "sql": (
            "SELECT s.city AS city, SUM(o.pay_amount) AS gmv "
            "FROM fact_orders o JOIN dim_shop s ON o.shop_id = s.shop_id "
            "WHERE o.order_status IN ('已完成','已支付','已退款') "
            "AND o.order_date >= '__PSTART__' AND o.order_date < '__PEND__' "
            "GROUP BY s.city ORDER BY gmv DESC LIMIT 10"
        ),
    },
    {
        "question": "上个月各品牌的销售额排名",
        "sql": (
            "SELECT s.brand AS brand, SUM(o.pay_amount) AS gmv "
            "FROM fact_orders o JOIN dim_shop s ON o.shop_id = s.shop_id "
            "WHERE o.order_status IN ('已完成','已支付','已退款') "
            "AND o.order_date >= '__PSTART__' AND o.order_date < '__PEND__' "
            "GROUP BY s.brand ORDER BY gmv DESC"
        ),
    },
    {
        "question": "上个月各支付方式的GMV",
        "sql": (
            "SELECT pay_method, SUM(pay_amount) AS gmv "
            "FROM fact_orders "
            "WHERE order_status IN ('已完成','已支付','已退款') "
            "AND pay_method <> '' "
            "AND order_date >= '__PSTART__' AND order_date < '__PEND__' "
            "GROUP BY pay_method ORDER BY gmv DESC"
        ),
    },
    {
        "question": "评分最低的3个店铺",
        "sql": (
            "SELECT s.shop_name AS shop_name, AVG(rv.star) AS avg_star "
            "FROM fact_reviews rv "
            "JOIN fact_orders o ON rv.order_id = o.order_id "
            "JOIN dim_shop s ON o.shop_id = s.shop_id "
            "GROUP BY s.shop_name ORDER BY avg_star ASC LIMIT 3"
        ),
    },
    {
        "question": "各订单状态的分布",
        "sql": (
            "SELECT order_status, COUNT(*) AS order_count "
            "FROM fact_orders GROUP BY order_status ORDER BY order_count DESC"
        ),
    },
    {
        "question": "各区域有多少客户",
        "sql": (
            "SELECT region, COUNT(*) AS customer_count "
            "FROM dim_customer GROUP BY region ORDER BY customer_count DESC"
        ),
    },
]


@lru_cache
def get_semantic_source() -> dict[str, Any]:
    """语义层来源双轨:SEMANTIC_LAYER_FILE 指向 YAML 时加载外部语义层,否则使用内置。

    外部语义层是 MCP 私有化部署接入"自己的数据库"的关键:
    引擎部署到对方环境后,由对方按模板描述自己的表结构/口径/示例。
    """
    settings = get_settings()
    file_name = (settings.semantic_layer_file or "").strip()
    if not file_name:
        return {
            "source": "builtin",
            "tables": TABLE_DOCS,
            "metrics": METRIC_DOCS,
            "examples": FEW_SHOT_EXAMPLES,
            "joins": JOIN_HINTS,
        }

    path = Path(file_name)
    if not path.is_absolute():
        path = settings.base_dir / path
    if not path.exists():
        raise FileNotFoundError(f"语义层文件不存在: {path}")

    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("tables"):
        raise ValueError(f"语义层文件缺少 tables 定义: {path}")

    source = {
        "source": f"file:{path.name}",
        "tables": data["tables"],
        "metrics": data.get("metrics") or [],
        "examples": data.get("examples") or [],
        "joins": data.get("joins") or [],
    }
    logger.info(
        "已加载外部语义层 %s: tables=%d metrics=%d examples=%d",
        path, len(source["tables"]), len(source["metrics"]), len(source["examples"]),
    )
    return source


def get_tables() -> list[dict]:
    return get_semantic_source()["tables"]


def get_metrics() -> list[dict]:
    return get_semantic_source()["metrics"]


def get_examples() -> list[dict]:
    return get_semantic_source()["examples"]


def get_joins() -> list[str]:
    return get_semantic_source()["joins"]


def build_corpus() -> list[CorpusDoc]:
    """把表结构 / 口径 / 示例拼装成可检索语料(来源由语义层配置决定)。"""
    docs: list[CorpusDoc] = []
    for table in get_tables():
        fields_text = "\n".join(f"- {k}: {v}" for k, v in table["fields"].items())
        docs.append(CorpusDoc(
            doc_id=f"table:{table['table']}",
            kind="table",
            title=table["table"],
            text=f"表 {table['table']}: {table['meaning']}\n字段说明:\n{fields_text}",
        ))
    joins = get_joins()
    if joins:
        docs.append(CorpusDoc(
            doc_id="join:hints", kind="table", title="表关联关系",
            text="表关联关系:\n" + "\n".join(f"- {h}" for h in joins),
        ))
    for metric in get_metrics():
        docs.append(CorpusDoc(
            doc_id=f"metric:{metric['metric']}", kind="metric", title=metric["metric"],
            text=f"指标【{metric['metric']}】口径: {metric['definition']}"
                 + (f"\n注意: {metric['note']}" if metric.get("note") else ""),
        ))
    for idx, example in enumerate(get_examples(), 1):
        docs.append(CorpusDoc(
            doc_id=f"example:{idx}", kind="example", title=example["question"],
            text=f"问题: {example['question']}\n参考SQL:\n{example['sql']}",
            sql=example["sql"],
        ))
    return docs
