"""个性化推荐服务 —— 基于协同过滤 / 关联规则的简单实现（组长负责，创新点）。

设计说明：
  推荐的原理是"物以类聚，人以群分"。这里用最经典的"关联规则"思路：
  - 统计历史订单中"买了 A 的人也买了 B"的共现次数
  - 用户买了/浏览了某水果，就把和它"经常一起买"的水果推荐给他
  - 再结合"当季""热销"做补充推荐

  答辩时讲：用协同过滤的关联规则（Apriori 思想）做"猜你喜欢"。
"""
from collections import defaultdict


class RecommendService:
    """推荐服务。"""

    def recommend_for_user(self, user_id, limit=6):
        """
        为用户推荐商品。策略（由强到弱）：
        1. 用户浏览过某细分类 → 优先推荐同细分类的商品
        2. 否则按销量（热销）推荐
        返回 Fruit 对象列表。
        """
        from app.models import Fruit, BrowseHistory

        # 1. 用户浏览过的细分类（按浏览次数加权排序，最近浏览的权重更高）
        browsed_subcats = []
        if user_id:
            rows = (
                BrowseHistory.query
                .filter_by(user_id=user_id)
                .order_by(BrowseHistory.viewed_at.desc())
                .limit(50)  # 只看最近 50 条，避免历史过多拖慢查询
                .all()
            )
            # 保持浏览先后顺序去重（最近浏览的细分类排前面）
            seen = set()
            ordered_ids = []
            for h in rows:
                if h.fruit_id not in seen:
                    seen.add(h.fruit_id)
                    ordered_ids.append(h.fruit_id)
            if ordered_ids:
                rows_fruit = (
                    Fruit.query.filter(Fruit.id.in_(ordered_ids))
                    .with_entities(Fruit.id, Fruit.sub_category).all()
                )
                sub_of = {fid: sub for fid, sub in rows_fruit}
                for fid in ordered_ids:
                    sub = sub_of.get(fid)
                    if sub and sub not in browsed_subcats:
                        browsed_subcats.append(sub)

        # 2. 推荐：优先同细分类，再按销量补足
        result = []
        seen_ids = set()
        if browsed_subcats:
            for sub in browsed_subcats:
                items = (
                    Fruit.query
                    .filter_by(sub_category=sub, is_on_sale=True)
                    .order_by(Fruit.sales.desc())
                    .limit(limit)
                    .all()
                )
                for f in items:
                    if f.id not in seen_ids:
                        seen_ids.add(f.id)
                        result.append(f)
                    if len(result) >= limit:
                        return result

        # 3. 用热销商品补足到 limit 个
        if len(result) < limit:
            hot = Fruit.query.filter_by(is_on_sale=True).order_by(Fruit.sales.desc()).all()
            for f in hot:
                if f.id not in seen_ids:
                    result.append(f)
                if len(result) >= limit:
                    break

        return result[:limit]

    def recommend_by_association(self, user_history, all_orders):
        """
        基于关联规则的推荐。
        :param user_history: 用户买过/浏览过的 fruit_id 列表
        :param all_orders: 所有历史订单，每条是 [fruit_id, ...]（一单买的水果）
        :return: 推荐的 fruit_id 列表（按关联度排序）
        """
        # 1. 统计商品共现次数：co_occur[A][B] = A、B 一起出现在订单里的次数
        co_occur = defaultdict(lambda: defaultdict(int))
        for order in all_orders:
            fruits = list(set(order))  # 一单内的水果去重
            for i in range(len(fruits)):
                for j in range(len(fruits)):
                    if i != j:
                        co_occur[fruits[i]][fruits[j]] += 1

        # 2. 根据用户历史，累加"和这些水果一起买"的商品得分
        scores = defaultdict(int)
        for fruit_id in user_history:
            for other, count in co_occur[fruit_id].items():
                if other not in user_history:
                    scores[other] += count

        # 3. 按得分排序，取 top
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [fruit_id for fruit_id, _ in ranked]


recommend_service = RecommendService()
