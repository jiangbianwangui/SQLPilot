"""
错误自修复循环 —— SQLPilot 相对社区 DatabaseAgent 的核心差异点之一。

思路：
    LLM 第一次写的 SQL 经常是错的（字段名幻觉、语法笔误、聚合写错）。
    与其直接报错，不如把「数据库原始报错」原样喂回 LLM，让它自己改，
    最多重试 N 次。这就是 Agent 相比纯 prompt 的价值：闭环反馈。

设计要点：
    - LLM 和 执行器 都是「注入」的（可调用对象），所以单测不需要真 API、
      不需要真数据库，fake 一个函数就能测完整的重试行为。
    - 每次尝试都记进 attempts，方便 demo 时展示「第一次错了、第二次改对」。

对外只暴露：RetryLoop.run() 和 extract_sql()。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..tools.execute_tool import QueryResult

# 匹配 ```sql ... ``` 代码块
_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.S | re.I)

INITIAL_TEMPLATE = """你是一个 MySQL 只读查询助手。根据下面的数据库结构，把用户的问题写成一条 SQL。

要求：
- 只输出一条 SQL，不要解释
- 只能是 SELECT 查询，禁止任何写操作
- 字段名必须来自下面的表结构，不要臆造

【数据库结构】
{schema}

【用户问题】
{question}
"""

REPAIR_TEMPLATE = """你上一次写的 SQL 执行失败了。请修正后重新输出一条 SQL。

【数据库结构】
{schema}

【用户问题】
{question}

【上一次的 SQL】
{sql}

【数据库报错】
{error}

要求：只输出修正后的 SQL，不要解释。
"""


@dataclass
class Attempt:
    """一次尝试的记录"""

    index: int          # 第几次（从 1 开始）
    sql: str = ""       # 这次生成的 SQL
    ok: bool = False    # 是否执行成功
    error: str = ""     # 失败原因（成功时为空）


@dataclass
class RetryResult:
    """整个循环的最终结果"""

    ok: bool
    sql: str = ""
    result: Optional[QueryResult] = None
    attempts: list[Attempt] = field(default_factory=list)
    attempts_used: int = 0

    @property
    def rows(self) -> list[dict]:
        return self.result.rows if self.result else []

    @property
    def error(self) -> str:
        """最终失败原因（取最后一次）"""
        return self.attempts[-1].error if self.attempts else ""


class RetryLoop:
    """生成 → 执行 → 失败就喂回 LLM 重生成，直到成功或用完次数。"""

    def __init__(
        self,
        llm_generate: Callable[[str], str],
        execute_fn: Callable[[str], QueryResult],
        max_attempts: int = 3,
    ) -> None:
        """
        Args:
            llm_generate: 输入 prompt，返回 LLM 原始文本
            execute_fn:   输入 SQL，返回 QueryResult（一般是 ExecuteTool.execute）
            max_attempts: 最多重试几次
        """
        self.llm_generate = llm_generate
        self.execute_fn = execute_fn
        self.max_attempts = max_attempts

    def run(self, question: str, schema_prompt: str) -> RetryResult:
        attempts: list[Attempt] = []
        last_sql = ""
        prompt = INITIAL_TEMPLATE.format(schema=schema_prompt, question=question)

        for i in range(1, self.max_attempts + 1):
            raw = self.llm_generate(prompt) or ""
            sql = extract_sql(raw)

            if not sql:
                # LLM 啥也没返回，也算一次失败，把「没返回」当成报错喂回去
                attempts.append(Attempt(i, "", False, "LLM 没有返回 SQL"))
                prompt = REPAIR_TEMPLATE.format(
                    schema=schema_prompt,
                    question=question,
                    sql="(空)",
                    error="上一次没有返回任何 SQL，请直接输出一条 SELECT",
                )
                continue

            last_sql = sql
            r = self.execute_fn(sql)

            if r.ok:
                attempts.append(Attempt(i, sql, True))
                return RetryResult(True, sql, r, attempts, i)

            # 失败：把报错原样喂回去，让 LLM 自己修
            attempts.append(Attempt(i, sql, False, r.error))
            prompt = REPAIR_TEMPLATE.format(
                schema=schema_prompt, question=question, sql=sql, error=r.error
            )

        return RetryResult(False, last_sql, None, attempts, self.max_attempts)


def extract_sql(text: str) -> str:
    """从 LLM 输出里抠出干净的一条 SQL。

    处理三种常见脏输出：
        ```sql\nSELECT 1\n```   -> SELECT 1
        sql SELECT 1            -> SELECT 1
        SELECT 1; DROP TABLE x  -> SELECT 1   （只取第一条，防顺手多写）
    """
    s = (text or "").strip()

    m = _FENCE.search(s)
    if m:
        s = m.group(1).strip()

    # 去掉行首的 "SQL" 标记
    s = re.sub(r"^sql\b\s*", "", s, flags=re.I).strip()

    # 只取第一条语句
    return s.split(";")[0].strip()
