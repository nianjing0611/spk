"""OpenAI 兼容 LLM 封装：生成电商商品卡 prompts，失败回退本地。"""

import json
import re

import requests

# 本地兜底的 15 种风格
LOCAL_STYLES = [
    "清新绿色商业棚拍，自然光，透明亚克力台座，少量果蔬点缀",
    "618 大促海报，红金主视觉，放射光，爆款标签",
    "高端极简灰白棚拍，大理石台面，金属细线装饰",
    "果蔬原料环绕，自然农园背景，阳光斑驳",
    "冷色冰感棚拍，蓝色渐变背景，水珠质感",
    "自然厨房场景，木质台面，暖色侧光",
    "轻奢台阶展示，金色边框，深色背景",
    "夏日清爽场景，薄荷绿背景，少量冰块",
    "社交媒体爆款风格，鲜艳撞色，活泼版式",
    "大理石纹理背景，高级灰调，金属点缀",
    "纯白棚拍，柔和顶光，干净投影",
    "浅米色礼盒内衬，丝绒质感，柔和光晕",
    "深色高级棚拍，单点射灯，戏剧光影",
    "清新果园背景，自然枝叶，阳光透射",
    "促销倒计时风格，红黄撞色，紧迫感版式",
]

# system prompt 约束（参考完整版设计）
SYSTEM_PROMPT = """你是电商商品图提示词专家。根据用户给的商品信息，生成 N 条用于图生图的提示词。

规则：
1. 用户填写的需求是唯一商品语义来源，不得引用或推测任何历史商品资料
2. 不得虚构或猜测品牌、商品名、型号、规格、标签文字或卖点
3. 需求未写明时只能称为"原产品"或"原商品"
4. 不得加入用户明确排除的元素
5. 每条 ≤100 字，要描述背景/光线/构图/氛围
6. 只输出 JSON 字符串数组，不要 Markdown、编号、解释
7. 恰好生成 {count} 条"""

# 保护文字（防止 AI 改掉商品包装上的文字）
PROTECTION_TEXT = (
    "不改变产品主体与包装文字，不增加多余文字，"
    "不修改品牌、价格、规格和关键卖点，保持商品比例与真实质感"
)


def generate(product_info: dict, count: int, llm_cfg: dict) -> list[str]:
    """生成 prompts。优先 OpenAI 兼容 API，失败回退本地。"""
    base_url = (llm_cfg.get("base_url") or "").rstrip("/")
    api_key = llm_cfg.get("api_key") or ""
    model = llm_cfg.get("model") or ""

    if not (base_url and api_key and model):
        return generate_local(product_info, count)

    try:
        return _call_api(
            product_info, count, base_url, api_key, model,
            llm_cfg.get("temperature", 0.2),
        )
    except Exception as e:
        print(f"[LLM] API 调用失败，回退本地: {e}")
        return generate_local(product_info, count)


def _call_api(product_info, count, base_url, api_key, model, temperature) -> list:
    """调 OpenAI 兼容 /chat/completions。"""
    user_msg = _build_user_msg(product_info, count)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(count=count)},
            {"role": "user", "content": user_msg},
        ],
        "temperature": temperature,
        "max_tokens": min(8000, max(2000, count * 180)),
    }
    r = requests.post(
        f"{base_url}/chat/completions", headers=headers, json=payload, timeout=60
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    prompts = _extract_json_array(content)
    if not prompts:
        raise ValueError(f"响应解析失败: {content[:200]}")
    return prompts[:count]


def _build_user_msg(product_info: dict, count: int) -> str:
    """构造用户消息：优先用自由描述，没有则用结构化字段。"""
    desc = (product_info.get("description") or "").strip()
    locked = product_info.get("locked_text", "")
    protect = PROTECTION_TEXT + (f"，必须保留:{locked}" if locked else "")
    if desc:
        return (
            f"用户描述：{desc}\n"
            f"保护文字：{protect}\n"
            f"请根据以上描述生成 {count} 条提示词，每条描述不同场景。"
        )
    parts = []
    for k in ["name", "selling_points", "price", "activity", "specs"]:
        v = product_info.get(k)
        if v:
            parts.append(f"{k}: {v}")
    info = "，".join(parts) if parts else "商品信息以源图为准"
    return (
        f"商品信息：{info}\n"
        f"保护文字：{protect}\n"
        f"请生成 {count} 条提示词，每条描述不同场景。"
    )


def _extract_json_array(text: str) -> list:
    """从文本提取 JSON 字符串数组。"""
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
        return [str(x) for x in arr if isinstance(x, str)]
    except json.JSONDecodeError:
        return []


def generate_local(product_info: dict, count: int) -> list:
    """本地兜底：15 种风格循环 + 商品信息拼接。优先用自由描述。"""
    desc = (product_info.get("description") or "").strip()
    if desc:
        info = desc[:60]
    else:
        parts = []
        for k in ["name", "selling_points", "price", "activity", "specs"]:
            v = product_info.get(k)
            if v:
                parts.append(f"{k}: {v}")
        info = "，".join(parts) if parts else "原产品"
    locked = product_info.get("locked_text", "")
    protect = PROTECTION_TEXT + (f"，必须保留:{locked}" if locked else "")

    result = []
    for i in range(count):
        style = LOCAL_STYLES[i % len(LOCAL_STYLES)]
        p = f"商品:{info}，方案{i + 1:02d}，{style}，电商商品卡，1:1比例，{protect}。"
        result.append(p)
    return result


def is_configured(llm_cfg: dict) -> bool:
    """判断 LLM 是否已配置（三项都填了）。"""
    return bool(
        (llm_cfg.get("base_url") or "").rstrip("/")
        and llm_cfg.get("api_key")
        and llm_cfg.get("model")
    )
