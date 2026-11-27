"""用户端路由（组长负责）。

模块：浏览分类、商品详情、购物车、下单支付、订单、售后，
以及创新点：限时秒杀、智能推荐。
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

from app.models import db, User, Fruit, Cart, Order, SeckillActivity, BrowseHistory, Address, Message, AfterSale, Review
from app.user.seckill_service import seckill_service
from app.user.recommend_service import recommend_service
from app.user import ai_service

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
    # 搜索关键词（可选）
    keyword = (request.args.get("q") or "").strip()

    query = Fruit.query.filter_by(is_on_sale=True)
    if category and category != "全部":
        query = query.filter_by(category=category)
    if sub:
        query = query.filter_by(sub_category=sub)
    if keyword:
        # 按名称/产地/细分分类模糊搜索
        like = f"%{keyword}%"
        query = query.filter(
            db.or_(Fruit.name.like(like), Fruit.origin.like(like), Fruit.sub_category.like(like))
        )
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
        keyword=keyword,
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
        # 售罄时，若库存扣减因数据库一致性问题失败，回滚内存标记
        flash("手慢了，已售罄", "error")

    return redirect(url_for("user.seckill"))


# ---------------- 商品浏览与详情 ----------------

@user_bp.route("/fruit/<int:fruit_id>")
def fruit_detail(fruit_id):
    """商品详情 + 记录浏览历史（给推荐用）。"""
    fruit = Fruit.query.get_or_404(fruit_id)
    if current_user_id():
        # 浏览历史：同一商品只保留最近一次浏览（更新时间），避免无限膨胀
        existing = BrowseHistory.query.filter_by(
            user_id=current_user_id(), fruit_id=fruit_id
        ).first()
        if existing:
            existing.viewed_at = datetime.now()
        else:
            db.session.add(BrowseHistory(user_id=current_user_id(), fruit_id=fruit_id))
        db.session.commit()
    # 商品评价列表 + 平均分
    reviews = Review.query.filter_by(fruit_id=fruit_id).order_by(Review.created_at.desc()).all()
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 0
    # 商品的商家（用于「咨询商家」按钮）
    merchant = _resolve_merchant(fruit)
    return render_template(
        "user/fruit_detail.html", fruit=fruit, reviews=reviews, avg_rating=avg_rating,
        merchant=merchant,
    )


@user_bp.route("/fruit/<int:fruit_id>/review", methods=["POST"])
def fruit_review(fruit_id):
    """提交商品评价（对已完成订单）。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    try:
        rating = int(request.form.get("rating", 5))
    except (TypeError, ValueError):
        rating = 5
    rating = max(1, min(5, rating))
    content = (request.form.get("content") or "").strip()

    # 校验：该用户有已完成订单才允许评价（简化：登录即可评，但记录 order_id 可选）
    order_id = request.form.get("order_id")
    review = Review(
        user_id=user.id,
        fruit_id=fruit_id,
        order_id=int(order_id) if order_id else None,
        rating=rating,
        content=content,
    )
    db.session.add(review)
    db.session.commit()
    flash("评价已发布，感谢你的反馈！", "success")
    return redirect(url_for("user.fruit_detail", fruit_id=fruit_id))


# ---------------- 购物车 ----------------

@user_bp.route("/cart")
def cart():
    """购物车列表。"""
    items = Cart.query.filter_by(user_id=current_user_id()).all() if current_user_id() else []
    # 过滤掉商品已下架/删除的条目，只统计有效商品
    valid_items = [i for i in items if i.fruit and i.fruit.is_on_sale]
    total = sum(i.fruit.price * i.quantity for i in valid_items)
    return render_template("user/cart.html", items=valid_items, total=total)


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
        # 只结算在售商品
        items = [i for i in items if i.fruit and i.fruit.is_on_sale]
        if not items:
            flash("购物车是空的", "error")
            return redirect(url_for("user.cart"))
        total = sum(item.fruit.price * item.quantity for item in items)
        addresses = Address.query.filter_by(user_id=current_user_id()).order_by(Address.is_default.desc(), Address.id.desc()).all()
        return render_template("user/checkout.html", items=items, total=total, addresses=addresses)

    # POST：下单
    items = Cart.query.filter_by(user_id=current_user_id()).all()
    # 只结算在售商品
    items = [i for i in items if i.fruit and i.fruit.is_on_sale]
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


# ---------------- 私信商家（咨询） ----------------

def _resolve_merchant(fruit):
    """确定商品的商家：优先 fruit.merchant_id，否则回退到第一个 merchant 账号。"""
    if fruit and fruit.merchant_id:
        m = User.query.get(fruit.merchant_id)
        if m:
            return m
    return User.query.filter_by(role="merchant").first()


@user_bp.route("/chat")
def chat_list():
    """我的咨询会话列表（按商家/商品聚合）。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    # 取出我参与的所有会话，按商家+商品分组
    my_msgs = Message.query.filter_by(user_id=user.id).order_by(Message.created_at.desc()).all()
    # 按 (merchant_id, fruit_id) 聚合
    sessions = {}
    for m in my_msgs:
        key = (m.merchant_id, m.fruit_id or 0)
        if key not in sessions:
            merchant = User.query.get(m.merchant_id)
            fruit = Fruit.query.get(m.fruit_id) if m.fruit_id else None
            sessions[key] = {
                "merchant": merchant,
                "fruit": fruit,
                "last": m,
            }
    return render_template("user/chat_list.html", sessions=sessions.values())


@user_bp.route("/chat/<int:merchant_id>")
@user_bp.route("/chat/<int:merchant_id>/<int:fruit_id>")
def chat_detail(merchant_id, fruit_id=None):
    """与某商家的聊天窗口（可按商品区分）。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    merchant = User.query.get(merchant_id)
    fruit = Fruit.query.get(fruit_id) if fruit_id else None
    q = Message.query.filter_by(user_id=user.id, merchant_id=merchant_id)
    if fruit_id:
        q = q.filter_by(fruit_id=fruit_id)
    msgs = q.order_by(Message.created_at.asc()).all()
    return render_template("user/chat.html", merchant=merchant, fruit=fruit, msgs=msgs)


@user_bp.route("/chat/<int:merchant_id>/send", methods=["POST"])
@user_bp.route("/chat/<int:merchant_id>/<int:fruit_id>/send", methods=["POST"])
def chat_send(merchant_id, fruit_id=None):
    """用户发送私信给商家。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    content = (request.form.get("content") or "").strip()
    if not content:
        flash("消息不能为空", "error")
        return redirect(request.referrer or url_for("user.chat_list"))
    msg = Message(
        user_id=user.id,
        merchant_id=merchant_id,
        fruit_id=fruit_id,
        sender_role="user",
        content=content,
    )
    db.session.add(msg)
    db.session.commit()
    return redirect(url_for("user.chat_detail", merchant_id=merchant_id, fruit_id=fruit_id) if fruit_id
                    else url_for("user.chat_detail", merchant_id=merchant_id))


# ---------------- 订单详情 ----------------

@user_bp.route("/order/<int:order_id>/detail")
def order_detail(order_id):
    """订单详情（JSON，供前端弹窗/展开）。"""
    user = _require_login()
    if user is None:
        return {"error": "请先登录"}, 401
    order = Order.query.filter_by(id=order_id, user_id=user.id).first()
    if not order:
        return {"error": "订单不存在"}, 404

    fruit = order.fruit
    # 尝试读取物流信息（若物流端已录入）
    logistics = None
    from app.models import Logistics
    logi = Logistics.query.filter_by(order_id=order.id).first()
    if logi:
        logistics = {
            "status": logi.status,
            "courier": logi.courier,
            "current_location": logi.current_location,
        }

    return {
        "id": order.id,
        "status": order.status,
        "is_seckill": order.is_seckill,
        "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "paid_at": order.paid_at.strftime("%Y-%m-%d %H:%M:%S") if order.paid_at else None,
        "pay_deadline": order.pay_deadline.strftime("%Y-%m-%d %H:%M:%S") if order.pay_deadline else None,
        "address": order.address,
        "payment_method": order.payment_method,
        "total_price": order.total_price,
        "quantity": order.quantity,
        "fruit_name": fruit.name if fruit else "",
        "fruit_emoji": fruit.emoji if fruit else "🍓",
        "fruit_origin": fruit.origin if fruit else "",
        "logistics": logistics,
    }


# ---------------- 售后 ----------------

@user_bp.route("/aftersale")
def aftersale_list():
    """我的售后申请列表。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    records = AfterSale.query.filter_by(user_id=user.id).order_by(AfterSale.created_at.desc()).all()
    return render_template("user/aftersale.html", records=records)


@user_bp.route("/order/<int:order_id>/aftersale/apply", methods=["POST"])
def aftersale_apply(order_id):
    """对某订单发起售后申请（退款/退货）。"""
    user = _require_login()
    if user is None:
        return redirect(url_for("auth.login"))
    order = Order.query.filter_by(id=order_id, user_id=user.id).first()
    if not order:
        flash("订单不存在", "error")
        return redirect(url_for("user.orders"))

    # 只允许对已支付/已完成/待发货等非取消订单申请售后
    if order.status in ("已取消", "待支付"):
        flash("该订单状态无法申请售后", "error")
        return redirect(url_for("user.orders"))

    # 已申请过则拒绝重复
    existing = AfterSale.query.filter_by(order_id=order.id).first()
    if existing:
        flash("该订单已申请过售后", "error")
        return redirect(url_for("user.aftersale_list"))

    atype = request.form.get("type", "退款")
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("请填写申请原因", "error")
        return redirect(url_for("user.orders"))

    record = AfterSale(order_id=order.id, user_id=user.id, type=atype, reason=reason)
    db.session.add(record)
    db.session.commit()
    flash("售后申请已提交，商家会尽快处理", "success")
    return redirect(url_for("user.aftersale_list"))


AI_QUICK_QUESTIONS = ["怎么参加秒杀？", "有什么优惠吗？", "怎么退款？", "怎么改收货地址？", "支持哪些支付方式？", "帮我推荐水果"]


@user_bp.route("/ai")
def ai_assistant():
    """AI 智能助手页面（悬浮球点开后的独立窗口，也支持独立访问）。"""
    return render_template("user/ai.html", quick_questions=AI_QUICK_QUESTIONS, ai_configured=ai_service.is_configured())


@user_bp.route("/ai/ask", methods=["POST"])
def ai_ask():
    """AI 助手问答（优先 DeepSeek 大模型，失败降级关键词匹配）。

    请求体：question（必填），history（可选 JSON 数组 [{role, content}]）
    """
    question = (request.form.get("question") or "").strip()
    if not question:
        return {"answer": "请先输入问题哦～"}, 400

    # 解析多轮历史
    history = None
    raw_history = request.form.get("history")
    if raw_history:
        import json as _json
        try:
            history = _json.loads(raw_history)
        except Exception:
            history = None

    answer, used_ai = ai_service.chat(question, history=history)

    # 大模型答不上时，兜底推荐热门水果
    if not used_ai and answer.startswith("这个问题我还没学会"):
        hot = Fruit.query.filter_by(is_on_sale=True).order_by(Fruit.sales.desc()).limit(3).all()
        if hot:
            names = "、".join(f"{f.emoji}{f.name}(¥{f.price})" for f in hot)
            answer = f"可以看看这些热销水果：{names}。也可以私信商家咨询哦～"

    return {"answer": answer, "used_ai": used_ai}
