"""演示数据脚本 —— 造一些水果、秒杀活动、历史订单，方便看秒杀和推荐效果。

用法：
    python seed_data.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import create_app
from app.models import db, User, Fruit, SeckillActivity, Order
from app.user.seckill_service import seckill_service
from datetime import datetime, timedelta


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        # 造水果（含大分类 + 细分类 + 销量 + 图标）
        fruits = [
            # (名称, 大分类, 细分类, 价格, 产地, 销量, 图标)
            ("红富士苹果", "水果", "苹果", 8.8, "山东烟台", 5200, "🍎"),
            ("阿克苏冰糖心苹果", "水果", "苹果", 12.9, "新疆阿克苏", 3100, "🍎"),
            ("丹东草莓", "水果", "莓果", 29.9, "辽宁丹东", 4800, "🍓"),
            ("云南蓝莓", "水果", "莓果", 25.0, "云南", 2600, "🫐"),
            ("海南香蕉", "水果", "香蕉", 12.9, "海南", 4300, "🍌"),
            ("赣南脐橙", "水果", "柑橘", 6.5, "江西赣州", 5600, "🍊"),
            ("广西砂糖橘", "水果", "柑橘", 5.9, "广西", 6100, "🍊"),
            ("库尔勒香梨", "水果", "梨", 7.9, "新疆库尔勒", 3400, "🍐"),
            ("阳光玫瑰葡萄", "水果", "葡萄", 19.9, "云南", 3900, "🍇"),
            ("麒麟西瓜", "水果", "瓜类", 3.9, "海南", 4500, "🍉"),
            ("哈密瓜", "水果", "瓜类", 6.9, "新疆哈密", 2800, "🍈"),
            ("大凉山软籽石榴", "水果", "石榴", 9.9, "四川大凉山", 1900, "🫐"),
            ("海南金钻凤梨", "水果", "热带水果", 13.9, "海南", 2300, "🍍"),
            ("智利车厘子", "水果", "进口", 49.9, "智利", 1700, "🍒"),
            ("阳光番茄", "蔬菜", "番茄", 4.5, "山东寿光", 5200, "🍅"),
            ("有机黄瓜", "蔬菜", "瓜茄", 3.9, "山东", 4400, "🥒"),
            ("云南土豆", "蔬菜", "根茎", 2.5, "云南", 6800, "🥔"),
        ]
        if Fruit.query.count() == 0:
            for name, cat, sub, price, origin, sales, emoji in fruits:
                db.session.add(Fruit(
                    name=name, category=cat, sub_category=sub,
                    price=price, origin=origin, sales=sales, emoji=emoji
                ))
            db.session.commit()
            print("已创建水果数据")

        # 造两个秒杀活动（草莓临期清仓 + 香蕉清仓）
        if SeckillActivity.query.count() == 0:
            now = datetime.now()  # 用本地时间，避免和前端 JS 时区不一致
            activities = [
                SeckillActivity(
                    fruit_id=2,          # 丹东草莓
                    seckill_price=9.9,
                    stock=100,
                    total_stock=100,
                    limit_per_user=1,
                    start_time=now - timedelta(hours=1),
                    end_time=now + timedelta(hours=2),
                    status="进行中",
                ),
                SeckillActivity(
                    fruit_id=3,          # 海南香蕉
                    seckill_price=5.9,
                    stock=80,
                    total_stock=80,
                    limit_per_user=1,
                    start_time=now + timedelta(hours=1),
                    end_time=now + timedelta(hours=4),
                    status="未开始",
                ),
            ]
            db.session.add_all(activities)
            db.session.commit()
            print("已创建秒杀活动")

            # 秒杀库存预热到 Redis/内存
            for a in SeckillActivity.query.all():
                seckill_service.preload_stock(a.id, a.stock)
            print("秒杀库存已预热")

        print("演示数据初始化完成！")


if __name__ == "__main__":
    seed()
