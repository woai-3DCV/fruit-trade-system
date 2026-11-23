"""初始化脚本 —— 建库 + 创建四个身份的测试账号。

用法（在项目根目录执行）：
    python init_db.py

会创建 4 个账号：
    普通用户：  user  / 123456
    商家：      merchant / 123456
    平台管理员：admin / admin123
    物流配送：  logistics / 123456
"""
import sys
import io

# Windows 控制台中文/编码兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import create_app
from app.models import db, User
from werkzeug.security import generate_password_hash


def init():
    app = create_app()
    with app.app_context():
        db.create_all()  # 建表

        # 预置四个身份的账号（已存在则跳过）
        accounts = [
            ("user", "123456", "user", "普通用户"),
            ("merchant", "123456", "merchant", "商家"),
            ("admin", "admin123", "admin", "平台管理员"),
            ("logistics", "123456", "logistics", "物流配送"),
        ]
        for username, password, role, label in accounts:
            if User.query.filter_by(username=username).first() is None:
                u = User(
                    username=username,
                    password_hash=generate_password_hash(password),
                    role=role,
                )
                db.session.add(u)
                print(f"已创建账号：{label} -> 用户名 {username} / 密码 {password}")
            else:
                print(f"账号已存在，跳过：{username}")

        db.session.commit()
        print("\n初始化完成！")


if __name__ == "__main__":
    init()
