# UML 图设计稿（水果交易智能管理系统）

> 用途：给画图的人一份「照着画就行」的内容清单。每张图列出完整要素和关系，避免画图时再去翻代码。
> 建议用 PlantUML / draw.io / ProcessOn 绘制。

---

## 1. 用例图（Use Case Diagram）

### 参与者（Actor）
| 参与者 | 说明 |
|---|---|
| 普通用户 | 顾客，购物的主体 |
| 商家 | 上架商品、发货、处理售后 |
| 平台管理员 | 审核商家、管理用户、处理投诉 |
| 物流配送员 | 配送、更新物流、温控记录 |
| DeepSeek 大模型 | 外部系统，AI 助手的支撑 |

### 用例（按参与者）
**普通用户：**
- 注册 / 登录
- 浏览商品（含分类筛选、搜索）
- 查看商品详情 / 评价
- 加入购物车 / 管理购物车
- 下单 / 支付 / 取消订单
- 确认收货
- 申请售后（退款/退货）
- 商品评价
- 收藏商品
- 私信商家（咨询）
- **限时秒杀**（创新点，`<<extend>>` 浏览商品）
- **个性化推荐**（创新点，`<<include>>` 浏览历史）
- **AI 智能客服**（创新点，`<<include>>` DeepSeek）

**商家：**
- 上架 / 下架商品
- 库存管理（损耗预警、批次管理）
- 发货
- 处理售后

**平台管理员：**
- 审核商家资质
- 管理用户
- 处理投诉

**物流配送员：**
- 接收配送任务
- 更新物流状态
- 冷链温控记录

### 关键关系标注
- 「秒杀」`<<extend>>` 「浏览商品」：秒杀是特殊的下单场景
- 「AI 客服」`<<include>>` 「DeepSeek 大模型」：依赖外部模型
- 「个性化推荐」`<<include>>` 「浏览历史记录」
- 「评价」「售后」`<<extend>>` 「确认收货」：收货后才能评价/售后

---

## 2. 类图（Class Diagram）

### 核心类及关系（对应 `app/models.py`）

```
User ──────1..*─── Order          （一个用户有多个订单）
User ──────1..*─── Cart           （一个用户一个购物车，多个条目）
User ──────1..*─── Address        （一个用户多个地址）
User ──────1..*─── BrowseHistory  （浏览历史）
User ──────1..*─── Favorite       （收藏）
User ──────1..*─── Message        （私信，用户和商家都发）
User ──────1..*─── Review         （评价）

Order ──────1──── Fruit            （一个订单对应一个水果，多对一）
Cart  ──────1──── Fruit            （购物车条目对应一个水果）
SeckillActivity ──1── Fruit        （秒杀活动对应一个水果）
BrowseHistory ───1── Fruit
Favorite ────────1── Fruit
Review ──────────1── Fruit

Order ──────1──0..1── Logistics    （订单可选有物流信息）
Order ──────1──0..1── AfterSale    （订单可选有售后）
Logistics ───1──*── TemperatureLog （物流有多个温控记录）

Fruit ──────1──*── FruitBatch      （水果有多个批次）
```

### 关键类的属性（画类图时写上）

**User**：id, username, password_hash, role, phone, nickname, avatar, gender

**Fruit**：id, name, category, sub_category, emoji, price, origin, sales, stock, merchant_id, is_on_sale

**Order**：id, user_id, fruit_id, quantity, total_price, status, is_seckill, created_at, pay_deadline, address, payment_method, paid_at, completed_at

**SeckillActivity**：id, fruit_id, seckill_price, stock, total_stock, limit_per_user, start_time, end_time, status

**Cart**：id, user_id, fruit_id, quantity

**Message**：id, user_id, merchant_id, fruit_id, sender_role, content

**Review**：id, user_id, fruit_id, order_id, rating, content

**AfterSale**：id, order_id, user_id, type, reason, status

**Logistics**：id, order_id, status, courier, current_location

> 亮点：`Order.status` 是状态机的核心，建议在类图里用注释标出状态值枚举（待支付/待发货/运输中/已完成/已取消）。

---

## 3. 顺序图（Sequence Diagram）—— 最有含金量的一张

### 3.1 秒杀流程（创新点，重点画这张）

```
参与者：用户 → 前端页面 → 秒杀服务(SeckillService) → 令牌桶 → 数据库/Redis → 消息队列 → 消费线程

1. 用户点击「立即抢购」
2. 前端 → 秒杀服务：POST /seckill/{id}/buy
3. 秒杀服务 → 令牌桶：try_acquire()
   ├─ 无令牌 → 返回 LIMITED（"人数过多"）
   └─ 有令牌 → 继续
4. 秒杀服务 → 数据库：查询是否已抢（限购校验）
   ├─ 已抢 → 返回 REPEAT_BUY
   └─ 未抢 → 继续
5. 秒杀服务 → 数据库/Redis：原子扣库存 UPDATE ... WHERE stock>0
   ├─ 失败 → 返回 SOLD_OUT
   └─ 成功 → 继续
6. 秒杀服务 → 消息队列：enqueue_order(activity_id, user_id)
7. 秒杀服务 → 前端：返回 SUCCESS（快速响应，不阻塞）
8. 消费线程（异步）→ 数据库：生成秒杀订单
9. 前端 → 用户：提示"抢购成功，订单生成中"
```

> 答辩金句：这个顺序图体现了「限流 → 限购 → 原子扣库存 → 异步下单」四层防线，是秒杀系统的标准架构。

### 3.2 普通下单流程

```
用户 → 前端 → 路由 → 数据库
1. 用户选商品加购物车
2. 用户提交订单（选地址）
3. 路由 → 数据库：校验库存
4. 路由 → 数据库：创建订单 + 扣库存 + 清购物车
5. 用户支付 → 订单状态"待发货"
6. 商家发货 → "运输中"
7. 用户确认收货 → "已完成"
```

---

## 4. 状态图（State Machine Diagram）—— 订单状态机

```
                 ┌─────────┐
   创建订单 ────▶│  待支付  │
                 └────┬────┘
           支付成功  │       超时/取消
                 ▼  │          ▼
              ┌─────┴──┐    ┌──────┐
              │ 待发货  │    │ 已取消 │
              └────┬───┘    └──────┘
           商家发货 │
                 ▼
              ┌───────┐
              │ 运输中  │
              └───┬───┘
           确认收货 │
                 ▼
              ┌───────┐
              │ 已完成  │
              └───────┘
```

**状态枚举**：待支付 → 待发货 → 运输中 → 已完成；待支付 → 已取消（超时/手动）

> 这张图直接对应代码里的 `Order.status`，画出来就是「订单状态机」，答辩时能讲清每个状态由哪个动作触发。

---

## 5. 活动图（Activity Diagram）—— 秒杀/支付的并发分支

### 秒杀活动图（体现并发控制）

```
开始
  │
  ▼
用户点击抢购
  │
  ▼
【判定】令牌桶是否有令牌？ ──否──▶ 提示"人数过多" ──▶ 结束
  │是
  ▼
【判定】是否已抢过？ ──是──▶ 提示"限购" ──▶ 结束
  │否
  ▼
【判定】库存 > 0？ ──否──▶ 提示"售罄" ──▶ 结束
  │是
  ▼
原子扣减库存（并发安全）
  │
  ▼
入队异步建单
  │
  ▼
结束
```

> 这个「判定菱形」的分支结构，正好画出并发场景下「拒绝超卖」的逻辑。

---

## 6. 组件图 / 部署图（Component & Deployment）

### 组件图
```
┌─────────────────────────────────────────┐
│              前端（浏览器）              │
│   用户端 / 商家端 / 管理端 / 物流端       │
└──────────────┬──────────────────────────┘
               │ HTTP
┌──────────────▼──────────────────────────┐
│          Flask 应用（后端）              │
│  auth 认证 ┃ user 用户 ┃ merchant 商家    │
│  admin 管理 ┃ logistics 物流              │
│  seckill_service（秒杀）                 │
│  recommend_service（推荐）               │
│  ai_service（AI，调 DeepSeek）           │
└──────┬───────────────────┬───────────────┘
       │ ORM               │ HTTP API
┌──────▼──────┐   ┌────────▼────────┐
│  SQLite/MySQL │   │  DeepSeek 大模型 │
│  （持久化）   │   │  （外部服务）    │
└─────────────┘   └─────────────────┘
       │
┌──────▼──────┐
│ Redis(可选)  │  （秒杀库存预热 + Lua 原子扣减）
└─────────────┘
```

### 部署图（可选）
- 客户端（浏览器）→ 应用服务器（Flask）→ 数据库服务器（MySQL/SQLite）+ 缓存（Redis）+ 外部 AI（DeepSeek）

---

## 7. 画图优先级建议

| 优先级 | 图 | 理由 |
|---|---|---|
| ★★★ | 顺序图（秒杀） | 最能体现你的创新点和技术深度 |
| ★★★ | 状态图（订单） | 直接对应代码，好画也好讲 |
| ★★★ | 类图 | 对应 models.py，证明模型设计清晰 |
| ★★ | 用例图 | 四端架构的总览 |
| ★★ | 活动图（秒杀并发） | 体现防超卖逻辑 |
| ★ | 组件图/部署图 | 体现技术栈分层 |

---

## 8. 答辩串词建议（创新点部分）

> "我们的系统有三个创新点，都围绕真实业务痛点：
> 1. **限时秒杀**——解决了高并发下『防超卖』的经典难题，用『令牌桶限流 + 原子扣库存 + 异步下单』三层架构，从理论到代码都落地了。
> 2. **个性化推荐**——基于浏览历史和收藏的协同过滤思想，解决了『冷启动』（热销兜底）和『可解释推荐』（猜你喜欢有据可依）。
> 3. **AI 智能客服**——接入 DeepSeek 大模型，实现多轮对话，未配置 Key 时降级为关键词匹配，保证系统可用性。"
