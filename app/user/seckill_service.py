"""秒杀核心服务 —— 防超卖的并发控制（组长负责，创新点）。

设计说明：
  秒杀的关键是"防超卖"。正常写法"先查库存再减"在并发下会被穿透，
  导致库存被扣成负数。

  这里用数据库的原子 UPDATE 保证"检查 + 扣减"合二为一：
      UPDATE seckill_activity SET stock = stock - 1
      WHERE id = :id AND stock > 0
  这条语句在数据库层面是原子的——只有库存 > 0 时才会扣减成功，
  并发下也不会超卖。

  答辩时讲：
    - 有 Redis 时用 Lua 脚本（单线程执行脚本，天然原子）
    - 本实现用数据库原子 UPDATE 实现同样效果（乐观锁思想）
    - 核心都是"把『查库存 + 扣库存』变成一个原子操作"
"""
import threading

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


class SeckillService:
    """秒杀服务：提供原子扣库存 + 限购能力。"""

    def __init__(self):
        self._lock = threading.Lock()  # 限购标记用的进程内锁
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

    # ---------------- 对外主流程 ----------------

    def seckill(self, activity_id: int, user_id: int) -> str:
        """执行一次抢购。返回结果状态码。"""
        # 1. 限购校验：一个用户只能抢一次
        if self.has_bought(activity_id, user_id):
            return "REPEAT_BUY"

        # 2. 原子扣库存
        if not self._decr_stock_atomic(activity_id):
            return "SOLD_OUT"

        # 3. 扣减成功，标记已抢
        self.mark_bought(activity_id, user_id)
        return "SUCCESS"


# 全局单例，各接口共用
seckill_service = SeckillService()
