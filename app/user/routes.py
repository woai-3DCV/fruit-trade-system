"""用户端路由（组长负责）。

模块：浏览分类、商品详情、购物车、下单支付、售后，以及创新点：限时秒杀、智能推荐。
"""
from flask import Blueprint

user_bp = Blueprint("user", __name__, url_prefix="/user")


@user_bp.route("/")
def home():
    return "用户端首页"
