"""认证模块 —— 注册、登录、退出（组长负责，共享）。"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from app.models import db, User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "")

        user = User.query.filter_by(username=username).first()
        if user is None or not check_password_hash(user.password_hash, password):
            flash("用户名或密码错误", "error")
            return redirect(url_for("auth.login"))

        if user.role != role:
            flash("该账号的身份与所选身份不符", "error")
            return redirect(url_for("auth.login"))

        # 登录成功，写入 session
        session["user_id"] = user.id
        session["username"] = user.username
        session["role"] = user.role
        session["nickname"] = user.nickname or user.username

        # 根据身份跳转到对应端
        role_index = {
            "user": "user.home",
            "merchant": "merchant.home",
            "admin": "admin.home",
            "logistics": "logistics.home",
        }
        return redirect(url_for(role_index.get(user.role, "user.home")))

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
