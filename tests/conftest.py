"""
测试公共 fixture。

为了让 Phase 1 的单元测试不依赖 Docker / MySQL，这里用 SQLite 的
内存库搭一个和 sql/init_db.sql 等价的迷你库。正式运行时代码走的是
MySQL + 只读账号，但 execute_tool / schema_tool 都基于 SQLAlchemy，
对两种引擎通用，所以单测可以放心用 SQLite。
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
import pytest


# SQLite 的 execute 一次只能跑一条语句，所以这里拆成单条列表
_SCHEMA_SQL = [
    """CREATE TABLE categories (
         id        INTEGER PRIMARY KEY,
         name      TEXT NOT NULL,
         parent_id INTEGER
       )""",
    """CREATE TABLE products (
         id          INTEGER PRIMARY KEY,
         name        TEXT NOT NULL,
         category_id INTEGER NOT NULL,
         price       REAL NOT NULL,
         stock       INTEGER NOT NULL DEFAULT 0,
         created_at  TEXT NOT NULL DEFAULT '2025-01-01 00:00:00'
       )""",
    """CREATE TABLE customers (
         id    INTEGER PRIMARY KEY,
         name  TEXT NOT NULL,
         city  TEXT,
         level INTEGER NOT NULL DEFAULT 1
       )""",
    """CREATE TABLE orders (
         id         INTEGER PRIMARY KEY,
         customer_id INTEGER NOT NULL,
         amount     REAL NOT NULL,
         status     TEXT NOT NULL DEFAULT 'paid',
         created_at TEXT NOT NULL DEFAULT '2025-01-01 00:00:00'
       )""",
    """CREATE TABLE order_items (
         id         INTEGER PRIMARY KEY,
         order_id   INTEGER NOT NULL,
         product_id INTEGER NOT NULL,
         qty        INTEGER NOT NULL,
         price      REAL NOT NULL
       )""",
]

_SAMPLE_ROWS = [
    ("INSERT INTO categories (id,name,parent_id) VALUES (1,'数码',NULL),(2,'服饰',NULL),(4,'手机',1);",),
    ("INSERT INTO products (id,name,category_id,price,stock) VALUES "
     "(1,'智能手机 X1',4,3999.00,120),(2,'轻薄笔记本 A',5,5499.00,40),(3,'纯棉T恤',2,79.00,500);",),
    ("INSERT INTO customers (id,name,city,level) VALUES "
     "(1,'张三','北京',3),(2,'李四','上海',2),(3,'王五','广州',5);",),
    ("INSERT INTO orders (id,customer_id,amount,status,created_at) VALUES "
     "(1,1,3999.00,'paid','2025-01-12 10:00:00'),"
     "(2,3,8999.00,'paid','2025-02-15 09:12:00'),"
     "(3,2,5499.00,'refunded','2025-03-01 20:00:00');",),
    ("INSERT INTO order_items (id,order_id,product_id,qty,price) VALUES "
     "(1,1,1,1,3999.00),(2,2,4,1,8999.00),(3,3,3,1,5499.00);",),
]


@pytest.fixture
def engine():
    """一个带示例数据的 SQLite 内存引擎（StaticPool 保证连接间共享）。"""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.begin() as conn:
        for ddl in _SCHEMA_SQL:
            conn.execute(text(ddl))
        for (stmt,) in _SAMPLE_ROWS:
            conn.execute(text(stmt))
    return eng
