"""数据库模型 —— 共享文件，修改前先在群里说。

说明：这里是所有端共用的领域模型。各端负责人如果要用到新表，
先在群里说一声，避免同时改这个文件造成冲突。
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    """用户：普通用户 / 商家 / 平台管理员 / 物流配送 四种身份统一建模。"""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # user / merchant / admin / logistics


class Fruit(db.Model):
    """水果品类。"""
    __tablename__ = "fruits"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    category = db.Column(db.String(64))
    price = db.Column(db.Float)
    origin = db.Column(db.String(128))  # 产地
