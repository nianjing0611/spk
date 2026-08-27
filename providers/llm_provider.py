"""OpenAI 兼容 LLM 封装：生成电商商品卡 prompts，失败回退本地。"""

import json
import re

import requests

# 15 种换背景材质/光影模板
LOCAL_STYLES = [
    "精致纯色背景，柔光，突出商品",
    "渐变背景，柔和侧光，氛围感强",
    "高级纹理背景，质感突出",
    "深色质感背景，单点聚光，戏剧光影",
    "浅色极简背景，漫射光，干净通透",
    "大理石纹理背景，质感高级",
    "丝绸布料背景，柔光泽，高级感",
    "几何纹理背景，视觉冲击",
    "水波纹理背景，清透感",
    "木纹质感背景，自然亲切",
    "金属质感背景，高光反射",
    "磨砂玻璃背景，散射光，朦胧感",
    "光晕渐变背景，柔光，氛围感",
    "点阵纹理背景，潮流感",
    "画布纹理背景，艺术感",
]

# 一致性选项到中文描述的映射
_CONSIST_MAP = {
    "scene": "保持原场景类型不变",
    "style": "保持原图风格不变",
    "color": "保持原图色调不变",
    "layout": "保持原图构图不变",
}

# system prompt 模板，{count} 和 {consistency_clause} 动态填充
SYSTEM_PROMPT = """你是电商商品图图生图提示词专家。根据用户给的需求，生成 N 条换背景提示词。

核心原则：这是图生图，模型能看到原图。核心是更换背景的材质/光影/氛围，同时根据用户勾选的一致性选项决定哪些必须保持不变。

规则：
1. 用户填写的需求是唯一商品语义来源，不得引用或推测任何历史商品资料
2. 不得虚构或猜测品牌、商品名、型号、规格、标签文字或卖点
3. 需求未写明时只能称为"原产品"或"原商品"
4. 不得加入用户明确排除的元素
5. 每条 ≤100 字，描述一种背景材质/光影效果
6. 只输出 JSON 字符串数组，不要 Markdown、编号、解释
7. 恰好生成 {count} 条
8. {consistency_clause}
9. 10 条分别描写不同的背景材质/光影（纯色/渐变/纹理/丝绸/金属等）
10. 严禁指定与一致性选项冲突的新场景或色调（如勾了场景一致性就不能写"自然场景""户外场景"）"""

# 保护文字模板
PROTECTION_TEMPLATE = (
    "更换背景的材质/光影/氛围，{consistency_text}，"
    "不改变产品主体与包装文字，不增加多余文字，"
    "不修改品牌、价格、规格和关键卖点，保持商品比例与真实质感"
)


def _build_consistency_clause(consistency: dict) -> str:
    """根据一致性选项，生成 SYSTEM_PROMPT 第 8 条的约束描述。"""
    items = []
    for k, label in _CONSIST_MAP.items():
        if consistency.get(k):
            items.append(label)
    if not items:
        return "每条只需描述换什么背景材质/光影，无需保持任何原图属性。"
    return f"每条必须包含：{'、'.join(items)}。"


def _build_consistency_text(consistency: dict) -> str:
    """根据一致性选项，生成 PROTECTION_TEXT 的中间部分。"""
    items = []
    for k, label in _CONSIST_MAP.items():
        if consistency.get(k):
            items.append(label)
    if not items:
        return "灵活调整一切"
    return "、".join(items)


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
    consistency = product_info.get("consistency") or {}
    user_msg = _build_user_msg(product_info, count)
    sys_content = SYSTEM_PROMPT.format(
        count=count,
        consistency_clause=_build_consistency_clause(consistency),
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_content},
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
    consistency = product_info.get("consistency") or {}
    protection_text = PROTECTION_TEMPLATE.format(
        consistency_text=_build_consistency_text(consistency)
    )
    locked = product_info.get("locked_text", "")
    protect = protection_text + (f"，必须保留:{locked}" if locked else "")
    consist_items = []
    for k, label in _CONSIST_MAP.items():
        if consistency.get(k):
            consist_items.append(label)
    consist_clause = (
        f'每条包含：{"、".join(consist_items)}。'
        if consist_items
        else "每条只需描述换什么背景材质/光影。"
    )
    if desc:
        return (
            f"用户描述：{desc}\n"
            f"保护文字：{protect}\n"
            f"一致性要求：{consist_clause}\n"
            f"请根据以上描述生成 {count} 条换背景提示词，每条描述不同背景材质/光影。"
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
        f"一致性要求：{consist_clause}\n"
        f"请生成 {count} 条换背景提示词，每条描述不同背景材质/光影。"
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
    """本地兜底：15 种背景材质循环 + 一致性选项拼接。"""
    desc = (product_info.get("description") or "").strip()
    consistency = product_info.get("consistency") or {}
    protection_text = PROTECTION_TEMPLATE.format(
        consistency_text=_build_consistency_text(consistency)
    )
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
    protect = protection_text + (f"，必须保留:{locked}" if locked else "")

    consist_items = []
    for k, label in _CONSIST_MAP.items():
        if consistency.get(k):
            consist_items.append(label)
    consist_text = "、".join(consist_items) if consist_items else "灵活调整一切"

    result = []
    for i in range(count):
        scene = LOCAL_STYLES[i % len(LOCAL_STYLES)]
        p = f"换背景材质为{scene}，{consist_text}，方案{i + 1:02d}，电商商品卡，1:1比例，{protect}。"
        result.append(p)
    return result


def is_configured(llm_cfg: dict) -> bool:
    """判断 LLM 是否已配置（三项都填了）。"""
    return bool(
        (llm_cfg.get("base_url") or "").rstrip("/")
        and llm_cfg.get("api_key")
        and llm_cfg.get("model")
    )
