"""retry_loop 的单元测试 —— 用 fake LLM 测自修复行为，不烧 API。"""
from __future__ import annotations

from app.core.retry_loop import RetryLoop, extract_sql
from app.tools.execute_tool import ExecuteTool

_SCHEMA_PROMPT = "表 products\n  - id INTEGER\n  - name TEXT\n  - price REAL"


def test_self_repair_on_bad_column(engine):
    """第一次写错字段名，第二次改对 —— 这是项目最值得演示的行为。"""
    calls: list[str] = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return "SELECT not_a_col FROM products" if len(calls) == 1 else "SELECT id FROM products"

    tool = ExecuteTool(engine)
    loop = RetryLoop(fake_llm, tool.execute, max_attempts=3)
    r = loop.run("查商品", _SCHEMA_PROMPT)

    assert r.ok, "第二次应该改对"
    assert r.attempts_used == 2
    assert r.sql == "SELECT id FROM products"
    assert r.rows, "应该真的查到数据"
    # 第二次的 prompt 必须包含第一次的报错，否则 LLM 无从修改
    assert "not_a_col" in calls[-1]


def test_gives_up_after_max_attempts(engine):
    """LLM 一直写危险 SQL，超过次数就放弃，不能死循环。"""
    def fake_llm(prompt: str) -> str:
        return "DROP TABLE products"

    tool = ExecuteTool(engine)
    loop = RetryLoop(fake_llm, tool.execute, max_attempts=2)
    r = loop.run("删库", _SCHEMA_PROMPT)

    assert not r.ok
    assert r.attempts_used == 2
    assert len(r.attempts) == 2
    assert all(not a.ok for a in r.attempts)
    assert r.error  # 要有失败原因可展示


def test_empty_llm_output_counts_as_failure(engine):
    def fake_llm(prompt: str) -> str:
        return ""

    tool = ExecuteTool(engine)
    loop = RetryLoop(fake_llm, tool.execute, max_attempts=2)
    r = loop.run("查商品", _SCHEMA_PROMPT)

    assert not r.ok
    assert r.attempts[0].error == "LLM 没有返回 SQL"


def test_extract_sql_cleans_common_mess():
    assert extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert extract_sql("sql SELECT 1") == "SELECT 1"
    assert extract_sql("SELECT 1; DROP TABLE x") == "SELECT 1"
    assert extract_sql("") == ""
