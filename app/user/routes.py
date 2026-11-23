"""用户端路由（组长负责）。

模块：浏览分类、商品详情、购物车、下单支付、订单、售后，
以及创新点：限时秒杀、智能推荐。
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta

from app.models import db, User, Fruit, Cart, Order, SeckillActivity, BrowseHistory
from app.user.seckill_service import seckill_service
from app.user.recommend_service import recommend_service

# 待支付订单的支付超时时间（分钟），超时自动取消
PAY_TIMEOUT_MINUTES = 15

user_bp = Blueprint("user", __name__, url_prefix="/user")


def current_user_id():
    return session.get("user_id")


@user_bp.route("/")
def home():
    # 大分类筛选（默认"水果"）
    category = request.args.get("category", "水果")
    # 细分类筛选（可选）
    sub = request.args.get("sub", "")

    query = Fruit.query.filter_by(is_on_sale=True, category=category)
    if sub:
        query = query.filter_by(sub_category=sub)
    fruits = query.all()

    # 该大分类下的所有细分类（用于左侧二级导航）
    all_sub_cats = [
        row[0] for row in
        db.session.query(Fruit.sub_category)
        .filter(Fruit.category == category, Fruit.is_on_sale == True)
        .distinct().all()
    ]

    # 所有大分类（用于顶部一级导航）
    all_categories = [
        row[0] for row in db.session.query(Fruit.category).distinct().all()
    ]

    # 秒杀活动
    seckills = SeckillActivity.query.filter_by(status="进行中").all()

    # 个性化推荐：按销量 + 浏览历史综合推荐
    recommends = recommend_service.recommend_for_user(current_user_id(), limit=6)

    return render_template(
        "user/home.html",
        fruits=fruits,
        seckills=seckills,
        recommends=recommends,
        all_categories=all_categories,
        all_sub_cats=all_sub_cats,
        current_category=category,
        current_sub=sub,
    )


# ---------------- 秒杀（创新点） ----------------

@user_bp.route("/seckill")
def seckill():
    """限时秒杀专区。"""
    seckills = SeckillActivity.query.all()
    # 计算每个活动的真实剩余库存（从 seckill_service 的内存/Redis 里取）
    result = []
    for s in seckills:
        remaining = seckill_service.get_remaining_stock(s.id)
        result.append({"activity": s, "remaining": remaining})
    return render_template("user/seckill.html", seckill_list=result)


@user_bp.route("/seckill/<int:activity_id>/buy", methods=["POST"])
def seckill_buy(activity_id):
    """抢购接口。"""
    if current_user_id() is None:
        flash("请先登录", "error")
        return redirect(url_for("auth.login"))

    result = seckill_service.seckill(activity_id, current_user_id())

    if result == "SUCCESS":
        # 生成秒杀订单
        activity = SeckillActivity.query.get(activity_id)
        fruit = Fruit.query.get(activity.fruit_id)
        order = Order(
            user_id=current_user_id(),
            fruit_id=activity.fruit_id,
            quantity=1,
            total_price=activity.seckill_price,
            status="待支付",
            is_seckill=True,
            pay_deadline=datetime.now() + timedelta(minutes=PAY_TIMEOUT_MINUTES),
        )
        db.session.add(order)
        db.session.commit()
        flash("🎉 抢购成功！请尽快支付", "success")
    elif result == "REPEAT_BUY":
        flash("你已抢过该商品（限购）", "error")
    else:
        flash("手慢了，已售罄", "error")

    return redirect(url_for("user.seckill"))


# ---------------- 商品浏览与详情 ----------------

@user_bp.route("/fruit/<int:fruit_id>")
def fruit_detail(fruit_id):
    """商品详情 + 记录浏览历史（给推荐用）。"""
    fruit = Fruit.query.get_or_404(fruit_id)
    if current_user_id():
        history = BrowseHistory(user_id=current_user_id(), fruit_id=fruit_id)
        db.session.add(history)
        db.session.commit()
    return render_template("user/fruit_detail.html", fruit=fruit)


# ---------------- 购物车 ----------------

@user_bp.route("/cart")
def cart():
    """购物车列表。"""
    items = Cart.query.filter_by(user_id=current_user_id()).all() if current_user_id() else []
    total = sum(item.fruit.price * item.quantity for item in items)
    return render_template("user/cart.html", items=items, total=total)


@user_bp.route("/cart/add/<int:fruit_id>", methods=["POST"])
def cart_add(fruit_id):
    """加入购物车（可指定数量，默认1）。"""
    if current_user_id() is None:
        flash("请先登录", "error")
        return redirect(url_for("auth.login"))
    try:
        quantity = int(request.form.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    if quantity < 1:
        quantity = 1

    item = Cart.query.filter_by(user_id=current_user_id(), fruit_id=fruit_id).first()
    if item:
        item.quantity += quantity
    else:
        item = Cart(user_id=current_user_id(), fruit_id=fruit_id, quantity=quantity)
        db.session.add(item)
    db.session.commit()
    flash(f"已加入购物车 ×{quantity}", "success")
    return redirect(request.referrer or url_for("user.cart"))


@user_bp.route("/cart/update/<int:item_id>/<action>", methods=["POST"])
def cart_update(item_id, action):
    """增减购物车商品数量。action: inc(加1) / dec(减1)。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    item = Cart.query.filter_by(id=item_id, user_id=current_user_id()).first()
    if item:
        if action == "inc":
            item.quantity += 1
        elif action == "dec":
            item.quantity -= 1
            if item.quantity <= 0:
                db.session.delete(item)
        db.session.commit()
    return redirect(url_for("user.cart"))


@user_bp.route("/cart/remove/<int:item_id>", methods=["POST"])
def cart_remove(item_id):
    """删除购物车商品。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    item = Cart.query.filter_by(id=item_id, user_id=current_user_id()).first()
    if item:
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("user.cart"))


# ---------------- 下单 ----------------

@user_bp.route("/checkout", methods=["POST"])
def checkout():
    """从购物车下单。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    items = Cart.query.filter_by(user_id=current_user_id()).all()
    for item in items:
        fruit = Fruit.query.get(item.fruit_id)
        order = Order(
            user_id=current_user_id(),
            fruit_id=item.fruit_id,
            quantity=item.quantity,
            total_price=fruit.price * item.quantity,
            status="待支付",
            pay_deadline=datetime.now() + timedelta(minutes=PAY_TIMEOUT_MINUTES),
        )
        db.session.add(order)
        db.session.delete(item)
    db.session.commit()
    flash("下单成功！请尽快支付", "success")
    return redirect(url_for("user.orders"))


# ---------------- 订单 ----------------

def _cancel_if_expired(order):
    """待支付订单超时自动取消。返回订单当前状态。"""
    if order.status == "待支付" and order.pay_deadline and datetime.now() > order.pay_deadline:
        order.status = "已取消"
        db.session.commit()
    return order.status


@user_bp.route("/orders")
def orders():
    """我的订单（进入时自动取消超时未支付订单）。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    my_orders = Order.query.filter_by(user_id=current_user_id()).order_by(Order.created_at.desc()).all()
    for o in my_orders:
        _cancel_if_expired(o)
    return render_template("user/orders.html", orders=my_orders, timeout_minutes=PAY_TIMEOUT_MINUTES)


@user_bp.route("/order/<int:order_id>/cancel", methods=["POST"])
def order_cancel(order_id):
    """取消订单（仅待支付可取消）。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    order = Order.query.filter_by(id=order_id, user_id=current_user_id()).first()
    if order and order.status == "待支付":
        order.status = "已取消"
        db.session.commit()
        flash("订单已取消", "success")
    else:
        flash("该订单无法取消", "error")
    return redirect(url_for("user.orders"))


@user_bp.route("/order/<int:order_id>/pay", methods=["POST"])
def order_pay(order_id):
    """支付单个订单（模拟支付，待支付 → 待发货）。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    order = Order.query.filter_by(id=order_id, user_id=current_user_id()).first()
    if order and order.status == "待支付":
        if order.pay_deadline and datetime.now() > order.pay_deadline:
            order.status = "已取消"
            db.session.commit()
            flash("订单已超时，请重新下单", "error")
        else:
            order.status = "待发货"
            db.session.commit()
            flash("支付成功！等待商家发货", "success")
    else:
        flash("该订单无法支付", "error")
    return redirect(url_for("user.orders"))


@user_bp.route("/order/batch-pay", methods=["POST"])
def order_batch_pay():
    """批量支付选中的待支付订单。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    ids = request.form.getlist("order_ids")
    if not ids:
        flash("请先勾选要支付的订单", "error")
        return redirect(url_for("user.orders"))

    paid = 0
    expired = 0
    for oid in ids:
        try:
            oid_int = int(oid)
        except (TypeError, ValueError):
            continue
        order = Order.query.filter_by(id=oid_int, user_id=current_user_id()).first()
        if not order or order.status != "待支付":
            continue
        if order.pay_deadline and datetime.now() > order.pay_deadline:
            order.status = "已取消"
            expired += 1
        else:
            order.status = "待发货"
            paid += 1
    db.session.commit()
    if paid:
        flash(f"成功支付 {paid} 笔订单", "success")
    if expired:
        flash(f"{expired} 笔订单已超时被取消", "error")
    if not paid and not expired:
        flash("没有可支付的订单", "error")
    return redirect(url_for("user.orders"))
