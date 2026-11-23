"""物流端路由（D 负责）。

模块：配送任务、物流追踪，以及创新点：冷链温控追踪、运输异常预警。
"""
from flask import Blueprint, render_template

logistics_bp = Blueprint("logistics", __name__, url_prefix="/logistics")


@logistics_bp.route("/")
def home():
    return render_template("logistics/home.html")
