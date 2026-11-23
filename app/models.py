"""数据库模型 —— 共享文件，修改前先在群里说。

说明：这里是所有端共用的领域模型，按"端"分区。各端负责人如果要新增
自己端的表，先群里说一声，避免同时改这个文件造成冲突。
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


# ============================================================
# 共享表（订单/用户跨端使用，组长统一定义）
# ============================================================

class User(db.Model):
    """用户：普通用户 / 商家 / 平台管理员 / 物流配送 四种身份统一建模。"""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # user / merchant / admin / logistics
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    """订单：下单源头在用户端，商家/物流都要读它、更新状态。"""
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    fruit_id = db.Column(db.Integer, db.ForeignKey("fruits.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    total_price = db.Column(db.Float)
    status = db.Column(db.String(20), default="待支付")  # 待支付/待发货/运输中/已完成/已取消
    is_seckill = db.Column(db.Boolean, default=False)   # 是否秒杀订单
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    fruit = db.relationship("Fruit", backref="orders")


# ============================================================
# 用户端表（组长负责）
# ============================================================

class Cart(db.Model):
    """购物车。"""
    __tablename__ = "cart_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    fruit_id = db.Column(db.Integer, db.ForeignKey("fruits.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)

    fruit = db.relationship("Fruit", backref="cart_items")


class SeckillActivity(db.Model):
    """限时秒杀活动（创新点）。"""
    __tablename__ = "seckill_activities"

    id = db.Column(db.Integer, primary_key=True)
    fruit_id = db.Column(db.Integer, db.ForeignKey("fruits.id"), nullable=False)
    seckill_price = db.Column(db.Float, nullable=False)   # 秒杀价
    stock = db.Column(db.Integer, nullable=False)          # 剩余库存（原子扣减用）
    total_stock = db.Column(db.Integer, nullable=False)    # 初始总库存（算"已抢"进度）
    limit_per_user = db.Column(db.Integer, default=1)      # 限购数量
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default="未开始")    # 未开始/进行中/已结束

    fruit = db.relationship("Fruit", backref="seckills")  # 关联水果，方便取名字/图片


class BrowseHistory(db.Model):
    """浏览历史（用于个性化推荐，创新点）。"""
    __tablename__ = "browse_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    fruit_id = db.Column(db.Integer, db.ForeignKey("fruits.id"), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# 商家端表（B 负责）
# ============================================================

class Fruit(db.Model):
    """水果商品。"""
    __tablename__ = "fruits"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    category = db.Column(db.String(64))          # 大分类（水果/蔬菜/肉禽等）
    sub_category = db.Column(db.String(64))      # 细分类（苹果/柑橘/莓果等）
    price = db.Column(db.Float)
    origin = db.Column(db.String(128))           # 产地
    sales = db.Column(db.Integer, default=0)     # 销量（支撑热销/进度条）
    merchant_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_on_sale = db.Column(db.Boolean, default=True)  # 上架/下架


class FruitBatch(db.Model):
    """水果批次（批次管理/溯源，创新点）。"""
    __tablename__ = "fruit_batches"

    id = db.Column(db.Integer, primary_key=True)
    fruit_id = db.Column(db.Integer, db.ForeignKey("fruits.id"), nullable=False)
    batch_no = db.Column(db.String(64), nullable=False)   # 批次号
    origin = db.Column(db.String(128))                     # 产地
    pick_date = db.Column(db.DateTime)                     # 采摘时间
    expire_date = db.Column(db.DateTime)                   # 保质期到期
    stock = db.Column(db.Integer, default=0)               # 该批次库存


class AfterSale(db.Model):
    """售后申请。"""
    __tablename__ = "after_sales"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    type = db.Column(db.String(20))          # 退款/退货
    reason = db.Column(db.String(255))
    status = db.Column(db.String(20), default="待处理")


# ============================================================
# 平台管理端表（C 负责）
# ============================================================

class MerchantQualification(db.Model):
    """商家资质审核。"""
    __tablename__ = "merchant_qualifications"

    id = db.Column(db.Integer, primary_key=True)
    merchant_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    license_no = db.Column(db.String(64))
    status = db.Column(db.String(20), default="待审核")   # 待审核/通过/驳回


class Complaint(db.Model):
    """平台投诉。"""
    __tablename__ = "complaints"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    content = db.Column(db.String(255))
    status = db.Column(db.String(20), default="待处理")


# ============================================================
# 物流端表（D 负责）
# ============================================================

class Logistics(db.Model):
    """物流配送。"""
    __tablename__ = "logistics"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    status = db.Column(db.String(20), default="待发货")   # 待发货/运输中/已完成
    courier = db.Column(db.String(64))                    # 配送员
    current_location = db.Column(db.String(128))          # 当前位置


class TemperatureLog(db.Model):
    """冷链温控记录（创新点）。"""
    __tablename__ = "temperature_logs"

    id = db.Column(db.Integer, primary_key=True)
    logistics_id = db.Column(db.Integer, db.ForeignKey("logistics.id"), nullable=False)
    temperature = db.Column(db.Float)                     # 温度
    record_time = db.Column(db.DateTime, default=datetime.utcnow)
