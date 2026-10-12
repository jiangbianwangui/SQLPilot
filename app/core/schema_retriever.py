"""
轻量 schema 检索 —— 给 LLM 只喂「相关的表」，而不是整库。

为什么需要：
    真实业务库几十上百张表，全塞进 prompt 会撑爆上下文、也会让 LLM 选错表。
    先用规则打分挑出最可能相关的几张，再拼进 prompt。

为什么用规则打分而不是向量检索：
    - 零依赖、零成本、毫秒级，适合小库和 Demo；
    - 中文表名/注释靠分词不好切，这里用「2-gram + 注释匹配」，实测够用。
    局限：不理解「北京客户花了多少钱」里的隐含 join 关系。真实版本应换成
    向量召回 + 外键图扩展，这里先留出接口（select_tables）。

对外只暴露两个方法：select_tables() 和 build_prompt()。
"""

from __future__ import annotations

import re
from typing import Optional

from ..tools.schema_tool import SchemaTool, TableInfo

# 英文/数字按单词切，中文按连续串切
_ASCII_WORD = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")

# 数值型字段的类型关键字（用于聚合类问题的加权）
_NUMERIC_TYPES = ("int", "real", "decimal", "float", "double", "numeric", "number")

# 出现这些词说明用户在问统计，数值字段所在的表更可能是答案
AGG_HINTS = (
    "多少", "几个", "总额", "总共", "平均", "求和", "统计", "数量",
    "最大", "最小", "最高", "最低", "排名",
    "count", "sum", "avg", "max", "min", "total",
)


class SchemaRetriever:
    """根据自然语言问题挑选相关表。"""

    def __init__(self, schema: dict[str, TableInfo], top_k: int = 5) -> None:
        self.schema = schema
        self.top_k = top_k

    @classmethod
    def from_engine(cls, engine, top_k: int = 5) -> "SchemaRetriever":
        """直接从数据库引擎构建（内部用 SchemaTool 探查）。"""
        return cls(SchemaTool(engine).get_full_schema(), top_k=top_k)

    # ---------------- 对外接口 ----------------
    def select_tables(self, question: str, top_k: Optional[int] = None) -> list[str]:
        """返回与问题最相关的表名列表（按得分降序）。"""
        k = top_k or self.top_k
        terms = _question_terms(question)

        scored: list[tuple[int, str]] = []
        for name, info in self.schema.items():
            s = self._score(name, info, terms, question)
            if s > 0:
                scored.append((s, name))
        scored.sort(key=lambda x: (-x[0], x[1]))

        picked = [n for _, n in scored[:k]]
        if not picked:
            # 一个都没命中：退回前 k 张表。
            # 宁可多喂几张让 LLM 自己选，也不能一张不给导致它瞎编字段。
            picked = sorted(self.schema)[:k]
        return picked

    def build_prompt(self, question: str, top_k: Optional[int] = None) -> str:
        """拼出「只含相关表」的 schema，直接塞进 LLM prompt。"""
        names = self.select_tables(question, top_k)
        blocks = [self.schema[n].to_prompt() for n in names if n in self.schema]
        return "\n\n".join(blocks) if blocks else "（库中没有可查询的表）"

    # ---------------- 打分 ----------------
    def _score(self, name: str, info: TableInfo, terms: list[str], question: str) -> int:
        score = 0
        name_l = name.lower()
        comment = (info.comment or "").lower()

        for t in terms:
            if t in name_l:                       # 命中表名
                score += 3
            if comment and t in comment:          # 命中表注释（中文库最有价值）
                score += 5
            for c in info.columns:
                if t in c.name.lower():           # 命中字段名
                    score += 1
                if c.comment and t in c.comment.lower():   # 命中字段注释
                    score += 2

        # 聚合类问题：含数值字段的表额外加权
        lowered_q = question.lower()
        if any(h in lowered_q for h in AGG_HINTS):
            if any(any(nt in c.type.lower() for nt in _NUMERIC_TYPES) for c in info.columns):
                score += 2

        return score


def _question_terms(question: str) -> list[str]:
    """把问题切成匹配用的词元：英文按单词，中文按 2-gram。

    例："北京客户花了多少钱" -> ['北京','京客','客户','户花','花了','了多','多少','少钱']
    """
    q = (question or "").lower()
    raw: list[str] = list(_ASCII_WORD.findall(q))

    for run in _CJK_RUN.findall(q):
        if len(run) <= 4:
            raw.append(run)
        # 长句切 2-gram，才能命中「客户」「商品」这类词
        for i in range(len(run) - 1):
            raw.append(run[i : i + 2])

    seen: set[str] = set()
    out: list[str] = []
    for t in raw:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
