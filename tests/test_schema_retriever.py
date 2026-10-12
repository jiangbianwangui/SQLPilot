"""schema_retriever 的单元测试（不依赖真实数据库）。"""
from __future__ import annotations

from app.core.schema_retriever import SchemaRetriever, _question_terms
from app.tools.schema_tool import ColumnInfo, TableInfo


def _demo_schema() -> dict[str, TableInfo]:
    """一个和 sql/init_db.sql 同构的迷你库（手动构造，无需连库）。"""
    return {
        "customers": TableInfo(
            "customers",
            [
                ColumnInfo("id", "INTEGER", False),
                ColumnInfo("name", "TEXT", False, comment="客户姓名"),
                ColumnInfo("city", "TEXT", True, comment="所在城市"),
            ],
            comment="客户",
        ),
        "orders": TableInfo(
            "orders",
            [
                ColumnInfo("id", "INTEGER", False),
                ColumnInfo("customer_id", "INTEGER", False, comment="下单客户"),
                ColumnInfo("amount", "DECIMAL(10,2)", False, comment="订单金额"),
            ],
            comment="订单",
        ),
        "products": TableInfo(
            "products",
            [
                ColumnInfo("id", "INTEGER", False),
                ColumnInfo("name", "TEXT", False, comment="商品名"),
                ColumnInfo("price", "DECIMAL(10,2)", False, comment="单价"),
            ],
            comment="商品",
        ),
    }


def test_chinese_terms_split_into_bigrams():
    terms = _question_terms("北京客户花了多少钱")
    assert "客户" in terms
    assert "多少" in terms


def test_pick_customer_and_orders_for_spend_question():
    """「花了多少钱」需要 customers + orders 两张表。"""
    r = SchemaRetriever(_demo_schema(), top_k=2)
    picked = r.select_tables("北京客户花了多少钱")
    assert "customers" in picked
    assert "orders" in picked


def test_pick_products_for_price_question():
    r = SchemaRetriever(_demo_schema(), top_k=2)
    picked = r.select_tables("最贵的商品是哪个")
    assert "products" in picked


def test_unknown_question_falls_back_to_some_tables():
    """完全匹配不上时也不能返回空，否则 LLM 只能瞎编字段。"""
    r = SchemaRetriever(_demo_schema(), top_k=2)
    picked = r.select_tables("asdfghjkl")
    assert picked, "一个都没召回时应退回默认表，不能为空"


def test_build_prompt_contains_selected_table():
    r = SchemaRetriever(_demo_schema())
    prompt = r.build_prompt("哪些商品库存不足")
    assert "products" in prompt
    assert "name" in prompt
