-- ============================================================
-- SQLPilot 演示库（MySQL 8）
-- 用途：本地起一个真实的业务库，让 text-to-SQL 有东西可查。
-- 启动方式（需要 Docker）：
--   docker run -d --name sqlpilot-mysql `
--     -e MYSQL_ROOT_PASSWORD=root123 `
--     -p 3306:3306 mysql:8
--   然后：mysql -h127.0.0.1 -uroot -proot123 < sql/init_db.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS shop
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE shop;

-- ---------- 分类表 ----------
DROP TABLE IF EXISTS categories;
CREATE TABLE categories (
  id      INT PRIMARY KEY AUTO_INCREMENT,
  name    VARCHAR(50)  NOT NULL COMMENT '分类名称',
  parent_id INT NULL COMMENT '父分类，NULL 表示一级分类'
) COMMENT='商品分类';

-- ---------- 商品表 ----------
DROP TABLE IF EXISTS products;
CREATE TABLE products (
  id          INT PRIMARY KEY AUTO_INCREMENT,
  name        VARCHAR(100) NOT NULL COMMENT '商品名',
  category_id INT          NOT NULL COMMENT '所属分类',
  price       DECIMAL(10,2) NOT NULL COMMENT '单价',
  stock       INT          NOT NULL DEFAULT 0 COMMENT '库存',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上架时间'
) COMMENT='商品';

-- ---------- 客户表 ----------
DROP TABLE IF EXISTS customers;
CREATE TABLE customers (
  id      INT PRIMARY KEY AUTO_INCREMENT,
  name    VARCHAR(50)  NOT NULL COMMENT '客户姓名',
  city    VARCHAR(50)  COMMENT '所在城市',
  level   TINYINT      NOT NULL DEFAULT 1 COMMENT '会员等级 1-5'
) COMMENT='客户';

-- ---------- 订单表 ----------
DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
  id         INT PRIMARY KEY AUTO_INCREMENT,
  customer_id INT NOT NULL COMMENT '下单客户',
  amount     DECIMAL(10,2) NOT NULL COMMENT '订单金额',
  status     VARCHAR(20) NOT NULL DEFAULT 'paid' COMMENT 'paid/refunded',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下单时间'
) COMMENT='订单';

-- ---------- 订单明细表 ----------
DROP TABLE IF EXISTS order_items;
CREATE TABLE order_items (
  id         INT PRIMARY KEY AUTO_INCREMENT,
  order_id   INT NOT NULL COMMENT '所属订单',
  product_id INT NOT NULL COMMENT '商品',
  qty        INT NOT NULL COMMENT '数量',
  price      DECIMAL(10,2) NOT NULL COMMENT '成交单价'
) COMMENT='订单明细';

-- ---------- 示例数据 ----------
INSERT INTO categories (name, parent_id) VALUES
  ('数码', NULL), ('服饰', NULL), ('家居', NULL),
  ('手机', 1), ('笔记本', 1);

INSERT INTO products (name, category_id, price, stock) VALUES
  ('智能手机 X1', 4, 3999.00, 120),
  ('智能手机 X2', 4, 5999.00, 80),
  ('轻薄笔记本 A', 5, 5499.00, 40),
  ('游戏笔记本 B', 5, 8999.00, 25),
  ('纯棉T恤', 2, 79.00, 500),
  ('羽绒服', 2, 699.00, 200),
  ('台灯', 3, 129.00, 300);

INSERT INTO customers (name, city, level) VALUES
  ('张三', '北京', 3), ('李四', '上海', 2), ('王五', '广州', 5),
  ('赵六', '北京', 1), ('钱七', '深圳', 4);

INSERT INTO orders (customer_id, amount, status, created_at) VALUES
  (1, 3999.00, 'paid', '2025-01-12 10:00:00'),
  (1, 79.00,   'paid', '2025-02-03 14:30:00'),
  (3, 8999.00, 'paid', '2025-02-15 09:12:00'),
  (2, 5499.00, 'refunded', '2025-03-01 20:00:00'),
  (5, 129.00,  'paid', '2025-03-20 11:45:00'),
  (4, 699.00,  'paid', '2025-04-08 19:05:00');

INSERT INTO order_items (order_id, product_id, qty, price) VALUES
  (1, 1, 1, 3999.00),
  (2, 5, 1, 79.00),
  (3, 4, 1, 8999.00),
  (4, 3, 1, 5499.00),
  (5, 7, 1, 129.00),
  (6, 6, 1, 699.00);

-- 给几个常用查询建索引，方便后面演示「索引建议」功能
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_orders_customer  ON orders(customer_id);
CREATE INDEX idx_orders_created   ON orders(created_at);

-- ============================================================
-- 安全层其三：只读账号
-- SQLPilot 连接必须使用这个只读账号，即使前两层（AST 校验、关键词
-- 黑名单）被绕过，数据库本身也不允许写入 / 删表。
-- ============================================================
CREATE USER IF NOT EXISTS 'sqlpilot_ro'@'%' IDENTIFIED BY 'sqlpilot_ro_2026';
GRANT SELECT ON shop.* TO 'sqlpilot_ro'@'%';
FLUSH PRIVILEGES;
