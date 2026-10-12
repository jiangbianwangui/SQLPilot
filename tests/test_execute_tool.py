"""execute_tool 的单元测试。"""
from __future__ import annotations

import pytest

from app.tools.execute_tool import ExecuteTool


def test_valid_select_returns_rows(engine):
    tool = ExecuteTool(engine)
    r = tool.execute("SELECT id, name FROM products")
    assert r.ok
    assert r.row_count == 3
    assert r.columns == ["id", "name"]
    # 行是 dict，字段名可索引
    assert r.rows[0]["name"] == "智能手机 X1"


def test_limit_auto_appended(engine):
    tool = ExecuteTool(engine, default_limit=2)
    r = tool.execute("SELECT id FROM products")
    assert r.ok
    assert "LIMIT" in r.sql.upper(), "没有自动加 LIMIT"
    assert r.row_count <= 2


def test_explicit_limit_respected(engine):
    tool = ExecuteTool(engine, default_limit=200)
    r = tool.execute("SELECT id FROM products LIMIT 1")
    assert r.ok
    assert r.row_count == 1


def test_drop_blocked_by_guard(engine):
    tool = ExecuteTool(engine)
    r = tool.execute("DROP TABLE products")
    assert not r.ok
    assert "DROP" in r.error.upper() or "删" in r.error


def test_invalid_syntax_rejected(engine):
    tool = ExecuteTool(engine)
    r = tool.execute("SELEC * FORM products")  # 故意拼错
    assert not r.ok
    assert r.error  # 必须给出原因，不能是空字符串


def test_nonexistent_column_normalized_error(engine):
    tool = ExecuteTool(engine)
    r = tool.execute("SELECT not_a_col FROM products")
    assert not r.ok
    assert r.error  # 至少是一句中文/原始提示
    # SQLite 没有整数错误码，MySQL 下会是 "1054"
    assert r.error_code is None or isinstance(r.error_code, str)


def test_union_query_runs(engine):
    tool = ExecuteTool(engine)
    r = tool.execute(
        "SELECT name FROM products UNION SELECT name FROM categories"
    )
    assert r.ok
    # 两张表各 3 / 3 行，UNION 去重后最多 6
    assert r.row_count <= 6


def test_join_query_runs(engine):
    tool = ExecuteTool(engine)
    r = tool.execute(
        "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id"
    )
    assert r.ok
    assert r.row_count == 3
    assert "name" in r.columns
