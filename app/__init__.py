"""Flask 应用工厂 —— 共享文件，修改前先在群里说。"""
from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev-secret-key"

    # 注册四个端的蓝图（各端负责人各自添加自己的蓝图）
    # from app.user.routes import user_bp
    # app.register_blueprint(user_bp)
    # from app.merchant.routes import merchant_bp
    # app.register_blueprint(merchant_bp)
    # from app.admin.routes import admin_bp
    # app.register_blueprint(admin_bp)
    # from app.logistics.routes import logistics_bp
    # app.register_blueprint(logistics_bp)

    @app.route("/")
    def index():
        return "水果交易智能管理系统"

    return app
