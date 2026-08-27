"""OpenAI 兼容 LLM 封装：生成电商商品卡 prompts，失败回退本地。"""

import json
import re

import requests

# 30 种不同类别的场景描述（覆盖自然/居家/影棚/户外/节日等）
# 模型需识别原图场景类别，然后从同类别中选一个全新场景替换背景
LOCAL_STYLES = [
    # 自然户外类
    "山谷溪流背景，自然光，清澈通透",
    "森林树木背景，阳光透射，自然氛围",
    "高山云雾背景，壮丽开阔",
    "海边沙滩背景，阳光明媚",
    "田间农舍背景，质朴自然",
    # 居家生活类
    "现代厨房背景，温暖灯光，家具体感",
    "木质餐桌背景，温馨居家",
    "客厅壁炉背景，舒适温暖",
    "阳台花园背景，自然光洒入",
    "书房书架背景，文化气息",
    # 影棚极简类
    "白色影棚背景，专业打光",
    "灰色无缝背景，柔和侧光",
    "黑色高级背景，聚光突出",
    "米色渐变背景，柔和氛围",
    "蓝色冷调背景，清透质感",
    # 节日促销类
    "红色喜庆背景，金色装饰，节日氛围",
    "618大促背景，红色主调，视觉冲击",
    "新年喜庆背景，灯笼装饰",
    "中秋月圆背景，温馨团圆",
    "圣诞装饰背景，红绿配色",
    # 高端质感类
    "大理石台面背景，冷色调高级感",
    "天鹅绒布料背景，柔质感",
    "金属质感背景，高光反射",
    "玻璃镜面背景，反射光影",
    "真皮纹理背景，奢华质感",
    # 户外场景类
    "城市天台背景，都市夜景",
    "公园长椅背景，休闲氛围",
    "庭院花园背景，鸟语花香",
    "露台吧台背景，休闲惬意",
    "泳池边背景，夏日清凉",
]

# 一致性选项到简短指令的映射（用于 SYSTEM_PROMPT 和 prompt 末尾）
_CONSIST_MAP = {
    "scene": "场景类别",
    "style": "视觉风格",
    "color": "色调倾向",
    "layout": "构图布局",
}

# system prompt：识别原图类别 → 换同类别全新背景（一致性逻辑全在这里，每条 prompt 不重复）
SYSTEM_PROMPT = """你是电商商品图图生图提示词专家。根据用户指令，生成 {count} 条换背景的提示词。

核心：这是图生图，模型能看到原图。识别原图的场景类别、风格、色调，生成 {count} 条换背景提示词。每条以"换背景为"开头，写一个全新的背景场景。

规则：
1. 每条 ≤50 字，以"换背景为"开头
2. 只输出 JSON 字符串数组，不要 Markdown、编号、解释
3. 恰好生成 {count} 条
4. {consistency_clause}
5. {count} 条必须是完全不同的背景场景
6. 不改变产品主体、包装文字、品牌、价格、规格"""


def _build_consistency_clause(consistency: dict) -> str:
    """根据一致性选项，生成 SYSTEM_PROMPT 第 8 条的约束描述。"""
    items = []
    for k, label in _CONSIST_MAP.items():
        if consistency.get(k):
            items.append(label)
    if not items:
        return "10 条可以自由选择任何背景类别，无需与原图保持一致。"
    return f"每条必须保持原图的{'、'.join(items)}不变，在此约束下选择全新背景场景。"


def _build_consistency_suffix(consistency: dict) -> str:
    """根据一致性选项，生成每条 prompt 末尾的简短后缀。"""
    items = []
    for k, label in _CONSIST_MAP.items():
        if consistency.get(k):
            items.append(f"保持{label}")
    if not items:
        return ""
    return "，".join(items)


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
    """构造用户消息：核心指令放 user message，防止 v4-pro 忽略 system prompt。"""
    desc = (product_info.get("description") or "").strip()
    consistency = product_info.get("consistency") or {}
    consist_suffix = _build_consistency_suffix(consistency)
    locked = product_info.get("locked_text", "")

    # 可选商品字段
    product_parts = []
    for k, label in [("name", "商品名"), ("selling_points", "卖点"),
                      ("price", "价格"), ("activity", "活动"), ("specs", "规格")]:
        v = (product_info.get(k) or "").strip()
        if v:
            product_parts.append(f"{label}:{v}")
    product_text = "，".join(product_parts) if product_parts else ""

    instruction = desc if desc else "仅更换背景"

    # 核心指令放 user message，防止 v4-pro 忽略 system prompt
    core_rules = f"""【重要】你是图生图提示词专家。必须遵守以下规则：
1. 生成 {count} 条换背景提示词，每条以"换背景为"开头
2. 只输出 JSON 字符串数组
3. {consist_suffix and '每条末尾加"' + consist_suffix + '"'}
4. 不改变产品主体、包装文字、品牌、价格、规格

指令：{instruction}"""

    if product_text:
        core_rules += f"\n商品：{product_text}"
    if locked:
        core_rules += f"\n必须保留：{locked}"

    return core_rules


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
    """本地兜底：场景 + 一致性后缀。"""
    consistency = product_info.get("consistency") or {}
    consist_suffix = _build_consistency_suffix(consistency)
    locked = product_info.get("locked_text", "")

    result = []
    for i in range(count):
        scene = LOCAL_STYLES[i % len(LOCAL_STYLES)]
        p = f"换背景为{scene}，{consist_suffix}，不改变产品主体与包装文字"
        if locked:
            p += f"，必须保留:{locked}"
        result.append(p)
    return result


def is_configured(llm_cfg: dict) -> bool:
    """判断 LLM 是否已配置（三项都填了）。"""
    return bool(
        (llm_cfg.get("base_url") or "").rstrip("/")
        and llm_cfg.get("api_key")
        and llm_cfg.get("model")
    )
