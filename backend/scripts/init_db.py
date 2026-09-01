"""将 CSV 数据导入数据库(SQLite / MySQL 均支持),并建立常用查询索引。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.db.database import engine

CSV_DIR = BACKEND_DIR / "data" / "csv"

INT_COLUMNS = {"quantity", "star"}
INDEXES = [
    ("idx_orders_date", "fact_orders", "order_date"),
    ("idx_orders_status", "fact_orders", "order_status"),
    ("idx_orders_customer", "fact_orders", "customer_id"),
    ("idx_orders_shop", "fact_orders", "shop_id"),
    ("idx_items_order", "fact_order_items", "order_id"),
    ("idx_items_product", "fact_order_items", "product_id"),
    ("idx_refunds_order", "fact_refunds", "order_id"),
    ("idx_refunds_date", "fact_refunds", "refund_date"),
    ("idx_reviews_order", "fact_reviews", "order_id"),
]


def main() -> None:
    settings = get_settings()
    summary_path = CSV_DIR / "summary.json"
    if not summary_path.exists():
        raise SystemExit("未找到 data/csv/summary.json,请先运行 python scripts/generate_data.py")

    summary = __import__("json").loads(summary_path.read_text(encoding="utf-8"))
    is_mysql = settings.db_url.startswith("mysql")

    for table in summary["rows"]:
        csv_path = CSV_DIR / f"{table}.csv"
        df = pd.read_csv(csv_path, encoding="utf-8-sig").fillna("")
        for col in INT_COLUMNS & set(df.columns):
            df[col] = df[col].astype(int)
        df.to_sql(table, engine, if_exists="replace", index=False,
                  chunksize=5000, method="multi" if is_mysql else None)
        print(f"导入 {table}: {len(df)} 行")

    with engine.begin() as conn:
        for index_name, table, column in INDEXES:
            dialect = "mysql" if is_mysql else "sqlite"
            conn.execute(text(
                f"CREATE INDEX {index_name} ON {table} ({column})"
                if dialect == "sqlite" else
                f"ALTER TABLE {table} ADD INDEX {index_name} ({column})"
            ))
    print(f"数据库初始化完成: {settings.db_url}")


if __name__ == "__main__":
    main()
