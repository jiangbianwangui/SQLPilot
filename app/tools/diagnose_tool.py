"""
慢查询诊断工具（阶段 3 的核心差异化功能）—— 逻辑由你来完成。

要解决的问题：
    用户问「这条查询为什么慢」，本工具用数据库自己的 EXPLAIN 看一下执行计划，
    判断有没有全表扫描（SCAN），有就建议加索引。

已知的坑（别踩）：
    - SQLite 用 `EXPLAIN QUERY PLAN`，MySQL 用 `EXPLAIN`，本文件先做 SQLite 版
    - EXPLAIN 只能跑 SELECT，所以必须先过 sql_guard 校验
    - 诊断结果里 "SCAN xxx" 表示全表扫描，"SEARCH xxx USING INDEX" 表示走了索引

已搭好的部分：数据结构、字段、提示文案。你只需要填三个 TODO。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Diagnosis:
    """一条 SQL 的诊断结论"""

    sql: str
    ok: bool = False                  # 诊断是否成功
    has_full_scan: bool = False       # 是否存在全表扫描
    scanned_tables: set[str] = field(default_factory=set)     # 被全表扫描的表
    suggestions: list[str] = field(default_factory=list)      # 给人看的建议
    plan: list[str] = field(default_factory=list)             # 原始执行计划（便于展示）
    error: str = ""                   # 失败原因


class DiagnoseTool:
    """用 EXPLAIN 分析一条查询的执行计划。"""

    def __init__(self, engine) -> None:
        self.engine = engine

    def diagnose(self, sql: str) -> Diagnosis:
        """诊断一条 SQL。返回 Diagnosis。

        三个 TODO 就是你要写的全部内容。
        """
        d = Diagnosis(sql=sql)

        # ---------- TODO 1：安全校验 ----------
        # 要求：调用 app.tools.sql_guard 的 validate_sql(sql)
        #   - 校验不通过（result.ok 为 False）时，把 result.reason 填进 d.error，
        #     直接 return d（不要去执行危险 SQL）
        #   - 校验通过则继续，用 result.sql（规范化后的 SQL）往下走
        #
        # 提示：先在文件顶部 `from app.tools.sql_guard import validate_sql`
        from app.tools.sql_guard import validate_sql
        result = validate_sql(sql)
        if not result.ok:
            d.error = result.reason
            return d
        else:
            sql = result.sql




        # ---------- TODO 2：跑 EXPLAIN（按方言分支）----------
        # SQLite 用 `EXPLAIN QUERY PLAN`；MySQL 用 `EXPLAIN`（无 QUERY PLAN 后缀）
        from sqlalchemy import text
        dialect = self.engine.dialect.name  # 'sqlite' 或 'mysql'
        try:
            with self.engine.connect() as conn:
                if dialect == 'sqlite':
                    rows = conn.execute(
                        text(f"EXPLAIN QUERY PLAN {sql}")).fetchall()
                    d.plan = [r[-1] for r in rows]  # 取最后一列可读文本
                else:  # mysql
                    rows = conn.execute(text(f"EXPLAIN {sql}")).fetchall()
        except Exception as e:
            d.error = str(e)
            return d

        # ---------- TODO 3：判断全表扫描并给建议（按方言分支）----------
        d.scanned_tables = set()
        if dialect == 'sqlite':
            for line in d.plan:
                if "USING INDEX" in line:
                    continue
                if "SCAN" in line:
                    parts = line.split()
                    table_name = parts[parts.index("SCAN") + 1]
                    d.scanned_tables.add(table_name)
                    d.suggestions.append(f"建议为 {table_name} 表的相关字段建索引")
        else:  # mysql
            # rows 是 12 列元组：id, select_type, table, partitions, type,
            # possible_keys, key, key_len, ref, rows, filtered, Extra
            # 全表扫描 = type=='ALL' 且 key 为 None；表名在 row[2]
            for row in rows:
                r = list(row)
                if r[4] == 'ALL' and r[6] is None:
                    table_name = r[2]
                    d.scanned_tables.add(table_name)
                    d.suggestions.append(f"建议为 {table_name} 表的相关字段建索引")
                d.plan.append(f"{r[2]}: type={r[4]}, key={r[6]}")
        d.has_full_scan = bool(d.scanned_tables)
        d.ok = True
        return d





def render(d: Diagnosis) -> str:
    """把诊断结果渲染成终端能看的文本（这段不用改，参考输出格式）。"""
    lines = [f"SQL: {d.sql}"]
    if not d.ok:
        lines.append(f"诊断失败: {d.error}")
        return "\n".join(lines)

    lines.append("执行计划:")
    for p in d.plan:
        lines.append(f"  {p}")

    if d.has_full_scan:
        lines.append(f"检测到全表扫描: {', '.join(d.scanned_tables)}")
        lines.append("建议:")
        for s in d.suggestions:
            lines.append(f"  - {s}")
    else:
        lines.append("未检测到全表扫描，索引情况良好")
    return "\n".join(lines)
