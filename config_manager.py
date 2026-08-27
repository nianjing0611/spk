"""配置管理：读写 config.json，首次运行创建默认配置，过滤敏感字段。"""
import json
import os
import sys
from pathlib import Path

# 运行时基目录（支持源码和 PyInstaller 打包两种模式）
if getattr(sys, "frozen", False):
    BASE_DIR = Path(os.path.dirname(sys.executable))      # exe 同目录（可写）
    RESOURCE_DIR = Path(sys._MEIPASS)                     # 打包资源目录（只读）
else:
    BASE_DIR = Path(__file__).resolve().parent            # 源码目录
    RESOURCE_DIR = BASE_DIR

CONFIG_FILE = BASE_DIR / "config.json"
VERSION_FILE = RESOURCE_DIR / "version.json" if getattr(sys, "frozen", False) else BASE_DIR / "version.json"

# 默认配置（分发时全空，等用户填 key）
DEFAULT_CONFIG = {
    "image": {
        "engine": "dreamina_cli",
        "cli_path": "auto",
        "model_version": "5.0",
        "resolution_type": "2k",
        "poll_interval": 10,
        "query_timeout": 1200,
        "max_concurrency": 4,
    },
    "llm": {
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "model": "deepseek-chat",
        "temperature": 0.2,
    },
    "output_dir": "output",
    "prompts": [],
}

# 敏感字段（返回前端时过滤掉，不回显）
SENSITIVE_KEYS = {"api_key"}


def load_config() -> dict:
    """加载配置；首次运行创建默认 config.json。"""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return _merge_defaults(cfg)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    """保存配置到 config.json。"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def public_config(cfg: dict) -> dict:
    """返回安全的配置给前端（过滤敏感字段，空值保留为空字符串）。"""
    pub = json.loads(json.dumps(cfg))  # 深拷贝
    _mask_sensitive(pub)
    return pub


def _mask_sensitive(d):
    """递归过滤敏感字段：有值显示 ***，空值保留空字符串。"""
    if isinstance(d, dict):
        for k, v in list(d.items()):
            if k in SENSITIVE_KEYS:
                d[k] = "***" if v else ""
            elif isinstance(v, (dict, list)):
                _mask_sensitive(v)
    elif isinstance(d, list):
        for item in d:
            _mask_sensitive(item)


def _merge_defaults(cfg: dict) -> dict:
    """合并默认值，补全新增字段（兼容旧版配置升级）。"""
    result = DEFAULT_CONFIG.copy()
    for k, v in cfg.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            merged = result[k].copy()
            merged.update(v)
            result[k] = merged
        else:
            result[k] = v
    return result


def get_version_info() -> dict:
    """读取 version.json。"""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": "0.0.0", "channel": "stable", "release_repo": ""}


def resolve_output_dir(cfg: dict) -> Path:
    """解析输出目录为绝对路径。"""
    out = cfg.get("output_dir", "output")
    p = Path(out)
    if not p.is_absolute():
        p = BASE_DIR / out
    p.mkdir(parents=True, exist_ok=True)
    return p
