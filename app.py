"""MyTool 主程序：Flask Web 应用，拖拽式即梦 AI 批量生图工具。

MVP 阶段：同步调用即梦 CLI（--poll=180），双层循环 图片×prompts。
"""
import os
import re
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import requests

from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS

from config_manager import (
    load_config, save_config, public_config, get_version_info,
    resolve_output_dir, BASE_DIR, RESOURCE_DIR,
)
from auth import (
    is_configured, setup_password, verify_password,
    create_session, check_session, destroy_session, get_cookie_name,
)
from providers import image_provider, llm_provider

app = Flask(__name__, template_folder=str(RESOURCE_DIR / "templates"), static_folder=None)
CORS(app)

# 上传大小限制（50MB，避免大图片直接 413 断连接）
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB

# 允许的图片后缀
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

# 全局状态（线程间读写，依赖 GIL 保证安全）
state = {
    "running": False,
    "paused": False,
    "total": 0,
    "done": 0,
    "current": "",
    "output_dir": "",
    "ratio": "1:1",
    "logs": [],
}

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def add_log(msg: str, level: str = "info"):
    """添加日志，保留最近 100 条。"""
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "level": level}
    state["logs"].append(entry)
    if len(state["logs"]) > 100:
        state["logs"] = state["logs"][-100:]


# ==================== 认证拦截 ====================
@app.before_request
def auth_check():
    """拦截 /api/ 请求，放行 /api/auth/。"""
    path = request.path
    if not path.startswith("/api/"):
        return None
    if path.startswith("/api/auth/"):
        return None
    token = request.cookies.get(get_cookie_name())
    if not check_session(token):
        return jsonify({"error": "未登录"}), 401
    return None


# ==================== 前端 ====================
@app.route("/")
def index():
    return send_from_directory(str(RESOURCE_DIR / "templates"), "index.html")


# ==================== 认证路由 ====================
@app.route("/api/auth/status")
def auth_status():
    return jsonify({"configured": is_configured()})


@app.route("/api/auth/setup", methods=["POST"])
def auth_setup():
    if is_configured():
        return jsonify({"error": "密码已设置"}), 400
    pwd = (request.json or {}).get("password", "")
    if setup_password(pwd):
        token = create_session()
        resp = make_response(jsonify({"success": True}))
        resp.set_cookie(get_cookie_name(), token, httponly=True, samesite="Lax", max_age=7 * 24 * 3600)
        return resp
    return jsonify({"error": "密码至少 6 位"}), 400


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    pwd = (request.json or {}).get("password", "")
    if verify_password(pwd):
        token = create_session()
        resp = make_response(jsonify({"success": True}))
        resp.set_cookie(get_cookie_name(), token, httponly=True, samesite="Lax", max_age=7 * 24 * 3600)
        return resp
    return jsonify({"error": "密码错误"}), 401


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    token = request.cookies.get(get_cookie_name())
    destroy_session(token)
    resp = make_response(jsonify({"success": True}))
    resp.delete_cookie(get_cookie_name())
    return resp


# ==================== 配置路由 ====================
@app.route("/api/config", methods=["GET", "POST"])
def config_route():
    if request.method == "GET":
        return jsonify(public_config(load_config()))
    data = request.json or {}
    cfg = load_config()
    # 合并保存：跳过前端掩码 ***（不覆盖真实 key）
    for k, v in data.items():
        if k in cfg and isinstance(cfg[k], dict) and isinstance(v, dict):
            for sk, sv in v.items():
                if sv == "***":
                    continue  # 前端掩码值，保留原值
                cfg[k][sk] = sv
        else:
            cfg[k] = v
    save_config(cfg)
    return jsonify({"success": True})


# ==================== 状态路由 ====================
@app.route("/api/state")
def get_state():
    return jsonify(state)


# ==================== 上传路由 ====================
@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "图片过大，单张请小于 50MB"}), 413


@app.errorhandler(401)
def not_authed(_e):
    return jsonify({"error": "会话已过期，请重新登录"}), 401


@app.route("/api/upload", methods=["POST"])
def upload():
    # 确保目录存在（放在这里可以动态适应 BASE_DIR 解析变化）
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[UPLOAD] 创建上传目录失败: {e}")
        return jsonify({"error": f"上传目录不可写: {e}"}), 500

    if "file" not in request.files:
        return jsonify({"error": "无文件，请选择图片"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "空文件名"}), 400

    # 1) 只保留文件名（防路径穿越）+ 去非法字符
    raw_name = os.path.basename(f.filename)
    # Windows 非法字符过滤
    safe_stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", Path(raw_name).stem)
    ext = Path(raw_name).suffix.lower()

    # 2) 后缀校验
    if ext not in ALLOWED_EXT:
        print(f"[UPLOAD] 拒绝: 后缀不支持 {raw_name}")
        return jsonify({"error": f"不支持的文件类型 {ext}，支持: jpg/png/gif/bmp/webp"}), 400

    # 3) 重名自动加序号
    final_stem = safe_stem or "image"
    dest = UPLOAD_DIR / f"{final_stem}{ext}"
    n = 1
    while dest.exists():
        dest = UPLOAD_DIR / f"{final_stem}_{n}{ext}"
        n += 1

    # 4) 先保存到临时文件，再原子重命名（避免半写入）
    tmp_path = UPLOAD_DIR / f".tmp_{os.getpid()}_{int(time.time()*1000)}{ext}"
    try:
        f.save(str(tmp_path))
        size = tmp_path.stat().st_size
        if size == 0:
            raise IOError("上传文件为空")
        os.replace(str(tmp_path), str(dest))
    except PermissionError as e:
        tmp_path.unlink(missing_ok=True)
        print(f"[UPLOAD] 写入失败(权限): {e}")
        return jsonify({"error": f"写入失败: 权限不足，请移到 C:\\MyTool 等可写目录"}), 500
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        print(f"[UPLOAD] 写入失败: {e}")
        return jsonify({"error": f"写入失败: {e}"}), 500

    print(f"[UPLOAD] OK {dest.name} ({size//1024} KB)")
    return jsonify({"path": str(dest), "name": dest.name, "size": size})


# ==================== 批量生成路由 ====================
@app.route("/api/start", methods=["POST"])
def start():
    if state["running"]:
        return jsonify({"error": "任务进行中"}), 400
    data = request.json or {}
    images = data.get("images", [])
    prompts = data.get("prompts", [])
    ratio = data.get("ratio", "1:1")
    if not images or not prompts:
        return jsonify({"error": "请添加图片和提示词"}), 400

    cfg = load_config()
    output_dir = resolve_output_dir(cfg)
    cli_path = cfg.get("image", {}).get("cli_path", "auto")

    t = threading.Thread(
        target=process_task,
        args=(images, prompts, str(output_dir), ratio, cli_path),
        daemon=True,
    )
    t.start()
    return jsonify({"success": True, "total": len(images) * len(prompts)})


@app.route("/api/stop", methods=["POST"])
def stop():
    state["running"] = False
    state["paused"] = False
    add_log("已请求停止，当前任务完成后将终止", "warn")
    return jsonify({"success": True})


@app.route("/api/pause", methods=["POST"])
def pause():
    if not state["running"]:
        return jsonify({"error": "任务未运行"}), 400
    state["paused"] = True
    add_log("已暂停，等待继续", "warn")
    return jsonify({"success": True})


@app.route("/api/resume", methods=["POST"])
def resume():
    if not state["running"]:
        return jsonify({"error": "任务未运行"}), 400
    if not state["paused"]:
        return jsonify({"error": "任务未暂停"}), 400
    state["paused"] = False
    add_log("已继续", "info")
    return jsonify({"success": True})


def process_task(images, prompts, output_dir, ratio, cli_path):
    """批量生成：双层循环 图片 × prompts（可中断模式）。"""
    state["running"] = True
    state["total"] = len(images) * len(prompts)
    state["done"] = 0
    state["output_dir"] = output_dir
    state["ratio"] = ratio
    add_log(f"开始任务：{len(images)} 图 × {len(prompts)} prompt = {state['total']} 个")

    def _canceled():
        return not state["running"]

    def _paused():
        return state.get("paused", False)

    n = 0
    for img in images:
        if _canceled():
            break
        img_path = img.get("path", "")
        img_name = Path(img.get("name", "image")).stem
        for pi, prompt in enumerate(prompts):
            # 暂停等待
            while _paused() and not _canceled():
                state["current"] = f"[{n}/{state['total']}] 已暂停 - {img_name} x P{pi + 1}"
                time.sleep(1)
            if _canceled():
                break
            n += 1
            state["current"] = f"[{n}/{state['total']}] {img_name} x P{pi + 1}"
            add_log(f"生成: {img_name} x P{pi + 1}")

            try:
                result = image_provider.run_sync(
                    img_path, prompt, ratio, cli_path,
                    cancel_flag=_canceled,
                )
                # 生成完成后也检查暂停（暂停时不下载，等继续）
                while _paused() and not _canceled():
                    time.sleep(1)
                if _canceled():
                    add_log("已停止", "warn")
                    break
                status = result.get("gen_status")
                if status == "success":
                    url = image_provider.extract_image_url(result)
                    if url:
                        save_path = next_numbered_output(output_dir, img_name)
                        download_image(url, save_path)
                        state["done"] = n
                        add_log(f"完成: {Path(save_path).name}")
                    else:
                        add_log(f"无图片URL: {img_name} x P{pi + 1}", "warn")
                else:
                    reason = result.get("fail_reason", "未知失败")
                    add_log(f"失败: {img_name} x P{pi + 1} - {reason}", "error")
            except Exception as e:
                add_log(f"异常: {e}", "error")

            time.sleep(2)

    state["running"] = False
    state["paused"] = False
    state["current"] = ""
    add_log(f"任务结束：完成 {state['done']}/{state['total']}")


def next_numbered_output(output_dir: str, name: str) -> str:
    """生成下一个序号文件名：name_001.png。"""
    d = Path(output_dir)
    d.mkdir(parents=True, exist_ok=True)
    max_n = 0
    for f in d.glob(f"{name}_*.png"):
        try:
            num = int(f.stem.split("_")[-1])
            if num > max_n:
                max_n = num
        except ValueError:
            pass
    return str(d / f"{name}_{max_n + 1:03d}.png")


def download_image(url: str, dest: str):
    """下载图片到本地。"""
    urllib.request.urlretrieve(url, dest)


# ==================== 积分路由 ====================
@app.route("/api/credit")
def credit():
    cfg = load_config()
    cli_path = cfg.get("image", {}).get("cli_path", "auto")
    return jsonify(image_provider.credit(cli_path))


# ==================== AI 生成 prompts 路由 ====================
@app.route("/api/ai-generate", methods=["POST"])
def ai_generate():
    data = request.json or {}
    product_info = data.get("product_info", {})
    count = data.get("count", 10)
    cfg = load_config()
    llm_cfg = cfg.get("llm", {})
    prompts = llm_provider.generate(product_info, count, llm_cfg)
    return jsonify({
        "prompts": prompts,
        "is_local": not llm_provider.is_configured(llm_cfg),
    })


# ==================== 输出管理路由 ====================
@app.route("/api/outputs")
def outputs():
    cfg = load_config()
    d = resolve_output_dir(cfg)
    files = []
    for f in sorted(d.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({"name": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime})
        if len(files) >= 200:
            break
    return jsonify({"files": files, "dir": str(d)})


@app.route("/api/open-output", methods=["POST"])
def open_output():
    cfg = load_config()
    d = resolve_output_dir(cfg)
    os.startfile(str(d))
    return jsonify({"success": True})


@app.route("/api/pick-folder", methods=["POST"])
def pick_folder():
    """弹出系统文件夹选择框，选完保存到 config 并返回路径。"""
    import subprocess, sys
    script = (
        "import tkinter as tk;from tkinter import filedialog;"
        "r=tk.Tk();r.withdraw();r.attributes('-topmost',True);"
        "p=filedialog.askdirectory(title='选择输出文件夹');"
        "r.destroy();print(p or '')"
    )
    try:
        out = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, text=True, timeout=120,
                             stdin=subprocess.DEVNULL, encoding="utf-8")
        path = (out.stdout or "").strip()
    except Exception as e:
        return jsonify({"path": "", "error": str(e)})
    if path:
        cfg = load_config()
        cfg["output_dir"] = path
        save_config(cfg)
        return jsonify({"path": path})
    return jsonify({"path": ""})


@app.route("/api/output-file/<name>")
def output_file(name):
    cfg = load_config()
    d = resolve_output_dir(cfg).resolve()
    f = (d / name).resolve()
    # 路径穿越防护
    try:
        f.relative_to(d)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not f.is_file():
        return jsonify({"error": "文件不存在"}), 404
    return send_from_directory(str(d), name)


# ==================== 版本路由 ====================
@app.route("/api/version")
def version():
    return jsonify(get_version_info())


@app.route("/api/check-update")
def check_update():
    """检查 GitHub 是否有新版本（查 latest release，无则回退最新 tag）。"""
    vi = get_version_info()
    repo = (vi.get("release_repo") or "").strip()
    if not repo:
        return jsonify({"error": "未配置 release_repo，无法检查更新"}), 400
    headers = {"Accept": "application/vnd.github+json"}
    latest, url, notes = _query_github_release(repo, headers)
    if latest is None:
        return jsonify({"error": "无法获取远程版本（仓库可能还没有 release/tag）"}), 502
    current = vi.get("version", "0.0.0")
    has_update = _compare_versions(latest, current) > 0
    return jsonify({
        "has_update": has_update,
        "current": current,
        "latest": latest,
        "release_url": url,
        "notes": notes,
    })


def _query_github_release(repo, headers):
    """查 GitHub latest release；无 release 则取最新 tag。返回 (version, url, notes)。"""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers=headers, timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            return (
                (d.get("tag_name") or "").lstrip("v"),
                d.get("html_url", ""),
                (d.get("body") or "")[:500],
            )
    except Exception:
        pass
    # 回退：查 tags
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/tags",
            headers=headers, timeout=15,
        )
        if r.status_code == 200 and r.json():
            t = r.json()[0]
            return (
                (t.get("name") or "").lstrip("v"),
                f"https://github.com/{repo}/releases",
                "",
            )
    except Exception:
        pass
    return None, "", ""


def _compare_versions(a, b):
    """语义化版本比较：a>b→1, a<b→-1, 相等→0。"""
    pa = [int(x) for x in re.findall(r"\d+", a)]
    pb = [int(x) for x in re.findall(r"\d+", b)]
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else 0
        y = pb[i] if i < len(pb) else 0
        if x > y:
            return 1
        if x < y:
            return -1
    return 0


def main():
    """启动 Flask。"""
    from config_manager import get_version_info
    vi = get_version_info()
    ver = vi.get("version", "0.0.0")
    print("=" * 50)
    print(f"MyTool v{ver}")
    print("访问 http://127.0.0.1:9527/")
    print("停止: 关闭本窗口 或 Ctrl+C")
    print("=" * 50)
    app.run(host="127.0.0.1", port=9527, debug=False, threaded=True)


if __name__ == "__main__":
    main()
