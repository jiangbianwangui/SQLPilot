"""
一键 demo —— 不依赖 Docker/MySQL，用 SQLite 内存库跑通完整链路。

    python -m app.demo "北京客户一共花了多少钱"

真实环境把 build_demo_engine() 换成 MySQL 只读账号连接即可，
上层 SQLAgent 代码一行都不用改。
"""

from __future__ import annotations

import sys
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from .agents.sql_agent import SQLAgent
from .core.llm import llm_generate

# 和 sql/init_db.sql 同构的迷你 shop 库（SQLite 方言），共 14 张表。
# 扩到十几张表后，SchemaRetriever(top_k=5) 才会显出「选表筛选」效果，
# 否则 5 张表全部被选中，看起来像没筛选。
_DDL = [
    # ---------- 原有 5 张核心表（订单 / 商品 / 客户链路）----------
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
    # ---------- 新增 9 张表，让演示库更像真实业务库 ----------
    """CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
       contact TEXT, city TEXT, rating REAL DEFAULT 0)""",
    """CREATE TABLE coupons (id INTEGER PRIMARY KEY, code TEXT NOT NULL,
       discount REAL NOT NULL, min_spend REAL DEFAULT 0, expires_at TEXT)""",
    """CREATE TABLE reviews (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL,
       customer_id INTEGER NOT NULL, rating INTEGER NOT NULL DEFAULT 5,
       content TEXT, created_at TEXT DEFAULT '2025-01-01 00:00:00')""",
    """CREATE TABLE shipments (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
       carrier TEXT, tracking_no TEXT, status TEXT DEFAULT 'shipped',
       shipped_at TEXT DEFAULT '2025-01-01 00:00:00')""",
    """CREATE TABLE payments (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
       method TEXT, amount REAL NOT NULL,
       paid_at TEXT DEFAULT '2025-01-01 00:00:00')""",
    """CREATE TABLE returns (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
       reason TEXT, refund_amount REAL DEFAULT 0,
       created_at TEXT DEFAULT '2025-01-01 00:00:00')""",
    """CREATE TABLE addresses (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
       province TEXT, city TEXT, detail TEXT)""",
    """CREATE TABLE cart_items (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
       product_id INTEGER NOT NULL, qty INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE staff (id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT)""",
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
    # ---------- 新增表数据 ----------
    """INSERT INTO suppliers (id,name,contact,city,rating) VALUES
       (1,'华强电子','13800000001','深圳',4.5),(2,'云仓服饰','13800000002','上海',4.2),
       (3,'温馨家居','13800000003','广州',4.8)""",
    """INSERT INTO coupons (id,code,discount,min_spend,expires_at) VALUES
       (1,'SAVE10',10,100,'2025-12-31'),(2,'SAVE50',50,500,'2025-12-31'),
       (3,'NEW20',20,0,'2025-06-30')""",
    """INSERT INTO reviews (id,product_id,customer_id,rating,content,created_at) VALUES
       (1,1,1,5,'很好用','2025-01-15 10:00:00'),(2,3,3,4,'很轻薄','2025-02-18 09:00:00'),
       (3,2,2,3,'一般般','2025-03-05 14:00:00'),(4,6,5,5,'很暖和','2025-03-22 11:00:00')""",
    """INSERT INTO shipments (id,order_id,carrier,tracking_no,status,shipped_at) VALUES
       (1,1,'SF','SF123','delivered','2025-01-13 09:00:00'),
       (2,3,'JD','JD456','delivered','2025-02-16 10:00:00'),
       (3,5,'YD','YD789','shipped','2025-03-21 11:00:00')""",
    """INSERT INTO payments (id,order_id,method,amount,paid_at) VALUES
       (1,1,'wechat',3999,'2025-01-12 10:01:00'),(2,2,'alipay',79,'2025-02-03 14:31:00'),
       (3,3,'card',8999,'2025-02-15 09:13:00'),(4,5,'wechat',129,'2025-03-20 11:46:00')""",
    """INSERT INTO returns (id,order_id,reason,refund_amount,created_at) VALUES
       (1,4,'不喜欢',5499,'2025-03-02 10:00:00')""",
    """INSERT INTO addresses (id,customer_id,province,city,detail) VALUES
       (1,1,'北京市','北京市','朝阳区xx路1号'),(2,2,'上海市','上海市','浦东新区yy路2号'),
       (3,3,'广东省','广州市','天河区zz路3号'),(4,5,'广东省','深圳市','南山区ww路4号')""",
    """INSERT INTO cart_items (id,customer_id,product_id,qty) VALUES
       (1,2,2,1),(2,3,4,1),(3,4,1,2)""",
    """INSERT INTO staff (id,name,role) VALUES
       (1,'小美','客服'),(2,'小李','仓库'),(3,'小王','财务')""",
]

# SQLite 的 inspector 读不到 COMMENT（MySQL 可以），但选表器打分严重依赖
# 中文注释匹配。这里把和 sql/init_db.sql 同款的注释注入到 engine.info，
# 让演示库（SQLite）也能跑出有意义的选表结果。MySQL 真实库自带注释，不受影响。
_COMMENTS = {
    "categories": {"table": "商品分类", "columns": {"name": "分类名称", "parent_id": "父分类"}},
    "products": {"table": "商品", "columns": {
        "name": "商品名", "category_id": "所属分类", "price": "单价",
        "stock": "库存", "created_at": "上架时间"}},
    "customers": {"table": "客户", "columns": {
        "name": "客户姓名", "city": "所在城市", "level": "会员等级"}},
    "orders": {"table": "订单", "columns": {
        "customer_id": "下单客户", "amount": "订单金额", "status": "订单状态",
        "created_at": "下单时间"}},
    "order_items": {"table": "订单明细", "columns": {
        "order_id": "所属订单", "product_id": "商品", "qty": "数量", "price": "成交单价"}},
    "suppliers": {"table": "供应商", "columns": {
        "name": "供应商名称", "contact": "联系电话", "city": "所在城市", "rating": "评分"}},
    "coupons": {"table": "优惠券", "columns": {
        "code": "优惠券码", "discount": "减免金额", "min_spend": "最低消费", "expires_at": "过期日"}},
    "reviews": {"table": "商品评价", "columns": {
        "product_id": "商品", "customer_id": "客户", "rating": "评分",
        "content": "评价内容", "created_at": "评价时间"}},
    "shipments": {"table": "物流发货", "columns": {
        "order_id": "订单", "carrier": "承运商", "tracking_no": "运单号",
        "status": "状态", "shipped_at": "发货时间"}},
    "payments": {"table": "支付记录", "columns": {
        "order_id": "订单", "method": "支付方式", "amount": "支付金额", "paid_at": "支付时间"}},
    "returns": {"table": "退货", "columns": {
        "order_id": "订单", "reason": "退货原因", "refund_amount": "退款金额", "created_at": "退货时间"}},
    "addresses": {"table": "收货地址", "columns": {
        "customer_id": "客户", "province": "省份", "city": "城市", "detail": "详细地址"}},
    "cart_items": {"table": "购物车", "columns": {
        "customer_id": "客户", "product_id": "商品", "qty": "数量"}},
    "staff": {"table": "员工", "columns": {"name": "姓名", "role": "岗位"}},
}


def build_demo_engine(path: Optional[str] = None):
    """建一个带示例数据的 SQLite 库。

    Args:
        path: 不传则用内存库（CLI 单次运行够用）；
              传文件路径则用文件库（Web 服务用，支持多请求/多线程安全访问）。
    """
    if path:
        # 文件库：用默认连接池，每个请求拿独立连接，线程安全且数据持久
        engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
    else:
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
    # 把中文注释注入 engine，让 SQLite 演示库也能被 SchemaRetriever 选中
    # （SQLite inspector 读不到 COMMENT；MySQL 真实库自带注释，不受影响）。
    engine.sqlpilot_comments = _COMMENTS
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
