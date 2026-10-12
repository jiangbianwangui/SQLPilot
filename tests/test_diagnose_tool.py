"""
DiagnoseTool 慢查询诊断测试。

为什么重要：
    诊断工具是 SQLPilot 的差异化功能 —— 它不只是"能查"，还能告诉用户
    "为什么慢、怎么改"。如果它对全表扫描视而不见，或者把走索引的查询
    误报成全表扫描，这个功能就失去意义了。所以三个核心场景必须有断言：
      1) 全表扫描能检测出来，并给出建索引建议
      2) 走了索引的查询不能误报
      3) 危险 SQL 在进诊断前就被安全层拦下，根本不会去跑

运行：
    pytest tests/test_diagnose_tool.py -v
"""

import pytest
from sqlalchemy import text

from app.demo import build_mysql_engine
from app.tools.diagnose_tool import DiagnoseTool, render


@pytest.fixture
def mysql_engine():
    """连进销存 MySQL 库；本地无 MySQL / 库不可达时跳过，不影响 SQLite 套件。

    方言分支是 SQLPilot 最近才加的（S1 阶段），必须有专门守护：
    一旦有人改坏 MySQL 的 EXPLAIN 解析，这条测试会立刻红，而不是把
    "方言锁死"的坑悄悄带回去。
    """
    try:
        eng = build_mysql_engine()
        with eng.connect() as conn:  # create_engine 是惰性的，必须真连一下探活
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"本地 MySQL 不可用，跳过方言测试：{e}")
    return eng


def test_full_scan_detected(engine):
    """没有索引的列做过滤，应该被识别为全表扫描并给出建索引建议。"""
    d = DiagnoseTool(engine).diagnose(
        "SELECT * FROM products WHERE name='智能手机 X1'"
    )
    assert d.ok, f"诊断应成功，却失败：{d.error}"
    assert d.has_full_scan is True, "name 列无索引，应判定为全表扫描"
    assert "products" in d.scanned_tables, (
        f"应识别出被扫描的表 products，实际：{d.scanned_tables}"
    )
    assert len(d.suggestions) > 0, "应给出至少一条建索引建议"
    assert "products" in d.suggestions[0], "建议文案里应包含表名"


def test_index_query_not_false_positive(engine):
    """走主键索引的查询，不应被误报为全表扫描。"""
    d = DiagnoseTool(engine).diagnose("SELECT * FROM products WHERE id=1")
    assert d.ok, f"诊断应成功，却失败：{d.error}"
    assert d.has_full_scan is False, "走主键索引不应被判为全表扫描"
    assert not d.scanned_tables, "走索引时不应记录任何被全表扫描的表"


def test_dangerous_sql_blocked(engine):
    """危险 SQL 应在安全层被拦，诊断直接以失败告终、不去执行。"""
    d = DiagnoseTool(engine).diagnose("DROP TABLE products")
    assert d.ok is False, "危险 SQL 不应进入诊断执行"
    assert d.error, "被拦截时应给出可读的错误原因"


# ===================== 方言分支守护（MySQL） =====================
# 上面的 3 个用例都用 SQLite fixture，覆盖不到 MySQL 的 EXPLAIN 解析。
# 下面两条专门守方言分支：MySQL 的 EXPLAIN 返回 12 列表，
# 全表扫描标志是 type='ALL' 且 key 为空 —— 和 SQLite 的文本解析完全不同。


def test_mysql_full_scan_detected(mysql_engine):
    """MySQL：无索引列 spec 过滤，应识别为全表扫描并给建索引建议。"""
    d = DiagnoseTool(mysql_engine).diagnose(
        "SELECT * FROM product WHERE spec='红色'"
    )
    assert d.ok, f"MySQL 诊断应成功，却失败：{d.error}"
    assert d.has_full_scan is True, "spec 列无索引，应判定为全表扫描"
    assert "product" in d.scanned_tables, (
        f"应识别出被扫描的表 product，实际：{d.scanned_tables}"
    )
    assert len(d.suggestions) > 0, "应给出至少一条建索引建议"


def test_mysql_index_query_not_false_positive(mysql_engine):
    """MySQL：走主键（id）的查询，不应被误报为全表扫描。"""
    d = DiagnoseTool(mysql_engine).diagnose(
        "SELECT * FROM product WHERE id=1"
    )
    assert d.ok, f"MySQL 诊断应成功，却失败：{d.error}"
    assert d.has_full_scan is False, "走主键索引不应被判为全表扫描"
    assert not d.scanned_tables, "走索引时不应记录任何被全表扫描的表"
