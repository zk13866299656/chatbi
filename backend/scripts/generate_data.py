"""生成中文电商仿真数据集(10 万级订单)。

为什么自建数据而不是用 Kaggle 的 Olist:
1. 中文商品/城市/区域,演示和面试讲解更贴近国内业务;
2. 内置 618 / 双11 季节性、区域权重、品类退款率差异,归因分析有"戏可看";
3. 无需下载账号,脚本一键可复现。

输出: backend/data/csv/*.csv
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "csv"
DATA_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = datetime(2025, 9, 1)
END_DATE = datetime(2026, 8, 31)
BASE_ORDERS_PER_DAY = 240

# (品类, 权重, 价格区间, 基础退款率, 品牌)
CATEGORIES = [
    ("手机数码", 0.16, (500, 6000), 0.05, ["华为", "小米", "OPPO", "vivo", "荣耀"]),
    ("服饰鞋包", 0.18, (80, 800), 0.14, ["优衣库", "森马", "太平鸟", "百丽"]),
    ("美妆个护", 0.13, (40, 400), 0.08, ["完美日记", "花西子", "欧莱雅", "百雀羚"]),
    ("食品饮料", 0.14, (15, 200), 0.04, ["三只松鼠", "良品铺子", "农夫山泉", "伊利"]),
    ("家居日用", 0.10, (30, 600), 0.07, ["网易严选", "无印良品", "水星家纺"]),
    ("家用电器", 0.09, (150, 4000), 0.06, ["美的", "格力", "小熊", "苏泊尔"]),
    ("运动户外", 0.07, (60, 900), 0.08, ["李宁", "安踏", "迪卡侬", "Keep"]),
    ("图书文娱", 0.05, (20, 150), 0.03, ["中信出版", "人民文学", "磨铁图书"]),
    ("母婴用品", 0.05, (50, 800), 0.06, ["babycare", "好孩子", "飞鹤"]),
    ("宠物生活", 0.03, (25, 400), 0.05, ["麦富迪", "卫仕", "小佩"]),
]

# (区域, 权重, [(城市, 城市内权重)])
REGIONS = [
    ("华东", 0.32, [("上海", 0.30), ("杭州", 0.25), ("南京", 0.20), ("苏州", 0.15), ("合肥", 0.10)]),
    ("华北", 0.22, [("北京", 0.40), ("天津", 0.25), ("石家庄", 0.20), ("太原", 0.15)]),
    ("华南", 0.20, [("广州", 0.35), ("深圳", 0.35), ("厦门", 0.15), ("佛山", 0.15)]),
    ("华中", 0.11, [("武汉", 0.40), ("长沙", 0.35), ("郑州", 0.25)]),
    ("西南", 0.09, [("成都", 0.40), ("重庆", 0.35), ("昆明", 0.25)]),
    ("东北", 0.04, [("沈阳", 0.40), ("大连", 0.30), ("哈尔滨", 0.30)]),
    ("西北", 0.02, [("西安", 0.45), ("兰州", 0.30), ("乌鲁木齐", 0.25)]),
]

# 月份季节性系数:双11、618 明显放量,2 月春节物流停滞回落
SEASONAL = {
    (2025, 9): 1.00, (2025, 10): 1.05, (2025, 11): 2.20, (2025, 12): 1.25,
    (2026, 1): 1.15, (2026, 2): 0.90, (2026, 3): 1.00, (2026, 4): 0.95,
    (2026, 5): 1.00, (2026, 6): 1.60, (2026, 7): 0.95, (2026, 8): 1.00,
}

STATUS_DIST = [("已完成", 0.68), ("已支付", 0.08), ("待支付", 0.06), ("已取消", 0.10), ("已退款", 0.08)]
PAY_METHODS = [("微信支付", 0.45), ("支付宝", 0.38), ("银联云闪付", 0.10), ("货到付款", 0.07)]
MEMBER_LEVELS = [("普通会员", 0.55), ("银卡会员", 0.25), ("金卡会员", 0.14), ("钻石会员", 0.06)]
REFUND_REASONS = [("七日无理由退货", 0.35), ("质量问题", 0.22), ("描述不符", 0.16), ("尺码/规格不合适", 0.15), ("物流损坏", 0.12)]
REVIEW_TAGS_GOOD = ["物流快", "包装好", "正品保障", "性价比高", "客服态度好", "质量不错"]
REVIEW_TAGS_BAD = ["做工一般", "物流慢", "与描述不符", "色差明显"]

PRODUCT_TEMPLATES = {
    "手机数码": ["旗舰手机", "蓝牙耳机", "智能手表", "充电宝", "平板电脑", "蓝牙音箱"],
    "服饰鞋包": ["休闲卫衣", "牛仔裤", "运动鞋", "双肩背包", "羽绒服", "连衣裙"],
    "美妆个护": ["精华液", "口红套装", "洗面奶", "防晒霜", "香水", "面膜盒装"],
    "食品饮料": ["坚果礼盒", "酸奶整箱", "膨化零食包", "咖啡豆", "果汁箱装", "牛肉干"],
    "家居日用": ["四件套床品", "收纳箱组", "香薰套装", "保温杯", "记忆枕", "洗衣凝珠"],
    "家用电器": ["空气炸锅", "变频空调", "破壁机", "电饭煲", "吸尘器", "加湿器"],
    "运动户外": ["跑步鞋", "瑜伽垫", "登山背包", "健身手套", "帐篷", "筋膜枪"],
    "图书文娱": ["长篇小说", "社科套装书", "少儿绘本", "艺术画册", "人物传记", "漫画合集"],
    "母婴用品": ["婴儿纸尿裤", "儿童安全座椅", "婴幼儿奶粉", "辅食机", "婴儿推车", "儿童保温壶"],
    "宠物生活": ["猫粮", "狗零食", "猫砂", "宠物饮水机", "狗狗牵引绳", "宠物玩具"],
}


def weighted_choice(options, weights):
    return random.choices(options, weights=weights, k=1)[0]


def pick_city():
    region = weighted_choice([r[0] for r in REGIONS], [r[1] for r in REGIONS])
    entry = next(r for r in REGIONS if r[0] == region)
    city = weighted_choice([c[0] for c in entry[2]], [c[1] for c in entry[2]])
    return region, city


def build_dimensions():
    shops, products, customers = [], [], []

    shop_seq = 1
    for category, _, _, _, brands in CATEGORIES:
        for brand in brands:
            for _ in range(3):  # 每个品牌 3 家区域旗舰店
                region, city = pick_city()
                shops.append({
                    "shop_id": f"SH{shop_seq:04d}",
                    "shop_name": f"{brand}{city}旗舰店",
                    "brand": brand,
                    "category": category,
                    "region": region,
                    "city": city,
                    "shop_rating": round(random.uniform(4.2, 5.0), 1),
                })
                shop_seq += 1

    pid = 1
    for category, _, (p_lo, p_hi), _, brands in CATEGORIES:
        templates = PRODUCT_TEMPLATES[category]
        for brand in brands:
            for tpl in templates:
                products.append({
                    "product_id": f"P{pid:05d}",
                    "product_name": f"{brand} {tpl}",
                    "category": category,
                    "brand": brand,
                    "unit_price": round(random.uniform(p_lo, p_hi), 2),
                    "status": "在售",
                })
                pid += 1

    for cid in range(1, 20001):
        region, city = pick_city()
        name_suffix = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=4))
        customers.append({
            "customer_id": f"C{cid:06d}",
            "customer_name": f"用户{name_suffix[:2]}****{name_suffix[2:]}",
            "region": region,
            "city": city,
            "member_level": weighted_choice([m[0] for m in MEMBER_LEVELS], [m[1] for m in MEMBER_LEVELS]),
            "register_date": (START_DATE - timedelta(days=random.randint(30, 900))).strftime("%Y-%m-%d"),
        })

    return shops, products, customers


def season_multiplier(day: datetime) -> float:
    base = SEASONAL.get((day.year, day.month), 1.0)
    if day.weekday() >= 5:
        base *= 1.15
    return base


def main() -> None:
    shops, products, customers = build_dimensions()
    shops_by_category: dict[str, list[dict]] = {}
    for shop in shops:
        shops_by_category.setdefault(shop["category"], []).append(shop)
    products_by_category: dict[str, list[dict]] = {}
    for product in products:
        products_by_category.setdefault(product["category"], []).append(product)

    cat_names = [c[0] for c in CATEGORIES]
    cat_weights = [c[1] for c in CATEGORIES]
    refund_base = {c[0]: c[3] for c in CATEGORIES}

    order_rows, item_rows, refund_rows, review_rows = [], [], [], []
    order_seq, item_seq = 0, 0

    day = START_DATE
    while day <= END_DATE:
        n_orders = max(1, int(BASE_ORDERS_PER_DAY * season_multiplier(day) * random.uniform(0.85, 1.15)))
        for _ in range(n_orders):
            order_seq += 1
            category = weighted_choice(cat_names, cat_weights)
            shop = random.choice(shops_by_category[category])
            customer = random.choice(customers) if random.random() > 0.30 else random.choice(customers[:3000])
            status = weighted_choice([s[0] for s in STATUS_DIST], [s[1] for s in STATUS_DIST])
            paid = status in ("已完成", "已支付", "已退款")

            order_dt = day.replace(
                hour=random.randint(0, 23), minute=random.randint(0, 59), second=random.randint(0, 59)
            )
            order_id = f"SO{order_dt.strftime('%Y%m%d')}{order_seq % 100000:05d}"

            n_items = weighted_choice([1, 2, 3, 4], [0.55, 0.28, 0.12, 0.05])
            item_amount, discount_total, items = 0.0, 0.0, []
            cat_products = products_by_category[category]
            for _ in range(n_items):
                product = random.choice(cat_products)
                qty = weighted_choice([1, 2, 3], [0.78, 0.16, 0.06])
                unit_price = round(product["unit_price"] * random.uniform(0.85, 1.0), 2)
                discount = round(unit_price * qty * random.choice([0, 0, 0.05, 0.1, 0.15]), 2)
                subtotal = round(unit_price * qty - discount, 2)
                item_amount += unit_price * qty
                discount_total += discount
                items.append((product, qty, unit_price, discount, subtotal))

            pay_amount = round(item_amount - discount_total, 2) if paid else 0.0
            order_rows.append({
                "order_id": order_id,
                "customer_id": customer["customer_id"],
                "shop_id": shop["shop_id"],
                "order_date": order_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "order_status": status,
                "pay_method": weighted_choice([p[0] for p in PAY_METHODS], [p[1] for p in PAY_METHODS]) if paid else "",
                "item_amount": round(item_amount, 2),
                "discount_amount": round(discount_total, 2),
                "pay_amount": pay_amount,
            })
            for product, qty, unit_price, discount, subtotal in items:
                item_seq += 1
                item_rows.append({
                    "item_id": f"I{item_seq:07d}",
                    "order_id": order_id,
                    "product_id": product["product_id"],
                    "quantity": qty,
                    "unit_price": unit_price,
                    "discount_amount": discount,
                    "subtotal": subtotal,
                })

            if status == "已退款":
                refund_dt = order_dt + timedelta(days=random.randint(1, 7))
                refund_rows.append({
                    "refund_id": f"RF{len(refund_rows) + 1:06d}",
                    "order_id": order_id,
                    "refund_amount": pay_amount,
                    "refund_date": refund_dt.strftime("%Y-%m-%d"),
                    "refund_reason": weighted_choice([r[0] for r in REFUND_REASONS], [r[1] for r in REFUND_REASONS]),
                })

            if status == "已完成" and random.random() < 0.45:
                # 退款率高的品类,评分整体偏低,便于演示"评分-品类"洞察
                if random.random() < refund_base[category] * 6:
                    star = weighted_choice([1, 2, 3], [0.35, 0.30, 0.35])
                    tags = random.sample(REVIEW_TAGS_BAD, k=random.randint(1, 2))
                else:
                    star = weighted_choice([3, 4, 5], [0.10, 0.28, 0.62])
                    tags = random.sample(REVIEW_TAGS_GOOD, k=random.randint(1, 3))
                review_rows.append({
                    "review_id": f"RV{len(review_rows) + 1:06d}",
                    "order_id": order_id,
                    "star": star,
                    "tags": ";".join(tags),
                    "created_at": (order_dt + timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d %H:%M:%S"),
                })
        day += timedelta(days=1)

    tables = {
        "dim_shop": (shops, ["shop_id", "shop_name", "brand", "category", "region", "city", "shop_rating"]),
        "dim_product": (products, ["product_id", "product_name", "category", "brand", "unit_price", "status"]),
        "dim_customer": (customers, ["customer_id", "customer_name", "region", "city", "member_level", "register_date"]),
        "fact_orders": (order_rows, ["order_id", "customer_id", "shop_id", "order_date", "order_status",
                                     "pay_method", "item_amount", "discount_amount", "pay_amount"]),
        "fact_order_items": (item_rows, ["item_id", "order_id", "product_id", "quantity", "unit_price",
                                         "discount_amount", "subtotal"]),
        "fact_refunds": (refund_rows, ["refund_id", "order_id", "refund_amount", "refund_date", "refund_reason"]),
        "fact_reviews": (review_rows, ["review_id", "order_id", "star", "tags", "created_at"]),
    }
    for name, (rows, columns) in tables.items():
        path = DATA_DIR / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    summary = {
        "date_range": [START_DATE.strftime("%Y-%m-%d"), END_DATE.strftime("%Y-%m-%d")],
        "rows": {name: len(rows) for name, (rows, _) in tables.items()},
    }
    (DATA_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
