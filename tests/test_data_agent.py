"""DataAnalysisAgent 单元测试 —— 用 fake llm_chat + 真实 SQLite 引擎，不烧 API。"""
from __future__ import annotations

from app.agents.data_agent import DataAnalysisAgent
from app.core.llm import ChatResponse, ToolCall


class Scripted:
    """按脚本依次返回 ChatResponse 的假 LLM。"""

    def __init__(self, responses):
        self._q = list(responses)
        self.calls = []

    def __call__(self, messages, tools=None):
        self.calls.append(messages)
        return self._q.pop(0)


def test_tool_dispatch_and_final_answer(engine):
    scripted = Scripted([
        ChatResponse(content="", tool_calls=[
            ToolCall("c1", "run_sql", {
                "sql": "SELECT city, COUNT(*) AS n FROM customers GROUP BY city"
            })
        ]),
        ChatResponse(content="各城市客户数：北京2、上海1、广州1。"),
    ])
    agent = DataAnalysisAgent(engine, llm_chat=scripted, max_iterations=5)
    reply = agent.run("各城市各有多少客户？")
    assert reply.ok
    assert reply.trace, "应该记录工具调用"
    assert reply.trace[0][0] == "run_sql"
    assert "北京" in reply.text
    # run_sql 的结果确实进了记忆，模型第二轮能看到
    tool_msgs = [m for m in agent.memory.messages if m["role"] == "tool"]
    assert tool_msgs, "工具结果应写回记忆"
    assert "北京" in tool_msgs[0]["content"]


def test_guard_blocks_dangerous_sql(engine):
    scripted = Scripted([
        ChatResponse(content="", tool_calls=[
            ToolCall("c1", "run_sql", {"sql": "DROP TABLE customers"})
        ]),
        ChatResponse(content="已处理。"),
    ])
    agent = DataAnalysisAgent(engine, llm_chat=scripted, max_iterations=5)
    reply = agent.run("删掉 customers 表")
    tool_results = [t[2] for t in reply.trace]
    # 安全层应拦截，工具结果里出现拒绝原因，而不是执行成功
    assert any("不允许" in r or "失败" in r for r in tool_results)
    assert "已处理" in reply.text
    # 表依然存在（没真被执行）
    assert "customers" in SchemaTool_list(engine)


def SchemaTool_list(engine):
    from app.tools.schema_tool import SchemaTool
    return SchemaTool(engine).list_tables()


def test_memory_across_turns(engine):
    # 第一轮问北京，第二轮追问上海，记忆应跨轮保留
    scripted = Scripted([
        ChatResponse(content="", tool_calls=[
            ToolCall("c1", "run_sql", {"sql":
                "SELECT SUM(amount) FROM orders o JOIN customers c "
                "ON c.id=o.customer_id WHERE c.city='北京'"})
        ]),
        ChatResponse(content="北京客户共消费 4078。"),
        ChatResponse(content="", tool_calls=[
            ToolCall("c2", "run_sql", {"sql":
                "SELECT SUM(amount) FROM orders o JOIN customers c "
                "ON c.id=o.customer_id WHERE c.city='上海'"})
        ]),
        ChatResponse(content="上海客户共消费 5499。"),
    ])
    agent = DataAnalysisAgent(engine, llm_chat=scripted, max_iterations=5)
    r1 = agent.run("北京客户一共花了多少？")
    assert r1.ok
    r2 = agent.run("那上海呢？")
    assert r2.ok
    assert len([m for m in agent.memory.messages if m["role"] == "user"]) == 2
    assert len([t for t in r1.trace + r2.trace if t[0] == "run_sql"]) == 2


def test_max_iterations_guard(engine):
    # 模型一直要求调用工具，不停下来 -> 触发步数上限
    looping = ChatResponse(content="", tool_calls=[
        ToolCall("c", "run_sql", {"sql": "SELECT 1"})
    ])
    scripted = Scripted([looping] * 12)
    agent = DataAnalysisAgent(engine, llm_chat=scripted, max_iterations=5)
    reply = agent.run("一直查")
    assert not reply.ok
    assert len(reply.trace) >= 5  # 至少跑满上限


def test_inspect_schema_lists_tables(engine):
    scripted = Scripted([
        ChatResponse(content="", tool_calls=[ToolCall("c1", "inspect_schema", {})]),
        ChatResponse(content="库里有这些表。"),
    ])
    agent = DataAnalysisAgent(engine, llm_chat=scripted, max_iterations=5)
    reply = agent.run("有哪些表？")
    assert reply.ok
    tool_results = [t[2] for t in reply.trace]
    assert any("customers" in r for r in tool_results)


def test_custom_tool_can_be_injected(engine):
    # 验证工具是可注入的：用一个假的 inspect 工具，验证分发逻辑
    calls = []

    def fake_inspect(**kwargs):
        calls.append(kwargs)
        return "fake schema"

    from app.agents.data_agent import ToolSpec

    fake_tool = ToolSpec(
        "inspect_schema", "fake", {"type": "object", "properties": {}}, fake_inspect
    )
    scripted = Scripted([
        ChatResponse(content="", tool_calls=[ToolCall("c1", "inspect_schema", {})]),
        ChatResponse(content="done"),
    ])
    agent = DataAnalysisAgent(
        engine, llm_chat=scripted, max_iterations=5, tools=[fake_tool]
    )
    reply = agent.run("看结构")
    assert reply.ok
    assert calls == [{}]
    assert reply.trace[0][2] == "fake schema"
