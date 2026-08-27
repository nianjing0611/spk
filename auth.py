"""本机密码认证：PBKDF2-HMAC-SHA256 + 持久化 session（重启不丢）。"""
import hmac
import json
import os
import secrets
import threading
import time
from hashlib import pbkdf2_hmac
from pathlib import Path

from config_manager import BASE_DIR

AUTH_FILE = BASE_DIR / "auth.json"
ITERATIONS = 200_000          # PBKDF2 迭代次数（工业级，防爆破）
SALT_BYTES = 16
SESSION_TTL = None            # None = 永久有效；如需过期改 7*24*3600（7天）等秒数

# 持久化 session 文件（放用户目录，工具升级/重启不丢登录态）
SESSION_DIR = Path.home() / ".mytool"
SESSION_FILE = SESSION_DIR / "sessions.json"

_lock = threading.Lock()
# 内存 session 存储（启动时从文件加载，运行时与文件双写）
_sessions: dict[str, float] = {}


def _load_sessions() -> None:
    """从文件加载 session 到内存（启动时调用，过滤已过期）。"""
    global _sessions
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        _sessions = {
            t: exp for t, exp in data.items()
            if exp is None or (isinstance(exp, (int, float)) and now <= exp)
        }
    except (json.JSONDecodeError, OSError):
        _sessions = {}


def _save_sessions() -> None:
    """把内存 session 写到文件（调用者需持锁）。"""
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(_sessions, f)
    except OSError:
        pass


# 启动时加载持久化 session（重启即恢复登录态）
_load_sessions()


def is_configured() -> bool:
    """是否已设置密码。"""
    return AUTH_FILE.exists()


def setup_password(password: str) -> bool:
    """首次设置密码（要求 ≥6 位）；已设置返回 False。"""
    if is_configured():
        return False
    if len(password) < 6:
        return False
    salt = os.urandom(SALT_BYTES)
    h = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    data = {
        "salt": salt.hex(),
        "password_hash": h.hex(),
        "created_at": time.time(),
    }
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True


def verify_password(password: str) -> bool:
    """验证密码（hmac.compare_digest 防时序攻击）。"""
    if not is_configured():
        return False
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    salt = bytes.fromhex(data.get("salt", ""))
    expected = bytes.fromhex(data.get("password_hash", ""))
    h = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return hmac.compare_digest(h, expected)


def create_session() -> str:
    """创建 session，返回 token（内存 + 文件双写）。"""
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = None  # None = 永久有效
        _save_sessions()
    return token


def check_session(token: str | None) -> bool:
    """验证 session 是否有效（走内存，过期时同步删文件；None=永久）。"""
    if not token:
        return False
    with _lock:
        if token not in _sessions:
            return False
        exp = _sessions[token]
        if exp is None:
            return True  # 永久有效
        if time.time() > exp:
            _sessions.pop(token, None)
            _save_sessions()
            return False
        return True


def destroy_session(token: str | None) -> None:
    """登出，销毁 session（内存 + 文件双删）。"""
    if not token:
        return
    with _lock:
        if token in _sessions:
            _sessions.pop(token, None)
            _save_sessions()


def get_cookie_name() -> str:
    """session cookie 名称。"""
    return "mytool_session"
