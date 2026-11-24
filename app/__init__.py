"""Flask 应用工厂 —— 共享文件，修改前先在群里说。"""
import os
from flask import Flask, render_template


def create_app():
    # 模板和静态文件放在项目根目录（而不是 app/ 包里）
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, "templates"),
        static_folder=os.path.join(base_dir, "static"),
    )
    app.config["SECRET_KEY"] = "dev-secret-key"

    # 数据库配置（SQLite，本地文件，零安装）
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///fruit.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    from app.models import db
    db.init_app(app)

    # 注册蓝图
    from app.auth import auth_bp
    app.register_blueprint(auth_bp)

    from app.user.routes import user_bp
    app.register_blueprint(user_bp)
    from app.merchant.routes import merchant_bp
    app.register_blueprint(merchant_bp)
    from app.admin.routes import admin_bp
    app.register_blueprint(admin_bp)
    from app.logistics.routes import logistics_bp
    app.register_blueprint(logistics_bp)

    # 启动秒杀异步下单消费线程（秒杀抢购成功后由它异步建单）
    from app.user.seckill_service import seckill_service
    seckill_service.start_consumer()

    @app.route("/")
    def index():
        return render_template("login.html")

    return app
