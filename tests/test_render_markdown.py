"""render_markdown 回归测试。

背景：把 render() 的终端文本直接塞进 gr.Markdown / gr.Chatbot 时，
Markdown 会把**单个换行**压成空格，整段结果挤成一整行（线上踩过）。
这里锁住契约：块与块之间必须是空行，SQL 必须包在代码块里，结果必须是表格。
"""
from __future__ import annotations

from app.agents.data_agent import AgentReply
from app.agents.sql_agent import Answer


def _sample_answer() -> Answer:
    return Answer(
        ok=True,
        question="北京客户一共花了多少钱",
        sql="SELECT c.name, SUM(o.amount) AS total FROM orders o",
        rows=[
            {"name": "王五", "total": 8999.0},
            {"name": "李四", "total": 5499.0},
        ],
        columns=["name", "total"],
        tables=["customers", "orders"],
        elapsed=0.34,
    )


def test_answer_markdown_uses_blank_lines_between_blocks():
    md = _sample_answer().render_markdown()
    # 关键：必须有空行分段，否则 Markdown 会压成一整行
    assert md.count("\n\n") >= 3
    assert "**问题**：北京客户一共花了多少钱" in md


def test_answer_markdown_renders_table_and_sql_fence():
    md = _sample_answer().render_markdown()
    assert "| name | total |" in md
    assert "| --- | --- |" in md
    assert "| 王五 | 8999.0 |" in md
    assert "```sql" in md and md.count("```") == 2
    assert "SELECT c.name" in md


def test_answer_markdown_has_summary_line():
    md = _sample_answer().render_markdown()
    assert "**结论**" in md
    assert "共返回 **2** 行" in md


def test_answer_markdown_failure_branch():
    md = Answer(ok=False, question="q", error="no such column: x", elapsed=0.2).render_markdown()
    assert "查询失败" in md
    assert "no such column: x" in md
    assert "\n\n" in md


def test_agent_reply_markdown_separates_trace_and_answer():
    reply = AgentReply(
        ok=True,
        text="消费最高的是张三",
        trace=[("run_sql", {"sql": "SELECT 1"}, "name|total\n张三|4078")],
    )
    md = reply.render_markdown()
    assert "**推理过程**" in md
    assert "**回答**" in md
    assert "消费最高的是张三" in md
    assert "\n\n" in md


def test_agent_reply_truncates_long_tool_args():
    long_sql = "SELECT " + "a, " * 100 + "b FROM t"
    reply = AgentReply(ok=True, text="ok", trace=[("run_sql", {"sql": long_sql}, "r")])
    md = reply.render_markdown()
    # 长参数必须截断，否则整条 SQL 会把界面撑爆
    assert "…" in md
    assert long_sql not in md
