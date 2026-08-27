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
SYSTEM_PROMPT = """你是电商商品图图生图提示词专家。根据用户给的需求，生成 N 条换背景提示词。

核心原则：这是图生图，模型能看到原图。先识别原图的场景类别、视觉风格和色调倾向，再生成 N 条全新背景的提示词。每条换一个完全不同的背景，但须与原图属于同一类别/风格/色调（根据用户勾选决定）。

规则：
1. 用户填写的需求是唯一商品语义来源，不得引用或推测任何历史商品资料
2. 不得虚构或猜测品牌、商品名、型号、规格、标签文字或卖点
3. 需求未写明时只能称为"原产品"或"原商品"
4. 不得加入用户明确排除的元素
5. 每条 ≤50 字，只描述一个背景场景，不要重复一致性说明
6. 只输出 JSON 字符串数组，不要 Markdown、编号、解释
7. 恰好生成 {count} 条
8. {consistency_clause}
9. 10 条必须是完全不同的背景场景（如山谷溪流、现代厨房、白色影棚、红色喜庆等）
10. 背景必须是全新的，不能只改材质或光影，要换整个场景"""


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
    """构造用户消息：精简，一致性逻辑已在 SYSTEM_PROMPT 中说明。"""
    desc = (product_info.get("description") or "").strip()
    consistency = product_info.get("consistency") or {}
    consist_suffix = _build_consistency_suffix(consistency)
    locked = product_info.get("locked_text", "")
    protect_parts = ["不改变产品主体与包装文字", "不增加多余文字", "不修改品牌、价格、规格和关键卖点", "保持商品比例与真实质感"]
    if locked:
        protect_parts.append(f"必须保留:{locked}")
    protect = "，".join(protect_parts)

    if desc:
        return (
            f"用户描述：{desc}\n"
            f"保护：{protect}\n"
            f'请生成 {count} 条换背景提示词。每条只写背景场景，末尾加"{consist_suffix}"。不要重复一致性说明。'
        )
    parts = []
    for k in ["name", "selling_points", "price", "activity", "specs"]:
        v = product_info.get(k)
        if v:
            parts.append(f"{k}: {v}")
    info = "，".join(parts) if parts else "商品信息以源图为准"
    return (
        f"商品信息：{info}\n"
        f"保护：{protect}\n"
        f'请生成 {count} 条换背景提示词。每条只写背景场景，末尾加"{consist_suffix}"。不要重复一致性说明。'
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
    """本地兜底：精简 prompt，场景 + 简短一致性后缀。"""
    consistency = product_info.get("consistency") or {}
    consist_suffix = _build_consistency_suffix(consistency)
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

    result = []
    for i in range(count):
        scene = LOCAL_STYLES[i % len(LOCAL_STYLES)]
        p = f"{scene}，{consist_suffix}，不改变产品主体与包装文字，保持商品比例与真实质感"
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
