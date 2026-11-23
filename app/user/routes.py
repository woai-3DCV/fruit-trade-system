"""用户端路由（组长负责）。

模块：浏览分类、商品详情、购物车、下单支付、订单、售后，
以及创新点：限时秒杀、智能推荐。
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

from app.models import db, User, Fruit, Cart, Order, SeckillActivity, BrowseHistory, Address
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
        # 生成秒杀订单（收货地址取默认地址，没有则留空）
        activity = SeckillActivity.query.get(activity_id)
        fruit = Fruit.query.get(activity.fruit_id)
        addr = Address.query.filter_by(user_id=current_user_id(), is_default=True).first()
        addr_snapshot = f"{addr.receiver} {addr.phone} {addr.detail}" if addr else ""
        order = Order(
            user_id=current_user_id(),
            fruit_id=activity.fruit_id,
            quantity=1,
            total_price=activity.seckill_price,
            status="待支付",
            is_seckill=True,
            pay_deadline=datetime.now() + timedelta(minutes=PAY_TIMEOUT_MINUTES),
            address=addr_snapshot,
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

@user_bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    """确认订单：GET 选收货地址，POST 真正下单。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        items = Cart.query.filter_by(user_id=current_user_id()).all()
        if not items:
            flash("购物车是空的", "error")
            return redirect(url_for("user.cart"))
        total = sum(item.fruit.price * item.quantity for item in items)
        addresses = Address.query.filter_by(user_id=current_user_id()).order_by(Address.is_default.desc(), Address.id.desc()).all()
        return render_template("user/checkout.html", items=items, total=total, addresses=addresses)

    # POST：下单
    items = Cart.query.filter_by(user_id=current_user_id()).all()
    if not items:
        flash("购物车是空的", "error")
        return redirect(url_for("user.cart"))

    # 收货地址：优先用户选的地址，否则默认地址，否则提示
    addr_id = request.form.get("address_id")
    address = None
    if addr_id:
        address = Address.query.filter_by(id=int(addr_id), user_id=current_user_id()).first()
    if address is None:
        address = Address.query.filter_by(user_id=current_user_id(), is_default=True).first()
    if address is None:
        flash("请先添加收货地址", "error")
        return redirect(url_for("user.profile"))
    address_snapshot = f"{address.receiver} {address.phone} {address.detail}"

    for item in items:
        fruit = Fruit.query.get(item.fruit_id)
        order = Order(
            user_id=current_user_id(),
            fruit_id=item.fruit_id,
            quantity=item.quantity,
            total_price=fruit.price * item.quantity,
            status="待支付",
            pay_deadline=datetime.now() + timedelta(minutes=PAY_TIMEOUT_MINUTES),
            address=address_snapshot,
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
    """我的订单（进入时自动取消超时未支付订单），支持按状态筛选。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))

    # 先取消超时订单
    all_orders = Order.query.filter_by(user_id=current_user_id()).order_by(Order.created_at.desc()).all()
    for o in all_orders:
        _cancel_if_expired(o)

    # 状态筛选
    status = request.args.get("status", "全部")
    if status != "全部":
        my_orders = Order.query.filter_by(user_id=current_user_id(), status=status).order_by(Order.created_at.desc()).all()
    else:
        my_orders = all_orders

    # 各状态数量（用于标签页显示）
    status_counts = {}
    for s in ["全部", "待支付", "待发货", "待收货", "已完成", "已取消"]:
        if s == "全部":
            status_counts[s] = Order.query.filter_by(user_id=current_user_id()).count()
        else:
            status_counts[s] = Order.query.filter_by(user_id=current_user_id(), status=s).count()

    return render_template(
        "user/orders.html",
        orders=my_orders,
        current_status=status,
        status_counts=status_counts,
        timeout_minutes=PAY_TIMEOUT_MINUTES,
    )


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


@user_bp.route("/order/<int:order_id>/pay", methods=["POST", "GET"])
def order_pay(order_id):
    """进入支付方式选择页（待支付订单）。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    order = Order.query.filter_by(id=order_id, user_id=current_user_id()).first()
    if not order:
        flash("订单不存在", "error")
        return redirect(url_for("user.orders"))
    if order.status != "待支付":
        flash("该订单当前状态不可支付", "error")
        return redirect(url_for("user.orders"))
    if order.pay_deadline and datetime.now() > order.pay_deadline:
        order.status = "已取消"
        db.session.commit()
        flash("订单已超时，请重新下单", "error")
        return redirect(url_for("user.orders"))
    return render_template("user/pay.html", order=order)


@user_bp.route("/order/<int:order_id>/pay/confirm", methods=["POST"])
def order_pay_confirm(order_id):
    """确认支付（选择支付方式后跳转模拟支付，确认后完成支付）。"""
    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    order = Order.query.filter_by(id=order_id, user_id=current_user_id()).first()
    if not order or order.status != "待支付":
        flash("该订单无法支付", "error")
        return redirect(url_for("user.orders"))
    if order.pay_deadline and datetime.now() > order.pay_deadline:
        order.status = "已取消"
        db.session.commit()
        flash("订单已超时，请重新下单", "error")
        return redirect(url_for("user.orders"))

    method = request.form.get("payment_method", "余额")
    order.payment_method = method
    order.paid_at = datetime.now()
    order.status = "待发货"
    db.session.commit()
    flash(f"支付成功！（{method}）等待商家发货", "success")
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


# ---------------- 个人中心 ----------------

def _require_login():
    """未登录则返回 None，已登录返回 user 对象。"""
    if current_user_id() is None:
        return None
    return User.query.get(current_user_id())


@user_bp.route("/profile")
def profile():
    """个人中心：基础资料 + 收货地址。"""
    user = _require_login()
    if user is None:
        flash("请先登录", "error")
        return redirect(url_for("auth.login"))
    addresses = Address.query.filter_by(user_id=user.id).order_by(Address.is_default.desc(), Address.id.desc()).all()
    return render_template("user/profile.html", user=user, addresses=addresses)


@user_bp.route("/profile/update", methods=["POST"])
def profile_update():
    """更新基础资料（昵称/手机/性别/头像）。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    user.nickname = request.form.get("nickname", "").strip() or user.username
    user.phone = request.form.get("phone", "").strip()
    user.gender = request.form.get("gender", "保密")
    db.session.commit()
    flash("资料已更新", "success")
    return redirect(url_for("user.profile"))


@user_bp.route("/profile/avatar", methods=["POST"])
def profile_avatar():
    """上传头像（拍照/相册，前端转 base64 后提交）。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    avatar_data = request.form.get("avatar_data", "").strip()
    if avatar_data and avatar_data.startswith("data:image"):
        # 简单校验 + 限制大小（约 2MB）
        if len(avatar_data) > 2 * 1024 * 1024:
            flash("图片过大，请选择 2MB 以内的图片", "error")
        else:
            user.avatar_url = avatar_data
            db.session.commit()
            flash("头像已更新", "success")
    else:
        flash("未选择图片", "error")
    return redirect(url_for("user.profile"))


@user_bp.route("/profile/password", methods=["POST"])
def profile_password():
    """修改密码。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    old_pwd = request.form.get("old_password", "")
    new_pwd = request.form.get("new_password", "")
    if not check_password_hash(user.password_hash, old_pwd):
        flash("原密码错误", "error")
    elif len(new_pwd) < 6:
        flash("新密码至少 6 位", "error")
    else:
        user.password_hash = generate_password_hash(new_pwd)
        db.session.commit()
        flash("密码已修改，下次登录请用新密码", "success")
    return redirect(url_for("user.profile"))


# ---------------- 收货地址 ----------------

@user_bp.route("/address/add", methods=["POST"])
def address_add():
    """新增收货地址。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    receiver = request.form.get("receiver", "").strip()
    phone = request.form.get("phone", "").strip()
    detail = request.form.get("detail", "").strip()
    if not (receiver and phone and detail):
        flash("请填写完整的收货信息", "error")
        return redirect(url_for("user.profile"))
    addr = Address(user_id=user.id, receiver=receiver, phone=phone, detail=detail,
                   is_default=(Address.query.filter_by(user_id=user.id).count() == 0))
    db.session.add(addr)
    db.session.commit()
    flash("地址已添加", "success")
    return redirect(url_for("user.profile"))


@user_bp.route("/address/<int:addr_id>/delete", methods=["POST"])
def address_delete(addr_id):
    """删除收货地址。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    addr = Address.query.filter_by(id=addr_id, user_id=user.id).first()
    if addr:
        was_default = addr.is_default
        db.session.delete(addr)
        db.session.commit()
        # 若删的是默认地址，把最新一个设为默认
        if was_default:
            remain = Address.query.filter_by(user_id=user.id).order_by(Address.id.desc()).first()
            if remain:
                remain.is_default = True
                db.session.commit()
        flash("地址已删除", "success")
    return redirect(url_for("user.profile"))


@user_bp.route("/address/<int:addr_id>/default", methods=["POST"])
def address_set_default(addr_id):
    """设为默认地址。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    Address.query.filter_by(user_id=user.id).update({"is_default": False})
    addr = Address.query.filter_by(id=addr_id, user_id=user.id).first()
    if addr:
        addr.is_default = True
    db.session.commit()
    flash("已设为默认地址", "success")
    return redirect(url_for("user.profile"))
