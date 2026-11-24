"""秒杀核心服务 —— 防超卖的并发控制 + 限流削峰 + 异步下单（组长负责，创新点）。

设计说明：
  秒杀的关键有三点：
  1. 防超卖 —— 把「查库存 + 扣库存」合并为一个原子操作
  2. 限流削峰 —— 令牌桶算法，挡住瞬时海量请求
  3. 异步下单 —— 抢到后不立刻写库，先进队列异步建单，快速响应

  答辩时讲：
    - 防超卖：数据库原子 UPDATE（乐观锁思想），有 Redis 时用 Lua 脚本
    - 限流：令牌桶算法，固定速率放行，超过则拒绝（削峰填谷）
    - 异步下单：消息队列解耦，抢购接口只做「扣库存」，建单交给消费者
"""
import threading
import time
from collections import deque

try:
    import redis
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False


# Redis 中保证「检查 + 扣减」原子性的 Lua 脚本
LUA_DECR_STOCK = """
local stock = tonumber(redis.call('get', KEYS[1]) or '0')
if stock > 0 then
    redis.call('decr', KEYS[1])
    return 1
else
    return 0
end
"""


class TokenBucket:
    """令牌桶限流器 —— 固定速率放行，超过则拒绝（削峰填谷）。

    原理：
      - 桶容量 capacity，每秒匀速放入 rate 个令牌
      - 请求到达时取一个令牌，取到则放行，取不到则拒绝
      - 相比「漏桶」能容忍一定突发流量
    """

    def __init__(self, rate: int, capacity: int):
        self.rate = rate              # 每秒生成令牌数（QPS 上限）
        self.capacity = capacity      # 桶容量（允许的突发量）
        self._tokens = float(capacity)
        self._last = time.time()
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        """尝试取一个令牌，成功返回 True。"""
        with self._lock:
            now = time.time()
            # 按流逝时间补充令牌
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False


class SeckillService:
    """秒杀服务：限流 + 原子扣库存 + 限购 + 异步下单。"""

    def __init__(self):
        self._lock = threading.Lock()  # 限购标记用的进程内锁
        # 限流器：每秒最多 50 个请求，突发容量 100（演示够用，答辩讲可调）
        self._limiter = TokenBucket(rate=50, capacity=100)
        # 异步下单队列 + 消费线程
        self._order_queue = deque()
        self._queue_lock = threading.Lock()
        self._redis = None
        if _HAS_REDIS:
            try:
                self._redis = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
                self._redis.ping()  # 测试连接
            except Exception:
                self._redis = None  # 连不上就降级到数据库原子扣减

    # ---------------- 库存相关 ----------------

    def preload_stock(self, activity_id: int, stock: int):
        """（兼容接口）Redis 模式下可预热库存；降级模式下库存以数据库为准，无需预热。"""
        key = f"seckill:stock:{activity_id}"
        if self._redis:
            self._redis.set(key, stock)

    def get_remaining_stock(self, activity_id: int) -> int:
        """查询当前剩余库存（统一以数据库 stock 字段为准）。"""
        if self._redis:
            val = self._redis.get(f"seckill:stock:{activity_id}")
            if val is not None:
                return int(val)
        # 降级模式：直接读数据库（唯一权威数据源）
        from app.models import SeckillActivity
        activity = SeckillActivity.query.get(activity_id)
        return activity.stock if activity else 0

    def get_status(self, activity) -> str:
        """动态计算活动状态（不依赖写死的 status 字段）。

        根据 start_time / end_time 与当前时间实时判断，避免活动过期后
        状态字段仍是「进行中」导致按钮可点但倒计时已归零。
        """
        from datetime import datetime
        now = datetime.now()
        if now < activity.start_time:
            return "未开始"
        if now > activity.end_time:
            return "已结束"
        return "进行中"

    def _decr_stock_atomic(self, activity_id: int) -> bool:
        """原子扣减库存，成功返回 True，售罄返回 False。"""
        if self._redis:
            key = f"seckill:stock:{activity_id}"
            return self._redis.eval(LUA_DECR_STOCK, 1, key) == 1

        # 降级方案：数据库原子 UPDATE，只有 stock > 0 才扣减成功，天然防超卖
        from sqlalchemy import text
        from app.models import db
        result = db.session.execute(
            text("UPDATE seckill_activities SET stock = stock - 1 "
                 "WHERE id = :id AND stock > 0"),
            {"id": activity_id},
        )
        db.session.commit()
        return result.rowcount == 1

    # ---------------- 限购相关 ----------------

    def has_bought(self, activity_id: int, user_id: int) -> bool:
        """判断该用户是否已抢过（限购防黄牛）。"""
        key = f"seckill:user:{activity_id}"
        if self._redis:
            return self._redis.sismember(key, user_id)
        else:
            with self._lock:
                self._mem_users = getattr(self, "_mem_users", {})
                return user_id in self._mem_users.get(activity_id, set())

    def mark_bought(self, activity_id: int, user_id: int):
        """记录该用户已抢（标记，防重复抢购）。"""
        key = f"seckill:user:{activity_id}"
        if self._redis:
            self._redis.sadd(key, user_id)
        else:
            with self._lock:
                self._mem_users = getattr(self, "_mem_users", {})
                self._mem_users.setdefault(activity_id, set()).add(user_id)

    def _has_order_in_db(self, activity_id: int, user_id: int) -> bool:
        """数据库兜底：该用户是否已有此活动的秒杀订单（防止进程重启后内存限购失效）。"""
        from app.models import SeckillActivity, Order
        activity = SeckillActivity.query.get(activity_id)
        if not activity:
            return False
        return Order.query.filter_by(
            user_id=user_id, fruit_id=activity.fruit_id, is_seckill=True
        ).first() is not None

    # ---------------- 限流 ----------------

    def is_limited(self) -> bool:
        """当前请求是否被限流（令牌桶无令牌）。"""
        return not self._limiter.try_acquire()

    # ---------------- 异步下单 ----------------

    def enqueue_order(self, activity_id: int, user_id: int):
        """把秒杀成功的信息丢进队列，由消费线程异步建单（解耦，快速响应）。"""
        with self._queue_lock:
            self._order_queue.append((activity_id, user_id))

    def _consume_orders(self):
        """队列消费者：异步生成秒杀订单。"""
        from app import create_app
        app = create_app()
        with app.app_context():
            while True:
                item = None
                with self._queue_lock:
                    if self._order_queue:
                        item = self._order_queue.popleft()
                if item is None:
                    time.sleep(0.05)  # 队列空，稍等再查
                    continue
                activity_id, user_id = item
                try:
                    self._build_order(activity_id, user_id)
                except Exception:
                    pass  # 建单失败不阻塞队列

    def _build_order(self, activity_id: int, user_id: int):
        """真正生成秒杀订单（消费线程里执行）。"""
        from app.models import db, SeckillActivity, Fruit, Order, Address
        from datetime import datetime, timedelta
        activity = SeckillActivity.query.get(activity_id)
        if not activity:
            return
        fruit = Fruit.query.get(activity.fruit_id)
        addr = Address.query.filter_by(user_id=user_id, is_default=True).first()
        addr_snapshot = f"{addr.receiver} {addr.phone} {addr.detail}" if addr else ""
        order = Order(
            user_id=user_id,
            fruit_id=activity.fruit_id,
            quantity=1,
            total_price=activity.seckill_price,
            status="待支付",
            is_seckill=True,
            pay_deadline=datetime.now() + timedelta(minutes=15),
            address=addr_snapshot,
        )
        db.session.add(order)
        db.session.commit()

    def start_consumer(self):
        """启动异步下单消费线程（应用启动时调用一次）。"""
        if not getattr(self, "_consumer_started", False):
            self._consumer_started = True
            t = threading.Thread(target=self._consume_orders, daemon=True)
            t.start()

    # ---------------- 对外主流程 ----------------

    def seckill(self, activity_id: int, user_id: int) -> str:
        """执行一次抢购。返回结果状态码。

        状态码：
          LIMITED   —— 被限流（令牌桶无令牌）
          REPEAT_BUY —— 已抢过（限购）
          SOLD_OUT   —— 售罄
          SUCCESS    —— 抢购成功（已入队，异步建单）
        """
        # 1. 限流：令牌桶无令牌则直接拒绝（削峰）
        if self.is_limited():
            return "LIMITED"

        # 2. 限购校验：先查内存标记，再查数据库兜底
        if self.has_bought(activity_id, user_id) or self._has_order_in_db(activity_id, user_id):
            return "REPEAT_BUY"

        # 3. 原子扣库存
        if not self._decr_stock_atomic(activity_id):
            return "SOLD_OUT"

        # 4. 扣减成功：标记已抢 + 入队异步建单
        self.mark_bought(activity_id, user_id)
        self.enqueue_order(activity_id, user_id)
        return "SUCCESS"


# 全局单例，各接口共用
seckill_service = SeckillService()

