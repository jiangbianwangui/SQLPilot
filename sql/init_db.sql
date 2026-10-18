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

-- ---------- 供应商表 ----------
DROP TABLE IF EXISTS suppliers;
CREATE TABLE suppliers (
  id      INT PRIMARY KEY AUTO_INCREMENT,
  name    VARCHAR(50)  NOT NULL COMMENT '供应商名称',
  contact VARCHAR(20)  COMMENT '联系电话',
  city    VARCHAR(50)  COMMENT '所在城市',
  rating  DECIMAL(2,1) DEFAULT 0 COMMENT '评分'
) COMMENT='供应商';

-- ---------- 优惠券表 ----------
DROP TABLE IF EXISTS coupons;
CREATE TABLE coupons (
  id         INT PRIMARY KEY AUTO_INCREMENT,
  code       VARCHAR(20)  NOT NULL COMMENT '优惠券码',
  discount   DECIMAL(10,2) NOT NULL COMMENT '减免金额',
  min_spend  DECIMAL(10,2) DEFAULT 0 COMMENT '最低消费',
  expires_at DATE         COMMENT '过期日'
) COMMENT='优惠券';

-- ---------- 商品评价表 ----------
DROP TABLE IF EXISTS reviews;
CREATE TABLE reviews (
  id          INT PRIMARY KEY AUTO_INCREMENT,
  product_id  INT NOT NULL COMMENT '商品',
  customer_id INT NOT NULL COMMENT '客户',
  rating      TINYINT NOT NULL DEFAULT 5 COMMENT '评分 1-5',
  content     VARCHAR(200) COMMENT '评价内容',
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '评价时间'
) COMMENT='商品评价';

-- ---------- 物流发货表 ----------
DROP TABLE IF EXISTS shipments;
CREATE TABLE shipments (
  id          INT PRIMARY KEY AUTO_INCREMENT,
  order_id    INT NOT NULL COMMENT '订单',
  carrier     VARCHAR(20) COMMENT '承运商',
  tracking_no VARCHAR(30) COMMENT '运单号',
  status      VARCHAR(20) DEFAULT 'shipped' COMMENT '状态',
  shipped_at  DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '发货时间'
) COMMENT='物流发货';

-- ---------- 支付记录表 ----------
DROP TABLE IF EXISTS payments;
CREATE TABLE payments (
  id       INT PRIMARY KEY AUTO_INCREMENT,
  order_id INT NOT NULL COMMENT '订单',
  method   VARCHAR(20) COMMENT '支付方式',
  amount   DECIMAL(10,2) NOT NULL COMMENT '支付金额',
  paid_at  DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '支付时间'
) COMMENT='支付记录';

-- ---------- 退货表 ----------
DROP TABLE IF EXISTS returns;
CREATE TABLE returns (
  id             INT PRIMARY KEY AUTO_INCREMENT,
  order_id       INT NOT NULL COMMENT '订单',
  reason         VARCHAR(100) COMMENT '退货原因',
  refund_amount  DECIMAL(10,2) DEFAULT 0 COMMENT '退款金额',
  created_at     DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '退货时间'
) COMMENT='退货';

-- ---------- 收货地址表 ----------
DROP TABLE IF EXISTS addresses;
CREATE TABLE addresses (
  id          INT PRIMARY KEY AUTO_INCREMENT,
  customer_id INT NOT NULL COMMENT '客户',
  province    VARCHAR(50) COMMENT '省份',
  city        VARCHAR(50) COMMENT '城市',
  detail      VARCHAR(100) COMMENT '详细地址'
) COMMENT='收货地址';

-- ---------- 购物车表 ----------
DROP TABLE IF EXISTS cart_items;
CREATE TABLE cart_items (
  id          INT PRIMARY KEY AUTO_INCREMENT,
  customer_id INT NOT NULL COMMENT '客户',
  product_id  INT NOT NULL COMMENT '商品',
  qty         INT NOT NULL DEFAULT 1 COMMENT '数量'
) COMMENT='购物车';

-- ---------- 员工表 ----------
DROP TABLE IF EXISTS staff;
CREATE TABLE staff (
  id    INT PRIMARY KEY AUTO_INCREMENT,
  name  VARCHAR(50) NOT NULL COMMENT '姓名',
  role  VARCHAR(20) COMMENT '岗位'
) COMMENT='员工';

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

INSERT INTO suppliers (name, contact, city, rating) VALUES
  ('华强电子', '13800000001', '深圳', 4.5),
  ('云仓服饰', '13800000002', '上海', 4.2),
  ('温馨家居', '13800000003', '广州', 4.8);

INSERT INTO coupons (code, discount, min_spend, expires_at) VALUES
  ('SAVE10', 10.00, 100.00, '2025-12-31'),
  ('SAVE50', 50.00, 500.00, '2025-12-31'),
  ('NEW20', 20.00, 0.00, '2025-06-30');

INSERT INTO reviews (product_id, customer_id, rating, content, created_at) VALUES
  (1, 1, 5, '很好用', '2025-01-15 10:00:00'),
  (3, 3, 4, '很轻薄', '2025-02-18 09:00:00'),
  (2, 2, 3, '一般般', '2025-03-05 14:00:00'),
  (6, 5, 5, '很暖和', '2025-03-22 11:00:00');

INSERT INTO shipments (order_id, carrier, tracking_no, status, shipped_at) VALUES
  (1, 'SF', 'SF123', 'delivered', '2025-01-13 09:00:00'),
  (3, 'JD', 'JD456', 'delivered', '2025-02-16 10:00:00'),
  (5, 'YD', 'YD789', 'shipped', '2025-03-21 11:00:00');

INSERT INTO payments (order_id, method, amount, paid_at) VALUES
  (1, 'wechat', 3999.00, '2025-01-12 10:01:00'),
  (2, 'alipay', 79.00, '2025-02-03 14:31:00'),
  (3, 'card', 8999.00, '2025-02-15 09:13:00'),
  (5, 'wechat', 129.00, '2025-03-20 11:46:00');

INSERT INTO returns (order_id, reason, refund_amount, created_at) VALUES
  (4, '不喜欢', 5499.00, '2025-03-02 10:00:00');

INSERT INTO addresses (customer_id, province, city, detail) VALUES
  (1, '北京市', '北京市', '朝阳区xx路1号'),
  (2, '上海市', '上海市', '浦东新区yy路2号'),
  (3, '广东省', '广州市', '天河区zz路3号'),
  (5, '广东省', '深圳市', '南山区ww路4号');

INSERT INTO cart_items (customer_id, product_id, qty) VALUES
  (2, 2, 1), (3, 4, 1), (4, 1, 2);

INSERT INTO staff (name, role) VALUES
  ('小美', '客服'), ('小李', '仓库'), ('小王', '财务');

-- 给几个常用查询建索引，方便后面演示「索引建议」功能
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_orders_customer  ON orders(customer_id);
CREATE INDEX idx_orders_created   ON orders(created_at);

-- 新增表的外键索引（演示「索引建议」功能时，这些字段正好缺建议）
CREATE INDEX idx_reviews_product  ON reviews(product_id);
CREATE INDEX idx_reviews_customer ON reviews(customer_id);
CREATE INDEX idx_shipments_order  ON shipments(order_id);
CREATE INDEX idx_payments_order   ON payments(order_id);
CREATE INDEX idx_returns_order    ON returns(order_id);
CREATE INDEX idx_addresses_cust   ON addresses(customer_id);
CREATE INDEX idx_cart_customer    ON cart_items(customer_id);
CREATE INDEX idx_cart_product     ON cart_items(product_id);
CREATE INDEX idx_suppliers_city   ON suppliers(city);

-- ============================================================
-- 安全层其三：只读账号
-- SQLPilot 连接必须使用这个只读账号，即使前两层（AST 校验、关键词
-- 黑名单）被绕过，数据库本身也不允许写入 / 删表。
-- ============================================================
CREATE USER IF NOT EXISTS 'sqlpilot_ro'@'%' IDENTIFIED BY 'sqlpilot_ro_2026';
GRANT SELECT ON shop.* TO 'sqlpilot_ro'@'%';
FLUSH PRIVILEGES;
