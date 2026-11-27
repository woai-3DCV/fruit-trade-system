"""商家端路由（B 负责）。

模块：上架/下架、库存管理、发货、售后、报表，以及创新点：库存损耗预警、批次管理。
"""
from flask import Blueprint, render_template

merchant_bp = Blueprint("merchant", __name__, url_prefix="/merchant")


@merchant_bp.route("/")
def home():
    return render_template("merchant/home.html")
