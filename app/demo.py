"""
一键 demo —— 不依赖 Docker/MySQL，用 SQLite 内存库跑通完整链路。

    python -m app.demo "北京客户一共花了多少钱"

真实环境把 build_demo_engine() 换成 MySQL 只读账号连接即可，
上层 SQLAgent 代码一行都不用改。
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from .agents.sql_agent import SQLAgent
from .core.llm import llm_generate

# 和 sql/init_db.sql 同构的迷你 shop 库（SQLite 方言）
_DDL = [
    """CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
       parent_id INTEGER)""",
    """CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
       category_id INTEGER NOT NULL, price REAL NOT NULL, stock INTEGER NOT NULL DEFAULT 0,
       created_at TEXT NOT NULL DEFAULT '2025-01-01 00:00:00')""",
    """CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
       city TEXT, level INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
       amount REAL NOT NULL, status TEXT NOT NULL DEFAULT 'paid',
       created_at TEXT NOT NULL DEFAULT '2025-01-01 00:00:00')""",
    """CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
       product_id INTEGER NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL)""",
]

_ROWS = [
    """INSERT INTO categories (id,name,parent_id) VALUES (1,'数码',NULL),(2,'服饰',NULL),(3,'家居',NULL),(4,'手机',1),(5,'笔记本',1)""",
    """INSERT INTO products (id,name,category_id,price,stock) VALUES
       (1,'智能手机 X1',4,3999,120),(2,'智能手机 X2',4,5999,80),
       (3,'轻薄笔记本 A',5,5499,40),(4,'游戏笔记本 B',5,8999,25),
       (5,'纯棉T恤',2,79,500),(6,'羽绒服',2,699,200),(7,'台灯',3,129,300)""",
    """INSERT INTO customers (id,name,city,level) VALUES
       (1,'张三','北京',3),(2,'李四','上海',2),(3,'王五','广州',5),(4,'赵六','北京',1),(5,'钱七','深圳',4)""",
    """INSERT INTO orders (id,customer_id,amount,status,created_at) VALUES
       (1,1,3999,'paid','2025-01-12 10:00:00'),(2,1,79,'paid','2025-02-03 14:30:00'),
       (3,3,8999,'paid','2025-02-15 09:12:00'),(4,2,5499,'refunded','2025-03-01 20:00:00'),
       (5,5,129,'paid','2025-03-20 11:45:00'),(6,4,699,'paid','2025-04-08 19:05:00')""",
    """INSERT INTO order_items (id,order_id,product_id,qty,price) VALUES
       (1,1,1,1,3999),(2,2,5,1,79),(3,3,4,1,8999),(4,4,3,1,5499),(5,5,7,1,129),(6,6,6,1,699)""",
]


def build_demo_engine():
    """建一个带示例数据的 SQLite 内存库。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
        for row in _ROWS:
            conn.execute(text(row))
    return engine


def build_mysql_engine():
    """连真实进销存库（MySQL @127.0.0.1:3306 / stationery_inventory）。

    这就是 S1「接真实数据库」的入口：把 SQLAgent 的引擎从 SQLite 内存库
    换成它，上层编排一行不用改。生产环境务必用**只读账号**，密码走环境变量，
    别硬编码（这里用本地默认值仅为本地演示）。
    """
    import os

    user = os.getenv("SQLPILOT_DB_USER", "root")
    pw = os.getenv("SQLPILOT_DB_PASSWORD", "123456")
    host = os.getenv("SQLPILOT_DB_HOST", "127.0.0.1")
    port = os.getenv("SQLPILOT_DB_PORT", "3306")
    db = os.getenv("SQLPILOT_DB_NAME", "stationery_inventory")
    url = f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


def main() -> None:
    question = " ".join(sys.argv[1:]) or "北京客户一共花了多少钱"
    print(f"=== SQLPilot Demo ===\n")

    agent = SQLAgent(build_demo_engine(), llm_generate=llm_generate)
    answer = agent.ask(question)
    print(answer.render())


if __name__ == "__main__":
    main()
