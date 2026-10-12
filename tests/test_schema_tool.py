"""schema_tool 的单元测试。"""
from __future__ import annotations

from app.tools.schema_tool import SchemaTool


def test_list_tables(engine):
    tool = SchemaTool(engine)
    tables = tool.list_tables()
    assert set(tables) >= {"products", "customers", "orders"}


def test_get_table_schema_columns(engine):
    tool = SchemaTool(engine)
    info = tool.get_table_schema("products")
    assert info is not None
    names = {c.name for c in info.columns}
    assert {"id", "name", "category_id", "price", "stock"} <= names
    # 类型被解析成字符串，非空
    assert all(c.type for c in info.columns)


def test_missing_table_returns_none(engine):
    tool = SchemaTool(engine)
    assert tool.get_table_schema("ghost_table") is None


def test_to_prompt_contains_names(engine):
    tool = SchemaTool(engine)
    prompt = tool.to_prompt(["products"])
    assert "products" in prompt
    assert "price" in prompt
    assert "name" in prompt


def test_full_schema(engine):
    tool = SchemaTool(engine)
    full = tool.get_full_schema()
    assert "orders" in full
    assert full["orders"].columns  # 至少要有字段
