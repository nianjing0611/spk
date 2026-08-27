"""OpenAI 兼容 LLM 封装：生成电商商品卡 prompts，失败回退本地。"""

import json
import re

import requests

# 本地兜底的 15 种换背景场景（需配合用户描述的调性生成，风格匹配由 LLM 保证）
# 格式：场景类型，实际生成时会根据用户调性动态调整风格描述
LOCAL_STYLES = [
    "纯净纯色背景，柔光棚拍，突出商品",
    "渐变背景，柔和侧光，氛围感强",
    "自然场景背景，自然光，清新氛围",
    "深色高级背景，单点聚光，戏剧光影",
    "浅色极简背景，漫射光，干净通透",
    "材质纹理背景，暖色调，质感突出",
    "户外场景背景，日光，自然氛围",
    "几何形状背景，对比色，视觉冲击",
    "水波纹理背景，冷色调，清透感",
    "木纹材质背景，暖色调，自然亲切",
    "金属质感背景，高光反射，科技感",
    "布料丝绸背景，柔光泽，高级感",
    "花瓣散落背景，柔光，浪漫氛围",
    "抽象光晕背景，霓虹灯彩，潮流感",
    "磨砂玻璃背景，散射光，朦胧感",
]

# system prompt 约束：图生图换背景型，风格调性匹配原图
SYSTEM_PROMPT = """你是电商商品图图生图提示词专家。根据用户给的商品调性，生成 N 条换背景提示词。

核心原则：这是图生图，需要更换背景和场景，但新背景的风格调性必须与原图一致。

规则：
1. 用户填写的需求是唯一商品语义来源，不得引用或推测任何历史商品资料
2. 不得虚构或猜测品牌、商品名、型号、规格、标签文字或卖点
3. 需求未写明时只能称为"原产品"或"原商品"
4. 不得加入用户明确排除的元素
5. 每条 ≤100 字，描述一个新背景场景
6. 只输出 JSON 字符串数组，不要 Markdown、编号、解释
7. 恰好生成 {count} 条
8. 每条必须结合用户描述的调性来描写背景和氛围，确保换背景后风格不偏移
9. 例如用户描述"辣味浓烈、红色系"，则背景应配合红/橙/暖色调，而非蓝/绿/冷色调
10. 例如用户描述"清新自然、绿色系"，则背景应配合绿/青/自然色调，而非红/紫/工业色调
11. 10 条分别描写不同的背景场景（纯色/渐变/材质/自然/棚拍等），但每条的调性须与用户描述一致"""

# 保护文字（换背景但保风格 + 包装文字不被篡改）
PROTECTION_TEXT = (
    "更换背景但保持原图的色调与氛围风格，不改变产品主体与包装文字，"
    "不增加多余文字，不修改品牌、价格、规格和关键卖点，"
    "保持商品比例与真实质感"
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
        "max_tokens": min(8192, max(4096, count * 300)),
    }
    r = requests.post(
        f"{base_url}/chat/completions", headers=headers, json=payload, timeout=90
    )
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    content = msg.get("content") or ""
    if not content:
        content = msg.get("reasoning_content") or ""
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
            f'请根据以上描述生成 {count} 条换背景提示词，每条描述不同背景场景，但调性须与上述描述一致。'
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
        f'请生成 {count} 条换背景提示词，每条描述不同背景场景，但调性须与上述商品信息一致。'
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
    """本地兜底：15 种换背景场景循环 + 商品调性拼接。优先用自由描述。"""
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
        scene = LOCAL_STYLES[i % len(LOCAL_STYLES)]
        p = f"换背景为{scene}，结合调性:{info}，方案{i + 1:02d}，电商商品卡，1:1比例，{protect}。"
        result.append(p)
    return result


def is_configured(llm_cfg: dict) -> bool:
    """判断 LLM 是否已配置（三项都填了）。"""
    return bool(
        (llm_cfg.get("base_url") or "").rstrip("/")
        and llm_cfg.get("api_key")
        and llm_cfg.get("model")
    )
