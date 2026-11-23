"""用户端路由（组长负责）。

模块：浏览分类、商品详情、购物车、下单支付、售后，以及创新点：限时秒杀、智能推荐。
"""
from flask import Blueprint, render_template

user_bp = Blueprint("user", __name__, url_prefix="/user")


@user_bp.route("/")
def home():
    return render_template("user/home.html")


@user_bp.route("/seckill")
def seckill():
    """限时秒杀专区（创新点）。"""
    return render_template("user/seckill.html")
