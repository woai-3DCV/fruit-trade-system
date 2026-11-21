"""平台管理端路由（C 负责）。

模块：审核商家资质、管理用户、处理投诉，以及创新点：商家信用评分、数据大屏。
"""
from flask import Blueprint

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
def home():
    return "平台管理端首页"
