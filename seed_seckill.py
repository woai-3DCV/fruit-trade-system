"""造多个限时秒杀活动 —— 时间基于当前时间动态生成，保证任何时候跑都有「进行中/未开始」的活动。

用法：
    python seed_seckill.py

会先清空旧的秒杀活动，再生成 6 个新的（2 个进行中 + 2 个未开始 + 2 个已结束），
覆盖三种状态，方便演示倒计时、抢购、售罄等效果。
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import create_app
from app.models import db, Fruit, SeckillActivity
from app.user.seckill_service import seckill_service
from datetime import datetime, timedelta


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        # 1. 清空旧的秒杀活动
        SeckillActivity.query.delete()
        db.session.commit()
        print("已清空旧秒杀活动")

        # 2. 生成 6 个新活动，覆盖三种状态
        now = datetime.now()
        # (fruit_id, 秒杀价, 库存, 状态, 相对时间的开始/结束偏移)
        plans = [
            # 进行中（已开始 1 小时，还 3 小时结束）
            (1, 6.9,  120, "进行中", -1, 3),    # 红富士苹果
            (2, 9.9,  100, "进行中", -2, 2),    # 阿克苏冰糖心苹果
            # 未开始（1 小时后开始）
            (3, 19.9, 80,  "未开始", 1, 4),     # 丹东草莓
            (7, 4.9,  90,  "未开始", 2, 5),     # 广西砂糖橘
            # 已结束（已结束 1 小时，用于展示"已结束"状态）
            (9, 15.9, 0,   "已结束", -5, -1),   # 阳光玫瑰葡萄
            (13, 9.9,  0,  "已结束", -6, -2),   # 海南金钻凤梨
        ]

        created = 0
        for fruit_id, price, stock, status, start_h, end_h in plans:
            fruit = Fruit.query.get(fruit_id)
            if not fruit:
                print(f"  跳过 fruit_id={fruit_id}（商品不存在）")
                continue
            act = SeckillActivity(
                fruit_id=fruit_id,
                seckill_price=price,
                stock=stock,
                total_stock=stock,
                limit_per_user=1,
                start_time=now + timedelta(hours=start_h),
                end_time=now + timedelta(hours=end_h),
                status=status,
            )
            db.session.add(act)
            created += 1
            print(f"  ✓ {fruit.name}：¥{price}，库存 {stock}，{status}（{start_h}~{end_h}h）")
        db.session.commit()

        # 3. 预热库存（进行中的活动）
        for a in SeckillActivity.query.all():
            seckill_service.preload_stock(a.id, a.stock)
        print(f"\n完成！共生成 {created} 个秒杀活动，库存已预热。")
        print("刷新秒杀页即可看到效果。")


if __name__ == "__main__":
    seed()
