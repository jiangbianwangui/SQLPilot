"""
SQLGuard 安全校验测试。

为什么这个测试最重要：
    这是系统对抗 SQL 注入的最后一道防线。如果这里有漏洞，
    攻击者可以让 Agent 删库、拖垮数据库、甚至读服务器文件。
    所以每个用例都要有对应的断言，不允许"看起来对就行"。

运行：
    pytest tests/test_sql_guard.py -v
"""

import pytest

from app.tools.sql_guard import SQLGuard, validate_sql


# ============================================================
# 必须放行的合法查询
# ============================================================
VALID_QUERIES = [
    "SELECT * FROM products",
    "SELECT name, price FROM products WHERE price > 100",
    "SELECT COUNT(*) FROM orders",
    # 含中文注释，应该能正常解析
    "SELECT id, name FROM products -- 这是中文注释",
    "SELECT id FROM products /* 块注释 */ WHERE id > 1",
    # 字符串里带分号，不是多语句
    "SELECT * FROM t WHERE name = 'a;b'",
    # CTE 写法（WITH ... SELECT）
    "WITH t AS (SELECT * FROM orders) SELECT COUNT(*) FROM t",
    # 聚合 + 分组
    "SELECT category, SUM(price) FROM products GROUP BY category HAVING SUM(price) > 1000",
    # JOIN
    "SELECT o.id, p.name FROM orders o JOIN products p ON o.product_id = p.id",
    # 允许的子查询
    "SELECT name FROM products WHERE id IN (SELECT product_id FROM orders)",
    # UNION 是只读的，报表场景很常见，必须放行
    "SELECT name FROM products UNION SELECT name FROM archived_products",
    # SQL 末尾有多余分号，仍是单条
    "SELECT * FROM products;",
    # 大小写混写的纯查询
    "select NAME from Products",
]


@pytest.mark.parametrize("sql", VALID_QUERIES)
def test_valid_queries_pass(sql):
    """合法查询必须放行，否则系统没法用"""
    result = SQLGuard().validate(sql)
    assert result.ok, f"应该放行却拒绝了：{sql}\n理由：{result.reason}"


# ============================================================
# 必须拦截的危险查询
# ============================================================
DANGEROUS_QUERIES = [
    # ---- 破坏性 DDL ----
    ("DROP TABLE products", "删表"),
    ("DROP DATABASE inventory", "删库"),
    ("TRUNCATE TABLE products", "清空表"),
    ("ALTER TABLE products ADD COLUMN x INT", "改表结构"),
    ("CREATE TABLE evil (id INT)", "建表"),
    ("CREATE DATABASE evil", "建库"),
    ("RENAME TABLE products TO p2", "重命名"),
    # ---- 破坏性 DML ----
    ("INSERT INTO products VALUES (1, 'x')", "插入"),
    ("UPDATE products SET price = 0", "更新"),
    ("DELETE FROM products", "删除"),
    ("REPLACE INTO products VALUES (1)", "替换"),
    # ---- 堆叠查询（注入经典形态）----
    ("SELECT * FROM users; DROP TABLE products", "堆叠查询"),
    ("SELECT 1; INSERT INTO t VALUES (1)", "堆叠查询"),
    # ---- 权限与事务 ----
    ("GRANT ALL ON *.* TO 'x'@'%'", "授权"),
    ("REVOKE ALL ON *.* FROM 'x'@'%'", "回收权限"),
    # CALL 在 sqlglot 里是 Command 节点，属于非查询语句
    ("CALL some_dangerous_proc()", "存储过程调用"),
    # ---- 文件读写 ----
    ("SELECT LOAD_FILE('/etc/passwd')", "读文件"),
    ("SELECT * FROM t INTO OUTFILE '/tmp/x.csv'", "写文件"),
    # ---- 拖垮服务 ----
    ("SELECT SLEEP(10)", "延时函数"),
    ("SELECT BENCHMARK(1000000, MD5('a'))", "压测函数"),
]


@pytest.mark.parametrize("sql,desc", DANGEROUS_QUERIES)
def test_dangerous_queries_blocked(sql, desc):
    """危险查询必须拦截，这是安全底线"""
    result = SQLGuard().validate(sql)
    assert not result.ok, f"【{desc}】竟然被放行了：{sql}"
    assert result.reason, f"拦截时必须给出原因，供 LLM 自我修正：{sql}"


# ============================================================
# 边界与绕过场景
# ============================================================

def test_comment_is_stripped_before_checking():
    """
    注释内容不会被执行，所以剥离后再判断。
    `SELECT 1 /* DROP TABLE x */` 剥离后是 `SELECT 1`，是安全的，应当放行。
    （社区某些实现会因为注释里有 DROP 就误判，这里明确行为：剥离）
    """
    result = SQLGuard().validate("SELECT 1 /* DROP TABLE products */")
    assert result.ok, "注释内容不执行，不该因此拒绝"
    assert "DROP" not in result.sql.upper(), "注释应被剥离后再交给数据库"


def test_line_comment_truncation():
    """
    真正的风险：-- 注释会吃掉本该执行的后半段条件。
    例如 LLM 生成 `SELECT * FROM t WHERE price>100 -- 忽略低价`，
    注释在服务器端被正确处理，但我们要确认剥离后语义完整、不产生多余语句。
    """
    result = SQLGuard().validate(
        "SELECT name, price FROM products WHERE price > 100 -- 过滤低价商品"
    )
    assert result.ok
    assert "products" in result.sql
    assert "过滤低价商品" not in result.sql, "中文注释应被剥离"


def test_case_insensitive_blocked():
    """大小写混写不能绕过：drop table / DrOp TaBlE"""
    for sql in ["drop table products", "DrOp TaBlE products", "DELETE FROM products"]:
        assert not SQLGuard().validate(sql).ok, f"大小写混写被绕过：{sql}"


def test_keyword_in_identifier_not_false_positive():
    """
    关键：不能误杀合法查询。
    created_at 里有 ate，drop 之类子串不能当成危险词。
    这是关键词黑名单最常见的误报来源。
    """
    valid = [
        "SELECT created_at, updated_at FROM orders",
        "SELECT deleted_flag FROM products",
        "SELECT creator_id FROM items",
        "SELECT * FROM updates",
    ]
    for sql in valid:
        result = SQLGuard().validate(sql)
        assert result.ok, f"误杀了合法查询：{sql}\n理由：{result.reason}"


def test_empty_sql_rejected():
    """空输入要拒绝，不能崩"""
    for bad in ["", "   ", "\n\t"]:
        result = SQLGuard().validate(bad)
        assert not result.ok


def test_garbage_input_not_crash():
    """乱七八糟的输入不能抛异常"""
    for bad in ["asdf", "!!!", "SELECT FROM WHERE", "'; DROP TABLE", "((("]:
        result = SQLGuard().validate(bad)   # 不能抛异常
        assert isinstance(result.ok, bool)


def test_reason_is_readable_chinese():
    """
    拒绝原因必须是能直接喂给 LLM 的中文说明。
    这是错误自修复闭环的基础 —— 原因不清晰，LLM 就修不对。
    """
    result = SQLGuard().validate("DROP TABLE products")
    assert "不允许" in result.reason or "危险" in result.reason
    assert result.statement_type == "drop", "应该能识别出语句类型是 drop"


def test_bool_protocol():
    """支持 if result: 这种写法"""
    assert bool(SQLGuard().validate("SELECT 1 FROM t")) is True
    assert bool(SQLGuard().validate("DROP TABLE t")) is False


def test_module_level_function():
    """模块级便捷函数也要能用"""
    assert validate_sql("SELECT 1 FROM t").ok
    assert not validate_sql("DELETE FROM t").ok


# ============================================================
# 安全边界：明确哪些不归本层管
#
# 这些是"正常 SQL 语义"，不是注入，校验层不该也不能拦：
#   SELECT * FROM t WHERE name='' OR 1=1        -- 逻辑上等价于全表
#   SELECT * FROM t WHERE 1=1 -- 后面是注释      -- 语义被注释吃掉
#
# 防这类问题靠的是工程手段，不是关键字黑名单：
#   1. 业务层永远用参数化查询，不拼接用户输入
#   2. 数据库连接用只读账号，且只 GRANT 必要的表
#   3. 加行级权限 / LIMIT 约束
#
# 把这个边界写清楚，比假装"全都拦住了"更诚实 —— 面试时也更好讲。
# ============================================================

def test_or_tautology_is_not_rejected():
    """OR 恒真是合法 SQL 语法，本层不拦（靠只读账号 + 参数化查询防御）"""
    result = SQLGuard().validate("SELECT * FROM users WHERE name='' OR 1=1")
    assert result.ok, "这是合法 SQL，拦截会造成误杀"


def test_excessive_limit_not_enforced_here():
    """
    本层不限制 SELECT 的返回量。行数限制应该在执行层做（见 execute_tool），
    这里刻意不做，避免校验层职责过载。
    """
    result = SQLGuard().validate("SELECT * FROM huge_table")
    assert result.ok
