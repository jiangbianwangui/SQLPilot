"""
数据库 schema 探查工具。

职责：
    给 Agent 提供「看库结构」的能力：有哪些表、每张表有哪些字段、
    字段类型和备注是什么。Agent 在生成 SQL 前必须先查 schema，避免
    猜字段名导致 1054（Unknown column）。

为什么用 SQLAlchemy inspector 而不是手写 information_schema 查询：
    - inspector 对 MySQL / SQLite / PostgreSQL 通用，本项目正式库是
      MySQL（inspector 底层就是读 information_schema），但单测可以用
      SQLite in-memory，不依赖 Docker。
    - 字段类型、 nullable、默认值的解析交给成熟库，少踩坑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import inspect
from sqlalchemy.engine import Engine


@dataclass
class ColumnInfo:
    """一张表的字段信息"""

    name: str
    type: str
    nullable: bool
    default: Optional[str] = None
    comment: Optional[str] = None

    def to_prompt(self) -> str:
        """生成给 LLM 看的一行字段描述"""
        bits = [f"{self.name} {self.type}"]
        bits.append("NULL" if self.nullable else "NOT NULL")
        if self.default is not None:
            bits.append(f"default={self.default}")
        if self.comment:
            bits.append(f"-- {self.comment}")
        return " ".join(bits)


@dataclass
class TableInfo:
    """一张表的完整信息"""

    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    comment: Optional[str] = None

    def to_prompt(self) -> str:
        head = f"表 {self.name}"
        if self.comment:
            head += f"（{self.comment}）"
        cols = "\n  - " + "\n  - ".join(c.to_prompt() for c in self.columns)
        return head + cols


class SchemaTool:
    """探查数据库结构。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_tables(self) -> list[str]:
        """返回所有用户表名（不含视图、系统表）。"""
        return inspect(self.engine).get_table_names()

    def get_table_schema(self, table: str) -> Optional[TableInfo]:
        """取单张表的结构；表不存在返回 None。"""
        inspector = inspect(self.engine)
        if table not in inspector.get_table_names():
            return None

        # 注释增强：优先用 engine.sqlpilot_comments 注入的中文注释。
        # SQLite 的 inspector 读不到表/列 COMMENT（演示库靠这里补），而 MySQL
        # 真实库自带 COMMENT，engine.sqlpilot_comments 里没有该 key，自动走下方 inspector 分支。
        injected = (getattr(self.engine, "sqlpilot_comments", None) or {}).get(table)
        tbl_comment_inject = (
            injected.get("table") if isinstance(injected, dict) else None
        )
        col_comments_inject = (
            injected.get("columns", {}) if isinstance(injected, dict) else {}
        )

        raw_cols = inspector.get_columns(table)
        columns = [
            ColumnInfo(
                name=c["name"],
                type=str(c["type"]),
                nullable=bool(c.get("nullable", True)),
                default=_safe_default(c.get("default")),
                comment=c.get("comment") or col_comments_inject.get(c["name"]) or None,
            )
            for c in raw_cols
        ]

        # 表级备注：MySQL 8 的 inspector 不直接给，这里宽容处理；
        # 演示库则用注入的注释兜底。
        comment = tbl_comment_inject
        if comment is None:
            try:
                table_comment = inspector.get_table_comment(table)
                comment = (table_comment or {}).get("text") or None
            except Exception:
                comment = None

        return TableInfo(name=table, columns=columns, comment=comment)

    def get_full_schema(self) -> dict[str, TableInfo]:
        """取全部表结构，便于一次性拼进 prompt。"""
        return {t: self.get_table_schema(t) for t in self.list_tables()}

    def to_prompt(self, tables: Optional[list[str]] = None) -> str:
        """把 schema 渲染成可直接塞进 LLM prompt 的文本。

        Args:
            tables: 只渲染指定表；为 None 渲染全部表。
        """
        names = tables if tables is not None else self.list_tables()
        blocks = []
        for name in names:
            info = self.get_table_schema(name)
            if info is not None:
                blocks.append(info.to_prompt())
        if not blocks:
            return "（库中没有可查询的表）"
        return "\n\n".join(blocks)


def _safe_default(value) -> Optional[str]:
    """default 可能是 sqlalchemy 的格式化对象，统一转成字符串。"""
    if value is None:
        return None
    return str(value)
