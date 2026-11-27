"""AI 助手服务 —— 接入 DeepSeek 大模型（OpenAI 兼容格式）。

说明：
- API Key 从环境变量 DEEPSEEK_API_KEY 读取，或从 ai_config.py 读取。
- 未配置 Key 或调用失败时，自动降级到本地关键词匹配。
- DeepSeek 的 base_url 是 https://api.deepseek.com ，接口兼容 OpenAI 的 /chat/completions。
"""
import os
import json
import urllib.request

# 优先环境变量，其次 ai_config.py（若存在）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

try:
    from app.user import ai_config  # type: ignore
    DEEPSEEK_API_KEY = DEEPSEEK_API_KEY or getattr(ai_config, "API_KEY", "")
    DEEPSEEK_BASE_URL = getattr(ai_config, "BASE_URL", DEEPSEEK_BASE_URL)
    DEEPSEEK_MODEL = getattr(ai_config, "MODEL", DEEPSEEK_MODEL)
except ImportError:
    pass

# 系统提示词：限定助手是"水果交易平台的智能客服"
SYSTEM_PROMPT = (
    "你是「水果交易智能管理系统」的智能客服助手，名叫小果。"
    "你负责解答用户在购物过程中的问题，包括：限时秒杀、优惠、退款退货、配送物流、"
    "收货地址、修改密码、支付方式、售后、水果新鲜度等。"
    "回答要简洁友好、口语化，多用 emoji，控制在 100 字以内。"
    "如果问题与购物无关，礼貌地引导用户回到购物话题。"
)


def _fallback_keywords(question):
    """本地关键词兜底（无 API 时用）。"""
    keywords = {
        "秒杀": "限时秒杀在「限时秒杀」专区，价格超低，先到先得！每次限购 1 件，手慢无哦～",
        "优惠": "可以关注「限时秒杀」专区，热门水果有折扣价，比如丹东草莓秒杀价 ¥9.9！",
        "推荐": "可以看首页底部的「猜你喜欢」，根据你的浏览记录智能推荐水果～",
        "退款": "在「我的订单」找到对应订单，可发起售后申请（退款）。",
        "退货": "在「我的订单」发起售后申请，选择退货并填写原因。",
        "配送": "订单发货后可在「我的订单」查看物流状态，全程冷链配送。",
        "物流": "订单运输中会实时更新位置，冷链温控全程监控。",
        "地址": "在「个人中心 → 收货地址」可以添加和管理收货地址。",
        "密码": "在「个人中心 → 安全设置」可以修改登录密码。",
        "支付": "支持微信支付、支付宝、银行卡支付三种方式。",
        "售后": "在「我的订单」可以对已完成订单发起售后申请。",
        "新鲜": "我们所有水果都是产地直采、冷链配送，保证新鲜。",
    }
    for kw, resp in keywords.items():
        if kw in question:
            return resp
    return None


def chat(question, history=None):
    """调用 DeepSeek 回答；失败则降级关键词匹配。

    返回 (answer, used_ai) —— used_ai 表示是否真的用了大模型。
    """
    # 1. 尝试调用 DeepSeek
    if DEEPSEEK_API_KEY:
        try:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for h in (history or []):
                messages.append(h)
            messages.append({"role": "user", "content": question})

            payload = json.dumps({
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 300,
            }).encode("utf-8")

            req = urllib.request.Request(
                DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + DEEPSEEK_API_KEY,
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            answer = data["choices"][0]["message"]["content"].strip()
            if answer:
                return answer, True
        except Exception as e:
            # 降级到关键词匹配（网络失败/超时/key 无效等都走这里）
            pass

    # 2. 降级：关键词匹配
    fallback = _fallback_keywords(question)
    if fallback:
        return fallback, False
    return (
        "这个问题我还没学会，你可以私信商家咨询，或者换个问法试试～比如问我「怎么参加秒杀」「怎么退款」😊",
        False,
    )


def is_configured():
    """是否已配置 API Key。"""
    return bool(DEEPSEEK_API_KEY)
