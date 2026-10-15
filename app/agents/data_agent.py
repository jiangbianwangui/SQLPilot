"""
多步数据分析 Agent —— 把 SQLPilot 的单步查询升级成「真正会思考」的 Agent。

和 SQLAgent（单步：一问一 SQL 一结果）的区别：
    - 工具调用（Tool Calling）：模型自己决定什么时候查表结构、什么时候跑 SQL、
      什么时候诊断慢查询、什么时候出图，而不是写死的一条流水线。
    - 会话记忆（Memory）：记住上一轮提到的表 / 时间范围 / 上下文，支持追问。
    - 反思-重规划（Reflection）：拿到执行结果后，模型自己判断是继续、换 SQL、
      澄清歧义还是收尾回答——这才是 Agent 相对「一把函数」的价值。

安全不打折：
    run_sql 工具底层就是 ExecuteTool —— 三层校验 + 只读账号 + 强制 LIMIT 全部复用，
    模型就算想写 DROP 也会被安全层拦下，和单步引擎是同一套防护。

设计哲学（沿用项目一贯风格）：
    - LLM 接口（llm_chat）和工具都是「注入」的，单测用 fake 即可，无需真 API / 真库。
    - 每个工具职责单一：inspect_schema 看结构、run_sql 取数、diagnose 诊断、plot 出图。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..tools.diagnose_tool import DiagnoseTool, render as render_diagnosis
from ..tools.execute_tool import ExecuteTool
from ..tools.schema_tool import SchemaTool


SYSTEM_PROMPT = """你是一个数据库数据分析助手，帮助用户用自然语言从业务库里取数和分析。

你能使用的工具有：
- inspect_schema：看数据库有哪些表、字段结构（先搞清楚结构再写 SQL）
- run_sql：执行一条只读 SELECT 查询取数（写操作会被安全层拦截，不要尝试）
- diagnose：分析某条查询的执行计划，检测全表扫描并建议建索引
- plot：把查询结果画成图表（需要 x/y 字段）

工作准则：
1. 不确定字段名或表结构时，先调用 inspect_schema，不要凭空猜字段。
2. 拿到数据后再回答，回答里要引用真实数字；没查到就说没查到。
3. 用户问题有歧义（如没说时间范围、城市）时，直接提问澄清，或给出合理默认并说明。
4. 如果某次 run_sql 报错，根据错误信息自行改写 SQL 再试。
5. 所有取数都必须通过 run_sql，禁止在回答里编造数据。
"""


@dataclass
class ToolSpec:
    """一个可被模型调用的工具。"""

    name: str
    description: str
    parameters: dict          # JSON Schema
    call: Callable[..., str]  # 实际执行，返回给模型的文本


@dataclass
class AgentReply:
    """一次多轮对话的最终回答（含过程，便于演示与排错）。"""

    ok: bool
    text: str
    trace: list = field(default_factory=list)   # [(tool_name, args, result), ...]

    def render(self) -> str:
        lines = []
        if self.trace:
            lines.append("【推理过程】")
            for i, (name, args, result) in enumerate(self.trace, 1):
                a = ", ".join(f"{k}={v}" for k, v in (args or {}).items())
                lines.append(f"  {i}. 调用 {name}({a})")
                for rline in str(result).splitlines()[:6]:
                    lines.append(f"       ↳ {rline}")
        lines.append("【回答】")
        lines.append(self.text)
        return "\n".join(lines)


class Memory:
    """会话级记忆：存 OpenAI 格式的消息列表。"""

    def __init__(self, system_prompt: str = "") -> None:
        self._system = {"role": "system", "content": system_prompt}
        self._msgs: list[dict] = [self._system] if system_prompt else []

    def add(
        self,
        role: str,
        content: Optional[str] = None,
        tool_calls=None,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        m: dict = {"role": role}
        if content is not None:
            m["content"] = content
        if tool_calls is not None:
            m["tool_calls"] = tool_calls
        if tool_call_id is not None:
            m["tool_call_id"] = tool_call_id
        if name is not None:
            m["name"] = name
        self._msgs.append(m)

    @property
    def messages(self) -> list[dict]:
        return self._msgs

    def reset(self) -> None:
        self._msgs = [self._system] if self._system.get("content") else []


class DataAnalysisAgent:
    """多步数据分析 Agent（ReAct 风格的工具调用循环 + 会话记忆）。"""

    def __init__(
        self,
        engine,
        llm_chat: Callable,
        tools: Optional[list[ToolSpec]] = None,
        max_iterations: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        """
        Args:
            engine:        SQLAlchemy 引擎（正式环境应是 MySQL 只读账号）
            llm_chat:      输入 (messages, tools) 返回 ChatResponse，注入以便单测
            tools:         自定义工具列表；不传则用基于 engine 的默认工具集
            max_iterations: 单轮最多推理步数（防止模型死循环调工具）
        """
        self.engine = engine
        self.llm_chat = llm_chat
        self.max_iterations = max_iterations
        self.memory = Memory(system_prompt)
        self.tools = {t.name: t for t in (tools or self._default_tools(engine))}

    # ---------------- 对外接口 ----------------
    def run(self, user_msg: str) -> AgentReply:
        """处理一句用户输入（可多轮连续调用，记忆跨轮保留）。"""
        self.memory.add("user", content=user_msg)
        trace: list = []

        for _ in range(self.max_iterations):
            resp = self.llm_chat(self.memory.messages, self._tool_schemas())
            if resp.tool_calls:
                # 把模型的「我要调用这些工具」记进历史，再逐个执行并把结果喂回
                self.memory.add(
                    "assistant",
                    content=resp.content or "",
                    tool_calls=[tc.to_openai() for tc in resp.tool_calls],
                )
                for tc in resp.tool_calls:
                    result = self._dispatch(tc)
                    trace.append((tc.name, tc.arguments, result))
                    self.memory.add(
                        "tool", content=result, tool_call_id=tc.id, name=tc.name
                    )
                continue
            # 没有工具调用 = 最终回答
            self.memory.add("assistant", content=resp.content)
            return AgentReply(ok=True, text=resp.content, trace=trace)

        msg = "已达到最大推理步数，请尝试把问题拆得更具体一些，或明确指出要看哪些表。"
        self.memory.add("assistant", content=msg)
        return AgentReply(ok=False, text=msg, trace=trace)

    def reset(self) -> None:
        """清空会话记忆（开始新一轮独立对话）。"""
        self.memory.reset()

    # ---------------- 内部 ----------------
    def _tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self.tools.values()
        ]

    def _dispatch(self, tc) -> str:
        spec = self.tools.get(tc.name)
        if spec is None:
            return f"未知工具: {tc.name}"
        try:
            return spec.call(**(tc.arguments or {}))
        except Exception as e:  # 工具崩了也不能让整个 Agent 挂掉
            return f"工具执行出错: {e}"

    @staticmethod
    def _default_tools(engine) -> list[ToolSpec]:
        schema_tool = SchemaTool(engine)
        exec_tool = ExecuteTool(engine)
        diag_tool = DiagnoseTool(engine)

        def inspect(**kwargs):
            tables = kwargs.get("tables") or []
            if not tables:
                return "可用表: " + ", ".join(schema_tool.list_tables())
            return schema_tool.to_prompt(tables)

        def run_sql(**kwargs):
            r = exec_tool.execute(kwargs.get("sql", ""))
            if not r.ok:
                return f"查询失败: {r.error}"
            if not r.rows:
                return "查询成功，但没有返回任何数据。"
            head = " | ".join(r.columns)
            lines = [head]
            for row in r.rows[:50]:
                lines.append(" | ".join(str(v) for v in row.values()))
            if r.row_count >= 50:
                lines.append("（仅显示前 50 行）")
            return "\n".join(lines)

        def diagnose(**kwargs):
            return render_diagnosis(diag_tool.diagnose(kwargs.get("sql", "")))

        def plot(**kwargs):
            try:
                import base64
                import io
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
            except Exception as e:
                return f"（绘图功能不可用：{e}；请检查是否安装 matplotlib）"
            r = exec_tool.execute(kwargs.get("sql", ""))
            if not r.ok:
                return f"查询失败: {r.error}"
            if not r.rows:
                return "查询无数据，无法绘图。"
            x, y, kind = kwargs.get("x"), kwargs.get("y"), kwargs.get("kind", "bar")
            if not x or not y:
                return "绘图需要提供 x 和 y 字段名。"
            xs = [str(row.get(x, "")) for row in r.rows]
            ys = [float(row.get(y) or 0) for row in r.rows]
            fig, ax = plt.subplots()
            if kind == "line":
                ax.plot(xs, ys)
            else:
                ax.bar(xs, ys)
            ax.set_xlabel(x)
            ax.set_ylabel(y)
            ax.tick_params(axis="x", rotation=45)
            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png")
            plt.close(fig)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"![chart](data:image/png;base64,{b64})\n（已生成{kind}图：x={x}, y={y}）"

        return [
            ToolSpec(
                "inspect_schema",
                "查看数据库表结构。传入 tables 指定要看的表名列表；不传则只列出全部表名。",
                {
                    "type": "object",
                    "properties": {
                        "tables": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要看结构的表名；为空则只列出全部表名",
                        }
                    },
                    "required": [],
                },
                inspect,
            ),
            ToolSpec(
                "run_sql",
                "执行一条只读 SELECT 查询并返回结果。写操作（INSERT/UPDATE/DELETE/DROP 等）会被安全层拦截，不要尝试。",
                {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "一条 SELECT SQL"}
                    },
                    "required": ["sql"],
                },
                run_sql,
            ),
            ToolSpec(
                "diagnose",
                "分析一条 SELECT 查询的执行计划，检测全表扫描并建议建索引。",
                {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "待诊断的 SELECT SQL"}
                    },
                    "required": ["sql"],
                },
                diagnose,
            ),
            ToolSpec(
                "plot",
                "把查询结果画成图表。直接传 SQL + x/y 字段名；需要 matplotlib，未安装会提示。",
                {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "取数 SQL"},
                        "x": {"type": "string", "description": "横轴字段"},
                        "y": {"type": "string", "description": "纵轴字段"},
                        "kind": {
                            "type": "string",
                            "enum": ["bar", "line"],
                            "description": "图表类型，默认 bar",
                        },
                    },
                    "required": ["sql", "x", "y"],
                },
                plot,
            ),
        ]
