"""
只读 SQL 执行工具。

职责：
    拿到一条「已经过安全层校验」的 SQL，在只读连接上执行，
    把结果整理成结构化 dict 返回给 Agent；执行失败时把数据库
    底层错误归一化成中文提示，便于喂回 LLM 做自我修正。

为什么单独成层：
    - 执行必须走只读账号（见 sql/init_db.sql），
    - 强制 LIMIT 防止一次拉爆内存，
    - 错误信息归一化避免把原始报错直接抛给用户 / 暴露 schema 细节。

注意：本工具不负责「生成」SQL，也不负责「校验」SQL —— 校验在
sql_guard，生成在 Agent。三层职责分离，方便单测和面试讲清楚。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .sql_guard import validate_sql, ValidationResult

# 无论如何最多返回这么多行，保护内存与下游 token 预算
MAX_ROWS_HARD = 1000

# MySQL 常见错误码 -> 中文友好提示（保留原始报错在末尾供调试）
_MYSQL_ERROR_CN: dict[str, str] = {
    "1049": "数据库不存在",
    "1054": "查询中引用了不存在的字段",
    "1052": "字段有歧义，请给字段加上表名前缀（如 t.col）",
    "1064": "SQL 语法错误，请检查关键字拼写或引号",
    "1066": "表别名有重复，请改用不同别名",
    "1096": "缺少表名，SELECT 必须跟 FROM table",
    "1109": "查询中引用了不存在的表",
    "1111": "聚合函数使用不当（如 WHERE 里直接用了 COUNT）",
    "1136": "列数与 VALUES 不匹配（但本系统只支持查询，不应出现）",
    "1146": "数据表不存在，请核对表名",
    "1149": "SQL 语法错误",
    "1241": "子查询应只返回一列，但实际返回了多列",
    "1242": "子查询返回了多行，但上下文只接受单行",
    "1055": "SELECT 的字段不在 GROUP BY 中（ONLY_FULL_GROUP_BY）",
    "1050": "表已存在",
    "1142": "当前账号没有该操作的权限（本系统为只读账号）",
}


@dataclass
class QueryResult:
    """一次查询的结果"""

    ok: bool
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    error: str = ""                 # 中文友好错误（ok=False 时有效）
    error_code: Optional[str] = None  # 数据库原始错误码，如 "1054"


class ExecuteTool:
    """在给定 SQLAlchemy 引擎上执行只读查询。"""

    def __init__(self, engine, default_limit: int = 200) -> None:
        """
        Args:
            engine: 一个「只读账号」的 SQLAlchemy Engine（见 sql/init_db.sql）
            default_limit: 未显式 LIMIT 时自动追加的上限
        """
        self.engine = engine
        self.default_limit = default_limit

    def execute(self, sql: str, limit: Optional[int] = None) -> QueryResult:
        """执行一条（应该已校验过的）SQL，返回结构化结果。

        Args:
            sql: 原始 SQL
            limit: 本次查询的行数上限，不传用 default_limit，且不超过 MAX_ROWS_HARD
        """
        limit = min(limit or self.default_limit, MAX_ROWS_HARD)

        # 1) 安全层双保险：执行前再校验一次，绝不直接把 LLM 的 SQL 丢给连接
        res: ValidationResult = validate_sql(sql)
        if not res.ok:
            return QueryResult(False, sql=sql, error=res.reason)

        safe_sql = res.sql

        # 2) 强制 LIMIT，防止超大结果集拖垮服务
        try:
            safe_sql = self._ensure_limit(safe_sql, limit)
        except Exception:
            # 加 LIMIT 失败（极罕见）就退回原句，不阻断正常查询
            safe_sql = res.sql

        # 3) 执行 + 错误归一化
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(safe_sql))
                columns = list(result.keys())
                raw = result.fetchmany(limit) or []
                rows = [dict(zip(columns, tuple(r))) for r in raw]
            return QueryResult(
                True,
                sql=safe_sql,
                columns=columns,
                rows=rows,
                row_count=len(rows),
            )
        except (SQLAlchemyError, DBAPIError) as exc:
            code, msg = _normalize_error(exc)
            return QueryResult(False, sql=safe_sql, error=msg, error_code=code)

    # ============================================================
    # 内部方法
    # ============================================================
    def _ensure_limit(self, sql: str, limit: int) -> str:
        """如果 SQL 顶层没有 LIMIT，就补一个（用 sqlglot，兼容 UNION）。

        注意：必须用 Query.limit() 方法，而不是手动 set 一个 exp.Limit
        节点 —— 后者在本机 sqlglot 版本里会把 limit 值错误贴到上一个
        标识符上（如 `c.id200`）。
        """
        import sqlglot

        tree = sqlglot.parse_one(sql, read="mysql")
        if tree is None:
            return sql
        if getattr(tree, "args", {}).get("limit") is None:
            tree = tree.limit(limit)  # .limit() 返回新树，必须接住
        return tree.sql(dialect="mysql")


def _normalize_error(exc: Exception) -> tuple[Optional[str], str]:
    """把数据库异常归一化成 (错误码, 中文提示)。

    优先用 DBAPI 原始异常的 args：MySQL 里 args[0] 是整数错误码，
    args[1] 是原始英文信息。拿不到码就退回原始 str。
    """
    orig = getattr(exc, "orig", exc)
    code: Optional[str] = None
    raw_msg: str = str(exc).strip()

    args = getattr(orig, "args", None)
    if isinstance(args, tuple) and args:
        first = args[0]
        if isinstance(first, int):
            code = str(first)
            if len(args) > 1 and args[1]:
                raw_msg = str(args[1]).strip()
        elif first:
            raw_msg = str(first).strip()

    if code and code in _MYSQL_ERROR_CN:
        return code, f"{_MYSQL_ERROR_CN[code]}（错误码 {code}）"

    # 没有码或码不在映射里：保留原始信息，至少给用户一句提示
    if code:
        return code, f"数据库执行出错（错误码 {code}）：{raw_msg}"
    return None, f"数据库执行出错：{raw_msg}"
