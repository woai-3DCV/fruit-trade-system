# 水果交易智能管理系统

《软件工程与 UML》实践大作业 · 题目一

一个打通「货源上架 → 客户下单 → 库存管理 → 物流配送」完整链路的生鲜水果交易平台。

## 系统架构（四端）

系统采用「四端架构」，一个系统、一套数据库，登录时选择不同身份进入对应界面：

| 端 | 身份 | 职责 | 负责人 |
|---|---|---|---|
| 用户端 | 普通用户 | 浏览分类、商品详情、购物车、下单支付、售后 | 组长（董丞杰） |
| 商家端 | 商家 | 上架/下架、库存管理（损耗预警）、发货、售后、报表 | 何丹婷 |
| 平台管理端 | 平台管理员 | 审核商家资质、管理用户、处理投诉 | 王琰 |
| 物流端 | 物流配送 | 配送任务、物流追踪、冷链温控 | 陆东平 |

## 技术栈

- 后端：Python + Flask + SQLAlchemy
- 数据库：MySQL + Redis（秒杀扣库存）
- 前端：Vue 3 + Element Plus（或简单 HTML）

## 目录结构

```
fruit-trade-system/
├── app/                  # 后端应用
│   ├── __init__.py       # Flask 应用工厂（共享，改前先在群里说）
│   ├── models.py         # 数据库模型（共享，改前先在群里说）
│   ├── user/             # 用户端（组长）
│   ├── merchant/         # 商家端（何丹婷）
│   ├── admin/            # 平台管理端（王琰）
│   └── logistics/        # 物流端（陆东平）
├── docs/                 # UML 图、文档
├── tests/                # 测试
└── requirements.txt
```

## 分支规范

- `main`：主分支，只有能跑通的代码才合入
- 每人一个分支：
  - `feature/user`（组长）
  - `feature/merchant`（何丹婷）
  - `feature/admin`（王琰）
  - `feature/logistics`（陆东平）

## 启动方式

```bash
# 1. 创建虚拟环境
python -m venv venv
# Windows 激活
venv\Scripts\activate
# macOS / Linux 激活
source venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
python run.py
```

启动后访问 http://127.0.0.1:5000

## 协作约定

1. 每人只在自己负责的端目录里写代码
2. `app/__init__.py` 和 `app/models.py` 是共享文件，修改前先在群里说
3. 每天至少提交一次（即使只写了一半），方便周报统计
4. 不要提交数据库文件、密钥、配置文件
