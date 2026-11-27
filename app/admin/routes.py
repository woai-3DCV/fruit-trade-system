"""平台管理端：商家资质审核、账号管理、投诉处理与运营概览。"""
from functools import wraps
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from app.models import Complaint, MerchantQualification, Order, User, db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@admin_bp.route("/")
@admin_required
def home():
    complaints = Complaint.query.order_by(Complaint.id.desc()).limit(5).all()
    days = request.args.get("days", "30")
    if days not in ("7", "30", "90"):
        days = "30"
    since = datetime.now() - timedelta(days=int(days) - 1)
    user_daily = db.session.query(db.func.date(User.created_at), db.func.count(User.id)).filter(User.created_at >= since, User.role == "user").group_by(db.func.date(User.created_at)).all()
    order_daily = db.session.query(db.func.date(Order.created_at), db.func.count(Order.id)).filter(Order.created_at >= since).group_by(db.func.date(Order.created_at)).all()
    stats = {
        "users": User.query.filter_by(role="user").count(),
        "merchants": User.query.filter_by(role="merchant").count(),
        "pending_qualifications": MerchantQualification.query.filter_by(status="待审核").count(),
        "pending_complaints": Complaint.query.filter_by(status="待处理").count(),
        "resolved_complaints": Complaint.query.filter_by(status="已处理").count(),
        "approved_qualifications": MerchantQualification.query.filter_by(status="通过").count(),
        "rejected_qualifications": MerchantQualification.query.filter_by(status="驳回").count(),
        "logistics": User.query.filter_by(role="logistics").count(),
        "orders": Order.query.count(),
        "revenue": db.session.query(db.func.coalesce(db.func.sum(Order.total_price), 0)).filter(Order.status.in_(["已完成", "运输中"])).scalar() or 0,
    }
    user_counts = {str(day): count for day, count in user_daily}
    order_counts = {str(day): count for day, count in order_daily}
    chart_days = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(int(days))]
    chart_data = {
        "days": chart_days,
        "users": [user_counts.get(day, 0) for day in chart_days],
        "orders": [order_counts.get(day, 0) for day in chart_days],
    }
    complainants = {u.id: u for u in User.query.filter(User.id.in_([c.user_id for c in complaints if c.user_id])).all()} if complaints else {}
    return render_template("admin/home.html", stats=stats, complaints=complaints, complainants=complainants, days=days, chart_data=chart_data)


@admin_bp.route("/review")
@admin_required
def review_center():
    return redirect(url_for("admin.qualifications"))


@admin_bp.route("/qualifications")
@admin_required
def qualifications():
    status = request.args.get("status", "全部")
    keyword = request.args.get("q", "").strip()
    query = MerchantQualification.query
    if status in ("待审核", "通过", "驳回"):
        query = query.filter_by(status=status)
    rows = query.order_by(MerchantQualification.id.desc()).all()
    merchants = {u.id: u for u in User.query.filter(User.id.in_([r.merchant_id for r in rows])).all()} if rows else {}
    if keyword:
        needle = keyword.lower()
        rows = [r for r in rows if needle in ((merchants[r.merchant_id].username or "").lower() if r.merchant_id in merchants else "") or needle in ((merchants[r.merchant_id].nickname or "").lower() if r.merchant_id in merchants else "") or needle in (r.license_no or "").lower()]
    return render_template("admin/qualifications.html", qualifications=rows, merchants=merchants, status=status, keyword=keyword)


@admin_bp.route("/qualification/<int:item_id>", methods=["POST"])
@admin_required
def review_qualification(item_id):
    item = MerchantQualification.query.get_or_404(item_id)
    decision = request.form.get("decision")
    if decision not in ("通过", "驳回"):
        abort(400)
    item.status = decision
    db.session.commit()
    flash(f"商家资质已{decision}", "success")
    return redirect(request.referrer or url_for("admin.qualifications"))


@admin_bp.route("/users")
@admin_required
def users():
    keyword = request.args.get("q", "").strip()
    role = request.args.get("role", "all")
    query = User.query.filter(User.role != "admin")
    if role in ("user", "merchant", "logistics"):
        query = query.filter_by(role=role)
    if keyword:
        query = query.filter(db.or_(User.username.contains(keyword), User.nickname.contains(keyword), User.phone.contains(keyword)))
    return render_template("admin/users.html", users=query.order_by(User.id.desc()).all(), keyword=keyword, role=role)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == "admin":
        abort(403)
    # 账号状态字段尚未纳入共享模型；用 session 标记演示启停状态，不改共享表结构。
    disabled = set(session.get("disabled_users", []))
    if user_id in disabled:
        disabled.remove(user_id)
        message = "账号已恢复"
    else:
        disabled.add(user_id)
        message = "账号已停用"
    session["disabled_users"] = list(disabled)
    flash(message, "success")
    return redirect(url_for("admin.users", role=request.form.get("role", "all"), q=request.form.get("q", "")))


@admin_bp.route("/complaints")
@admin_required
def complaints():
    keyword = request.args.get("q", "").strip()
    status = request.args.get("status", "全部")
    query = Complaint.query
    if status in ("待处理", "已处理"):
        query = query.filter_by(status=status)
    if keyword:
        query = query.filter(Complaint.content.contains(keyword))
    rows = query.order_by(Complaint.id.desc()).all()
    complainants = {u.id: u for u in User.query.filter(User.id.in_([c.user_id for c in rows if c.user_id])).all()} if rows else {}
    return render_template("admin/complaints.html", complaints=rows, complainants=complainants, keyword=keyword, status=status)


@admin_bp.route("/complaints/<int:complaint_id>/resolve", methods=["POST"])
@admin_required
def resolve_complaint(complaint_id):
    complaint = Complaint.query.get_or_404(complaint_id)
    complaint.status = "已处理"
    db.session.commit()
    flash("投诉已标记为处理完成", "success")
    return redirect(request.referrer or url_for("admin.complaints"))


