"""
SQLPilot 主 Agent —— 把「选表 → 生成 → 执行 → 出错自修复」串成一条闭环。

这就是「agent」和「一把函数」的区别：
    输入一句自然语言，Agent 自己决定看哪些表、自己写 SQL，
    写错了自己根据数据库报错改，直到能跑出结果为止。

分层（每层都能单独替换 / 单测）：
    SchemaRetriever  选表        —— 只把相关表喂给 LLM
    RetryLoop        生成+自修复 —— LLM 与执行器都是注入的
    ExecuteTool      执行       —— 只读 + 强制 LIMIT + 错误归一化
    llm_generate     大模型     —— app/core/llm.py，可换 DeepSeek/Ollama
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..core.retry_loop import Attempt, RetryLoop, RetryResult
from ..core.schema_retriever import SchemaRetriever
from ..tools.execute_tool import ExecuteTool


@dataclass
class Answer:
    """一次自然语言提问的完整回答（含过程，方便演示与排错）。"""

    ok: bool
    question: str
    sql: str = ""
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)     # 选中的表
    attempts: list[Attempt] = field(default_factory=list)  # 每次尝试的记录
    error: str = ""
    elapsed: float = 0.0

    def render(self) -> str:
        """渲染成命令行/终端里好看的结果。"""
        lines = []
        lines.append(f"问题: {self.question}")
        lines.append(f"选中表: {', '.join(self.tables) or '(无)'}")
        lines.append("尝试过程:")
        for a in self.attempts:
            mark = "OK  " if a.ok else "失败"
            lines.append(f"  第{a.index}次 [{mark}] {a.sql}")
            if not a.ok and a.error:
                lines.append(f"         -> {a.error}")
        if self.ok:
            lines.append("结果:")
            lines.append(f"  SQL: {self.sql}")
            if self.rows:
                lines.append("  " + " | ".join(self.columns))
                for r in self.rows:
                    lines.append("  " + " | ".join(str(v) for v in r.values()))
            else:
                lines.append("  (无数据)")
        else:
            lines.append(f"失败: {self.error}")
        lines.append(f"耗时: {self.elapsed:.2f}s")
        return "\n".join(lines)


class SQLAgent:
    """自然语言 → SQL → 结果 的闭环 Agent。"""

    def __init__(
        self,
        engine,
        llm_generate: Callable[[str], str],
        top_k: int = 5,
        max_attempts: int = 3,
    ) -> None:
        """
        Args:
            engine:        SQLAlchemy 引擎（正式环境应是 MySQL 只读账号）
            llm_generate:  输入 prompt 返回文本，交给 RetryLoop 用
            top_k:         选表时最多喂几张表
            max_attempts:  SQL 最多重试几次
        """
        self.retriever = SchemaRetriever.from_engine(engine, top_k=top_k)
        self.executor = ExecuteTool(engine)
        self.loop = RetryLoop(
            llm_generate=llm_generate,
            execute_fn=self.executor.execute,
            max_attempts=max_attempts,
        )

    def ask(self, question: str) -> Answer:
        """问一句，返回完整回答（含选表、SQL、重试过程）。"""
        start = time.time()

        tables = self.retriever.select_tables(question)
        schema_prompt = self.retriever.build_prompt(question)

        r: RetryResult = self.loop.run(question, schema_prompt)

        return Answer(
            ok=r.ok,
            question=question,
            sql=r.sql,
            rows=r.rows,
            columns=r.result.columns if r.result else [],
            tables=tables,
            attempts=r.attempts,
            error=r.error,
            elapsed=time.time() - start,
        )
