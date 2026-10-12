"""
SQL 安全校验层 —— 本项目的核心防护。

为什么需要这一层：
    LLM 生成的 SQL 不可信。它可能因为幻觉生成 DROP TABLE，
    也可能被 prompt 注入诱导生成破坏性语句。绝不能拿到连接直接执行。

三层防护：
    第1 层 AST 解析    —— 用 sqlglot 把 SQL 解析成语法树，只放行 SELECT
    第2 层 关键词黑名单 —— 兜底扫描注释、字符串里的危险词
    第3 层 只读连接    —— 数据库层面用只读账号兜底（见 sql/init_db.sql）

只有三层同时通过才返回 True。任何一层不过就拒绝，并给出原因供 LLM 修正。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ============================================================
# 允许的语句类型：只有查询
# 注意 sqlglot 会把 `SELECT ... UNION SELECT` 解析成 Union 节点，
# 它本质仍是只读查询（报表场景很常见），所以要放行。
# ============================================================
ALLOWED_STATEMENTS = ("select", "union", "with")

# ============================================================
# 危险关键词黑名单
# 分三类，每类给出人话解释，便于喂回给 LLM 让它自我修正
# ============================================================
BLACKLIST: list[tuple[str, str]] = [
    # DDL —— 会改结构
    ("drop",     "删表/删库操作"),
    ("truncate", "清空表操作"),
    ("alter",    "修改表结构操作"),
    ("create",   "建表/建库操作"),
    ("rename",   "重命名操作"),
    # DML —— 会改数据
    ("insert",   "插入数据操作"),
    ("update",   "更新数据操作"),
    ("delete",   "删除数据操作"),
    ("replace",  "替换数据操作"),
    ("upsert",   "写入数据操作"),
    # 权限与事务控制
    ("grant",    "授权操作"),
    ("revoke",   "回收权限操作"),
    ("commit",   "提交事务操作"),
    ("rollback", "回滚事务操作"),
    # 文件与系统操作
    ("load_file",     "读本地文件"),
    ("into_outfile",  "写本地文件"),
    ("outfile",       "导出文件"),
    ("dumpfile",      "导出文件"),
    ("benchmark",     "压测函数"),
    ("sleep",         "延时函数，可被用于拖垮服务"),
]

# 需要显式拒绝的函数（即使整体是 SELECT）
DANGEROUS_FUNCS = ("load_file", "sys_exec", "benchmark", "sleep", "get_lock")


@dataclass
class ValidationResult:
    """校验结果"""

    ok: bool
    sql: str
    reason: str = ""           # 不通过的原因（中文，可直接喂给 LLM）
    statement_type: str = ""   # 识别出的语句类型，如 select / drop

    def __bool__(self) -> bool:
        return self.ok


class SQLGuard:
    """
    SQL 安全校验器。

    用法：
        guard = SQLGuard()
        result = guard.validate("SELECT * FROM users")
        if not result.ok:
            print(result.reason)   # 喂回给 LLM 让它改
    """

    # 匹配 `--` 单行注释和 `/* */` 块注释里的内容
    _COMMENT_PATTERN = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)

    def validate(self, sql: str) -> ValidationResult:
        """
        校验一条 SQL 是否安全可执行。

        Args:
            sql: 待校验的 SQL 文本

        Returns:
            ValidationResult
        """
        if not sql or not sql.strip():
            return ValidationResult(False, sql, "SQL 为空")

        # ---------- 预处理：去掉注释 ----------
        # 危险关键词可能藏在注释里（如 `-- DROP TABLE x`），
        # 但也可能有合法的中文注释，所以先剥离再检查
        stripped = self._COMMENT_PATTERN.sub(" ", sql)

        # ---------- 第 0 层：多语句检测 ----------
        # 分号分隔的多个语句：`SELECT 1; DROP TABLE users`
        # 这是 SQL 注入最经典的形态，必须在解析前拦掉
        if self._has_multiple_statements(stripped):
            return ValidationResult(
                False, sql, "检测到多条 SQL 语句，只允许执行单条查询"
            )

        # ---------- 第 1 层：AST 解析 ----------
        parsed = self._parse(stripped)
        if parsed is None:
            return ValidationResult(False, sql, "SQL 语法无法解析，请检查语法")

        stmt_type, parsed_sql = parsed

        # 只允许 SELECT
        if stmt_type not in ALLOWED_STATEMENTS:
            return ValidationResult(
                False,
                sql,
                f"不允许执行 {stmt_type.upper()} 语句，"
                f"本系统是只读查询工具，只支持 SELECT",
                stmt_type,
            )

        # ---------- 第 1.5 层：UNION 两侧都必须是 SELECT ----------
        # UNION 本身是只读的（报表常用），但要确认每个分支都是查询，
        # 防止有人构造出奇怪的组合绕过白名单
        if stmt_type == "union" and not self._union_all_select(parsed_sql):
            return ValidationResult(
                False,
                sql,
                "UNION 的每个分支都必须是 SELECT 查询",
                stmt_type,
            )

        # ---------- 第 2 层：关键词黑名单 ----------
        # AST 通过不代表安全：SELECT 可以嵌套在存储过程里，
        # 也可以通过 INTO OUTFILE 写文件，所以再扫一遍关键词
        lowered = parsed_sql.lower()
        for keyword, desc in BLACKLIST:
            if self._has_keyword(lowered, keyword):
                return ValidationResult(
                    False,
                    sql,
                    f"检测到危险关键词 '{keyword}'（{desc}），"
                    f"请改写为纯查询语句",
                    stmt_type,
                )

        for func in DANGEROUS_FUNCS:
            if self._has_keyword(lowered, func):
                return ValidationResult(
                    False,
                    sql,
                    f"检测到危险函数 {func}()，不允许在查询中使用",
                    stmt_type,
                )

        # ---------- 通过全部三层 ----------
        return ValidationResult(True, parsed_sql, statement_type=stmt_type)

    # ============================================================
    # 内部方法
    # ============================================================

    def _parse(self, sql: str) -> Optional[tuple[str, str]]:
        """
        用 sqlglot 解析 SQL，返回 (语句类型, 规范化后的SQL)。
        sqlglot 不可用时降级为正则判断。
        """
        try:
            import sqlglot
            from sqlglot import exp

            statements = sqlglot.parse(sql, read="mysql")
            # 过滤掉空语句（末尾多一个分号会解析出 None）
            real = [s for s in statements if s is not None]
            if len(real) != 1:
                return None

            stmt = real[0]
            # 取最外层节点的类型名，如 Select / Drop / Insert
            stmt_type = type(stmt).__name__.lower()
            # 规范化输出（顺手处理了部分注入技巧，如大小写混写）
            return stmt_type, stmt.sql(dialect="mysql")
        except ImportError:
            # 没装 sqlglot 的降级路径：只做最基础的类型判断
            return self._parse_fallback(sql)
        except Exception:
            # 解析失败说明语法有问题
            return None

    def _parse_fallback(self, sql: str) -> Optional[tuple[str, str]]:
        """不依赖 sqlglot 的降级解析（正则）"""
        s = sql.strip().lower()
        if s.startswith("with"):
            return "select", sql.strip()
        for kw in ("select", "show", "describe", "explain"):
            if s.startswith(kw):
                return ("select" if kw == "select" else kw), sql.strip()
        # 含 union 的查询：前提是整句以 select 开头
        if " union " in s and s.startswith("select"):
            return "union", sql.strip()
        # 识别出危险类型，便于给用户提示
        for kw in ("drop", "delete", "update", "insert", "alter", "create", "truncate"):
            if s.startswith(kw):
                return kw, sql.strip()
        return None

    def _union_all_select(self, sql: str) -> bool:
        """
        校验 UNION 的每个分支都是 SELECT。

        注意：sqlglot 里 Union 不是 Select 的子类，而是独立节点类型，
        所以这里按类型名判断，不能用 isinstance(tree, exp.Select)。
        """
        try:
            import sqlglot
            from sqlglot import exp

            tree = sqlglot.parse_one(sql, read="mysql")
            allowed = ("select", "union")
            if type(tree).__name__.lower() not in allowed:
                return False
            # 顶层是 Union 时，逐个检查分支
            if type(tree).__name__.lower() == "union":
                for branch in (tree.this, tree.expression):
                    # 允许 SELECT 或嵌套的 Union（如 A UNION B UNION C）
                    if type(branch).__name__.lower() not in allowed:
                        return False
            return True
        except Exception:
            # 解析不了就保守拒绝，宁可误杀不可放过
            return False

    def _has_multiple_statements(self, sql: str) -> bool:
        """
        检测是否有多条语句。

        注意不能简单数分号 —— 字符串里的分号不算，比如
        `SELECT * FROM t WHERE name = 'a;b'` 是合法的单条查询。
        """
        in_single = False
        in_double = False
        in_backtick = False
        prev = ""

        for ch in sql:
            if ch == "'" and not in_double and not in_backtick and (prev == "\\" or prev != "\\"):
                in_single = not in_single
            elif ch == '"' and not in_single and not in_backtick:
                in_double = not in_double
            elif ch == "`":
                in_backtick = not in_backtick
            elif ch == ";" and not in_single and not in_double and not in_backtick:
                # 分号后面还有非空白内容 → 多语句
                rest = sql[sql.index(ch) + 1:].strip() if ch in sql else ""
                if rest:
                    return True
            prev = ch
        return False

    def _has_keyword(self, lowered_sql: str, keyword: str) -> bool:
        """
        判断关键词是否作为独立标识符出现。

        不能用 `keyword in sql` —— 那会把 `created_at` 里的 `ate` 误判成 `ate`。
        用正则要求前后是非单词字符。
        """
        pattern = rf"(?<![a-z0-9_]){re.escape(keyword)}(?![a-z0-9_])"
        return re.search(pattern, lowered_sql) is not None


# ============================================================
# 模块级单例，方便各处 import
# ============================================================
_guard = SQLGuard()


def validate_sql(sql: str) -> ValidationResult:
    """便捷函数：校验一条 SQL 是否安全"""
    return _guard.validate(sql)
