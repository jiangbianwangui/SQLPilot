"""演示库（SQLite）注释注入 + 选表器回归测试。

背景：SQLite 的 inspector 读不到 COMMENT，导致 SchemaRetriever 在演示库上
打分全为 0、只能退回字母序前 top_k 张表。修复是把中文注释注入
engine.sqlpilot_comments。本文件锁住这个契约，防止演示 Demo 选表退化为字母序。
"""

from app.demo import build_demo_engine
from app.core.schema_retriever import SchemaRetriever
from sqlalchemy import text


def test_demo_engine_injects_comments():
    eng = build_demo_engine()
    comments = getattr(eng, "sqlpilot_comments", None)
    assert comments, "演示库必须注入 sqlpilot_comments"
    # 核心表与部分新增表都要有注释，否则选表器无法区分
    for t in ("customers", "orders", "products", "suppliers", "reviews"):
        assert t in comments, f"{t} 缺少演示注释"


def test_retriever_selects_relevant_subset_not_alphabetical():
    eng = build_demo_engine()
    r = SchemaRetriever.from_engine(eng, top_k=5)
    # 供应商类问题应只命中 suppliers，而不是字母序前 5 张表
    assert r.select_tables("上海有哪些供应商") == ["suppliers"]
    # 退货相关应命中 returns 而非无关表
    sel = r.select_tables("哪些订单退款了")
    assert "returns" in sel
    assert "orders" in sel


def test_demo_has_all_14_tables_with_data():
    eng = build_demo_engine()
    with eng.connect() as c:
        n = c.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        ).scalar()
        assert n == 14
        for t in (
            "suppliers",
            "coupons",
            "reviews",
            "shipments",
            "payments",
            "returns",
            "addresses",
            "cart_items",
            "staff",
        ):
            assert c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() > 0
