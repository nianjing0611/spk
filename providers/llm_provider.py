"""OpenAI 兼容 LLM 封装：生成电商商品卡 prompts，失败回退本地。"""

import json
import re

import requests

# 本地兜底的 15 种增强方向（保持原图风格，只优化光影/质感/氛围）
LOCAL_STYLES = [
    "保持原图构图与背景，优化光影层次，增强商品质感与立体感",
    "保持原图色调，柔和侧光提升氛围，突出商品主体",
    "保持原图场景，增强暖色调商业感，适度锐化商品轮廓",
    "保持原图构图，柔光箱效果，商品细节更清晰，背景轻微虚化",
    "保持原图背景，优化光线均匀度，增强商品表面光泽",
    "保持原图色调，增强自然光感，商品质感更真实",
    "保持原图构图，提升画面层次感，暗部细节更丰富",
    "保持原图场景，增强冷色调清新感，商品更通透",
    "保持原图背景，优化高光控制，商品边缘更锐利",
    "保持原图色调，增强景深虚化，商品主体更聚焦",
    "保持原图构图，提升整体亮度与对比度，商业棚拍质感",
    "保持原图背景，柔化阴影，增强商品高级感",
    "保持原图色调，优化色彩饱和度，商品更鲜艳生动",
    "保持原图场景，增强逆光氛围，商品轮廓光更明显",
    "保持原图构图，优化白平衡，商品色彩更准确自然",
]

# system prompt 约束：图生图增强型，保持原图风格只做优化
SYSTEM_PROMPT = """你是电商商品图图生图提示词专家。根据用户给的商品调性，生成 N 条增强型提示词。

核心原则：这是图生图，不是文生图。原图已有自己的风格和场景，prompt 的作用是增强优化而非替换覆盖。

规则：
1. 用户填写的需求是唯一商品语义来源，不得引用或推测任何历史商品资料
2. 不得虚构或猜测品牌、商品名、型号、规格、标签文字或卖点
3. 需求未写明时只能称为"原产品"或"原商品"
4. 不得加入用户明确排除的元素
5. 每条 ≤100 字，描述光影/质感/构图/氛围的优化方向
6. 只输出 JSON 字符串数组，不要 Markdown、编号、解释
7. 恰好生成 {count} 条
8. 每条必须以"保持原图"开头，描述对原图的增强而非替换场景
9. 不得指定具体背景或场景（如"厨房""棚拍""果园"），因为原图风格各异，prompt 须适配任何原图
10. 优化方向限：光影、质感、构图比例、氛围、商品突出度、色彩调性、景深虚化"""

# 保护文字（保持原图 + 包装文字不被篡改）
PROTECTION_TEXT = (
    "保持原图的背景、构图与色调，不改变产品主体与包装文字，"
    "不增加多余文字，不修改品牌、价格、规格和关键卖点，"
    "保持商品比例与真实质感，仅优化光影和氛围"
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
            f'请根据以上描述生成 {count} 条增强型提示词，每条描述不同优化方向，都以"保持原图"开头。'
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
        f'请生成 {count} 条增强型提示词，每条描述不同优化方向，都以"保持原图"开头。'
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
