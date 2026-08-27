"""MyTool 主程序：Flask Web 应用，拖拽式即梦 AI 批量生图工具。

MVP 阶段：同步调用即梦 CLI（--poll=180），双层循环 图片×prompts。
"""
import json
import os
import re
import subprocess
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

# 全局状态（线程间读写），多线程修改必须持 state_lock
state_lock = threading.Lock()
# 输出文件名分配锁：防止并发下 next_numbered_output 扫描+命名时产生同序号冲突
naming_lock = threading.Lock()
state = {
    "running": False,
    "paused": False,
    "total": 0,
    "done": 0,
    "running_count": 0,   # 当前并发执行中的子任务数
    "current": "",
    "output_dir": "",
    "ratio": "1:1",
    "logs": [],
    "update_progress": {  # 自动更新进度
        "status": "idle",   # idle / downloading / downloaded / applying / error
        "version": "",
        "downloaded": 0,
        "total": 0,
        "message": "",
        "zip_path": "",
    },
}

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 自动更新：下载缓存目录 + 跨重启 pending 标记
UPDATES_DIR = BASE_DIR / "_updates"
UPDATES_DIR.mkdir(exist_ok=True)
PENDING_UPDATE_FILE = BASE_DIR / ".update_pending.json"


def add_log(msg: str, level: str = "info"):
    """添加日志，保留最近 100 条（线程安全）。"""
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "level": level}
    with state_lock:
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
    # 同步 state 缓存（避免输出目录等配置显示旧值）
    if cfg.get("output_dir"):
        state["output_dir"] = str(resolve_output_dir(cfg))
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
    with state_lock:
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
    img_cfg = cfg.get("image", {}) or {}
    cli_path = img_cfg.get("cli_path", "auto")
    # 并发参数：默认 4，范围 1~16
    try:
        max_concurrency = int(img_cfg.get("max_concurrency", 4))
    except (TypeError, ValueError):
        max_concurrency = 4
    max_concurrency = max(1, min(16, max_concurrency))
    model_version = img_cfg.get("model_version", "5.0")
    resolution_type = img_cfg.get("resolution_type", "2k")
    query_timeout = int(img_cfg.get("query_timeout", 1200) or 1200)

    t = threading.Thread(
        target=process_task,
        args=(
            images, prompts, str(output_dir), ratio, cli_path,
            max_concurrency, model_version, resolution_type, query_timeout,
        ),
        daemon=True,
    )
    t.start()
    return jsonify({"success": True, "total": len(images) * len(prompts)})


@app.route("/api/stop", methods=["POST"])
def stop():
    with state_lock:
        state["running"] = False
        state["paused"] = False
    add_log("已请求停止，当前并发任务完成后将终止", "warn")
    return jsonify({"success": True})


@app.route("/api/pause", methods=["POST"])
def pause():
    with state_lock:
        running = state["running"]
        if not running:
            return jsonify({"error": "任务未运行"}), 400
        state["paused"] = True
    add_log("已暂停，正在执行的并发任务完成当前轮询后等待继续", "warn")
    return jsonify({"success": True})


@app.route("/api/resume", methods=["POST"])
def resume():
    with state_lock:
        running = state["running"]
        paused = state["paused"]
        if not running:
            return jsonify({"error": "任务未运行"}), 400
        if not paused:
            return jsonify({"error": "任务未暂停"}), 400
        state["paused"] = False
    add_log("已继续", "info")
    return jsonify({"success": True})


def process_task(
    images, prompts, output_dir, ratio, cli_path,
    max_concurrency=4, model_version="5.0", resolution_type="2k", query_timeout=1200,
):
    """批量生成（并发版）：两阶段 → ①并发submit拿submit_id → ②并发轮询+下载。

    max_concurrency: 每阶段线程池并发上限（默认4，范围1~16）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(images) * len(prompts)
    # 初始化 state
    with state_lock:
        state["running"] = True
        state["paused"] = False
        state["total"] = total
        state["done"] = 0
        state["running_count"] = 0
        state["output_dir"] = output_dir
        state["ratio"] = ratio
        state["current"] = f"准备提交 0/{total}"

    def _canceled():
        return not state["running"]

    def _paused():
        return state.get("paused", False)

    # 构建任务列表（主线程串行 → 在此预分配 save_path，避免并发下同序号冲突）
    tasks = []
    n = 0
    # 先统计每个 img_name 当前已有的最大序号（扫描一次磁盘，比并发下反复扫描更稳）
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    img_counter: dict[str, int] = {}
    for f in out_path.glob("*.png"):
        # 格式 name_001.png → 拆分 stem
        parts = f.stem.rsplit("_", 1)
        if len(parts) == 2:
            base, num_s = parts
            try:
                num = int(num_s)
            except ValueError:
                continue
            img_counter[base] = max(img_counter.get(base, 0), num)

    for img in images:
        img_path = img.get("path", "")
        img_name = Path(img.get("name", "image")).stem
        for pi, prompt in enumerate(prompts):
            n += 1
            img_counter[img_name] = img_counter.get(img_name, 0) + 1
            seq = img_counter[img_name]
            save_path = str(out_path / f"{img_name}_{seq:03d}.png")
            label = f"{img_name} x P{pi + 1}"
            tasks.append({
                "idx": n,
                "img_path": img_path,
                "img_name": img_name,
                "pi": pi,
                "prompt": prompt,
                "label": label,
                "save_path": save_path,  # 预分配好，线程里直接用
            })

    add_log(
        f"开始任务：{len(images)} 图 × {len(prompts)} prompt = {total} 个，"
        f"并发度 {max_concurrency} 路"
    )

    # ============================================================
    # 阶段一：并发 submit（获取 submit_id）
    # ============================================================
    submitted = []  # 提交成功: {**task, "submit_id": str}
    submit_failed = []  # 提交失败: {**task, "reason": str}

    def _do_submit(task):
        # 提交前检查 暂停/停止
        while _paused() and not _canceled():
            time.sleep(1)
        if _canceled():
            return None, "已停止", task
        try:
            r = image_provider.submit(
                task["img_path"], task["prompt"], ratio, cli_path,
                model_version=model_version, resolution_type=resolution_type,
            )
            sid = r.get("submit_id")
            if sid:
                return sid, None, task
            reason = r.get("fail_reason") or "提交返回无 submit_id"
            return None, reason, task
        except Exception as e:
            return None, f"提交异常: {e}", task

    add_log(f"[阶段1/2] 并发提交 {len(tasks)} 个任务（上限 {max_concurrency} 路）...")
    with ThreadPoolExecutor(max_workers=max_concurrency) as ex:
        futures = {ex.submit(_do_submit, t): t for t in tasks}
        finished_submit = 0
        for fut in as_completed(futures):
            if _canceled():
                break  # 不再取结果
            sid, err, task = fut.result()
            finished_submit += 1
            with state_lock:
                state["current"] = f"[提交中 {finished_submit}/{len(tasks)}] 最近: {task['label']}"
            if sid:
                submitted.append({**task, "submit_id": sid})
                add_log(f"[提交OK {finished_submit}/{len(tasks)}] {task['label']} → {sid}")
            else:
                submit_failed.append({**task, "reason": err or "未知"})
                add_log(
                    f"[提交失败 {finished_submit}/{len(tasks)}] {task['label']} - {err}",
                    "error",
                )

    # 提交阶段失败的任务直接计入失败日志（不占 done 计数，因为 done 是完成数）
    for t in submit_failed:
        add_log(f"失败: {t['label']} - (提交失败) {t['reason']}", "error")

    if _canceled():
        add_log("已停止（提交阶段被中断）", "warn")
        _finalize_task(total)
        return

    if not submitted:
        add_log("所有任务提交均失败，任务结束", "error")
        _finalize_task(total)
        return

    # ============================================================
    # 阶段二：并发轮询 query_result + 下载
    # ============================================================
    add_log(
        f"[阶段2/2] 并发轮询 {len(submitted)} 个任务（上限 {max_concurrency} 路，总超时 {query_timeout}s/个）..."
    )

    def _inc_running(delta):
        with state_lock:
            state["running_count"] = max(0, state.get("running_count", 0) + delta)

    def _do_poll(task):
        """轮询单个 submit_id，返回 (success_bool, task_dict, extra_info)"""
        _inc_running(+1)
        submit_id = task["submit_id"]
        label = task["label"]
        idx = task["idx"]

        try:
            with state_lock:
                state["current"] = f"[{idx}/{total}] 生成中: {label} (并发 {state['running_count']})"

            start = time.time()
            poll_interval = 5
            while time.time() - start < query_timeout:
                # 暂停：不发 query，只 sleep
                while _paused() and not _canceled():
                    with state_lock:
                        state["current"] = f"[{idx}/{total}] 已暂停 - {label} (并发 {state['running_count']})"
                    time.sleep(1)
                if _canceled():
                    return False, task, "已停止"

                qr = image_provider.query(submit_id, cli_path)
                status = qr.get("gen_status", "")

                if status == "success":
                    # 下载前检查暂停
                    while _paused() and not _canceled():
                        time.sleep(1)
                    if _canceled():
                        return False, task, "已停止"
                    url = image_provider.extract_image_url(qr)
                    if url:
                        # save_path 由主线程预分配，零并发冲突
                        save_path = task["save_path"]
                        download_image(url, save_path)
                        with state_lock:
                            state["done"] += 1
                        add_log(f"完成: {Path(save_path).name}")
                        return True, task, Path(save_path).name
                    else:
                        return False, task, "无图片URL"
                if status in ("fail", "error"):
                    reason = qr.get("fail_reason", "远端返回失败")
                    return False, task, reason
                # pending: 继续等
                time.sleep(poll_interval)

            return False, task, f"轮询超时（{query_timeout}s）"
        except Exception as e:
            return False, task, f"轮询异常: {e}"
        finally:
            _inc_running(-1)

    success_cnt = 0
    fail_cnt = 0
    with ThreadPoolExecutor(max_workers=max_concurrency) as ex:
        futures = [ex.submit(_do_poll, t) for t in submitted]
        for fut in as_completed(futures):
            if _canceled() and not fut.done():
                fut.cancel()
                continue
            try:
                ok, task, info = fut.result()
            except Exception as e:
                ok, task, info = False, {}, f"Future异常: {e}"
            label = task.get("label", "?")
            if ok:
                success_cnt += 1
            else:
                fail_cnt += 1
                add_log(f"失败: {label} - {info}", "error")

    # 收尾
    _finalize_task(total)


def _finalize_task(total: int):
    """任务结束：重置 state，写结束日志。"""
    done = 0
    with state_lock:
        done = state["done"]
        state["running"] = False
        state["paused"] = False
        state["running_count"] = 0
        state["current"] = ""
    add_log(f"任务结束：成功 {done}/{total}")


def next_numbered_output(output_dir: str, name: str) -> str:
    """生成下一个序号文件名：name_001.png（线程安全，避免并发下同序号互相覆盖）。"""
    with naming_lock:
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
    try:
        # 确保目录存在（防止用户手动删除等情况）
        d.mkdir(parents=True, exist_ok=True)
        if not os.path.isdir(str(d)):
            return jsonify({"success": False, "error": f"目录不存在且无法创建: {d}", "dir": str(d)}), 500
        os.startfile(str(d))
        print(f"[OPEN-OUTPUT] 已打开目录: {d}")
        return jsonify({"success": True, "dir": str(d)})
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        print(f"[OPEN-OUTPUT] 打开失败: {err_msg}")
        return jsonify({"success": False, "error": err_msg, "dir": str(d)}), 500


@app.route("/api/pick-folder", methods=["POST"])
def pick_folder():
    """弹出系统文件夹选择框，选完保存到 config 并返回路径。"""
    import subprocess, sys
    # 必须用 -u 关闭 stdout 缓冲，tk 窗口要 topmost
    script = (
        "import sys,sys\nsys.stdout.reconfigure(encoding='utf-8')\n"
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r=tk.Tk()\n"
        "r.withdraw()\n"
        "r.attributes('-topmost', True)\n"
        "r.overrideredirect(True)\n"
        "r.geometry('0x0+0+0')\n"
        "r.update_idletasks();r.update()\n"
        "try:\n"
        "    p=filedialog.askdirectory(title='MyTool: 选择输出文件夹', mustexist=False)\n"
        "finally:\n"
        "    try:r.destroy()\n"
        "    except Exception:pass\n"
        "print(p or '')\n"
    )
    try:
        print("[PICK-FOLDER] 正在打开文件夹选择对话框（如果没看到，请看任务栏后面）...")
        out = subprocess.run(
            [sys.executable, "-u", "-c", script],
            capture_output=True, text=True, timeout=300,
            stdin=subprocess.DEVNULL, encoding="utf-8",
            errors="replace",
        )
        path = (out.stdout or "").strip().strip('"').strip("'")
        stderr_tip = ""
        if out.stderr and "error" in out.stderr.lower():
            stderr_tip = f" (stderr: {out.stderr.strip()[:300]})"
        print(f"[PICK-FOLDER] 用户选择: '{path}' (returncode={out.returncode}){stderr_tip}")
    except subprocess.TimeoutExpired:
        print("[PICK-FOLDER] 5分钟超时未选择文件夹，已取消")
        return jsonify({"path": "", "error": "超时（5分钟内未选择文件夹）。请重试，对话框可能被窗口挡住，请看任务栏后面。"})
    except Exception as e:
        print(f"[PICK-FOLDER] 异常: {e}")
        return jsonify({"path": "", "error": f"调用失败: {e}"})

    if not path:
        return jsonify({"path": "", "error": "未选择文件夹（点了取消）。如果没有看到选择框，请看任务栏后面。"})

    # 绝对路径安全检查 + 立刻 mkdir
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[PICK-FOLDER] 创建目录失败: {e}")
        return jsonify({"path": "", "error": f"目录不可写: {e}。请选择你有权限的文件夹。"})

    cfg = load_config()
    cfg["output_dir"] = str(p.resolve())  # 存绝对路径
    save_config(cfg)
    # 同步 state 的缓存显示，让用户立刻看到
    state["output_dir"] = str(p.resolve())
    print(f"[PICK-FOLDER] 已保存输出目录: {state['output_dir']}")
    return jsonify({"path": state["output_dir"], "success": True})


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
    latest, url, notes, download_url, file_size, asset_name = _query_github_release(repo, headers)
    if latest is None:
        # 离线软降级（Experience 829940：更新失败不影响主功能）
        current = vi.get("version", "0.0.0")
        return jsonify({
            "has_update": False,
            "current": current,
            "latest": current,
            "release_url": f"https://github.com/{repo}/releases",
            "notes": "",
            "download_url": "",
            "file_size": 0,
            "asset_name": "",
            "reachable": False,
        })
    current = vi.get("version", "0.0.0")
    has_update = _compare_versions(latest, current) > 0
    return jsonify({
        "has_update": has_update,
        "current": current,
        "latest": latest,
        "release_url": url,
        "notes": notes,
        "download_url": download_url or "",
        "file_size": int(file_size or 0),
        "asset_name": asset_name or "",
        "reachable": True,
    })


def _query_github_release(repo, headers):
    """查 GitHub latest release；无 release 则取最新 tag。

    返回: (version, url, notes, download_url, file_size, asset_name)
    download_url 只对 release 模式可用（需要 assets 里有 zip 资产）；tag 回退模式下为空。
    """
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers=headers, timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            version = (d.get("tag_name") or "").lstrip("v")
            html_url = d.get("html_url", "")
            notes = (d.get("body") or "")[:500]
            # 从 assets 里挑第一个 zip 分发包作为自动下载目标
            assets = d.get("assets") or []
            dl_url, dl_size, dl_name = "", 0, ""
            for a in assets:
                name = (a.get("name") or "").lower()
                if name.endswith(".zip"):
                    dl_url = a.get("browser_download_url") or ""
                    dl_size = int(a.get("size") or 0)
                    dl_name = a.get("name") or ""
                    break
            return version, html_url, notes, dl_url, dl_size, dl_name
    except Exception:
        pass
    # 回退：查 tags（仅能拿到版本号和 releases 列表页，无 zip 直链）
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
                "", 0, "",
            )
    except Exception:
        pass
    return None, "", "", "", 0, ""


# ==================== 自动更新接口 ====================
@app.route("/api/update-progress", methods=["GET"])
def update_progress():
    """返回当前下载更新进度（前端轮询）。"""
    with state_lock:
        return jsonify(state["update_progress"].copy())


@app.route("/api/download-update", methods=["POST"])
def download_update():
    """后台线程从 GitHub release assets 直链下载 zip 分发包（不阻塞接口返回）。"""
    data = request.json or {}
    download_url = (data.get("download_url") or "").strip()
    version = (data.get("latest") or data.get("version") or "").strip()
    expected_size = int(data.get("file_size") or 0)
    if not download_url or not version:
        return jsonify({"success": False, "error": "缺少 download_url 或 version 参数"}), 400

    with state_lock:
        current_status = state["update_progress"].get("status")
        if current_status == "downloading":
            return jsonify({"success": False, "error": "已经在下载中，请稍候"}), 400
        state["update_progress"].update({
            "status": "downloading",
            "version": version,
            "downloaded": 0,
            "total": expected_size,
            "message": f"开始下载 v{version}...",
            "zip_path": "",
        })

    zip_path = UPDATES_DIR / f"MyTool_v{version}.zip"
    part_path = zip_path.with_suffix(".zip.part")

    def _worker():
        try:
            # 先清理残留
            for p in (zip_path, part_path):
                if p.exists():
                    try: p.unlink()
                    except Exception: pass
            # 流式下载（边下边写 chunk）
            with requests.get(download_url, stream=True, timeout=(10, 600),
                              allow_redirects=True) as r:
                # Experience 925541：必须先判定响应不是 HTML 错误页/登录页
                if r.status_code != 200:
                    raise RuntimeError(f"下载 HTTP {r.status_code}")
                ct = r.headers.get("Content-Type", "")
                if ct.startswith("text/html"):
                    raise RuntimeError(
                        "响应不是文件，而是页面（可能是 GitHub 登录/错误页）。"
                        "Content-Type: " + ct
                    )
                cl = r.headers.get("Content-Length")
                total_sz = expected_size
                if cl and int(cl) > 0:
                    total_sz = int(cl)
                    if expected_size and total_sz != expected_size:
                        # size 不一致，先继续下载，写完再做校验
                        print(f"[UPDATE] Content-Length({total_sz})≠预期({expected_size})，下载后二次校验")

                downloaded = 0
                with open(str(part_path), "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        # 每 256KB 更新一次进度，避免锁竞争过强
                        if downloaded % (256 * 1024) == 0:
                            with state_lock:
                                state["update_progress"]["downloaded"] = downloaded
                                state["update_progress"]["total"] = total_sz

                # 最终进度
                with state_lock:
                    state["update_progress"]["downloaded"] = downloaded
                    state["update_progress"]["total"] = total_sz

            # Content-Type 判定：下载完再次校验文件类型 + 大小
            actual_sz = part_path.stat().st_size
            if expected_size and abs(actual_sz - expected_size) > max(4096, expected_size * 0.01):
                raise RuntimeError(
                    f"下载后大小校验失败（预期 {expected_size}，实际 {actual_sz}）"
                )
            # zip 文件合法性校验（是否真的是 zip，不是假文件）
            import zipfile
            if not zipfile.is_zipfile(str(part_path)):
                raise RuntimeError("下载的文件不是合法 zip（可能被重定向到错误页面）")

            # 校验通过，.part → .zip
            part_path.replace(str(zip_path))

            with state_lock:
                state["update_progress"].update({
                    "status": "downloaded",
                    "message": f"✅ v{version} 下载完成，等待应用更新",
                    "zip_path": str(zip_path),
                    "downloaded": actual_sz,
                    "total": actual_sz,
                })
            add_log(f"[自动更新] v{version} 下载完成：{zip_path.name} ({actual_sz//1024} KB)")

        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            # 清理残留
            for p in (zip_path, part_path):
                try:
                    if p.exists(): p.unlink()
                except Exception: pass
            with state_lock:
                state["update_progress"].update({
                    "status": "error",
                    "message": "❌ 下载失败：" + err,
                })
            add_log(f"[自动更新] 下载失败：{err}", "error")

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"success": True, "message": "已开始后台下载"})


@app.route("/api/apply-update", methods=["POST"])
def apply_update():
    """校验 zip → 写 pending 标记 → 启动独立 apply_update.bat → 返回（不立即退出）。

    apply_update.bat 会等待几秒确保 Flask 响应被前端收完，然后：
    备份 → 解压覆盖 → 重新启动 启动.bat。
    """
    import zipfile
    with state_lock:
        up = state["update_progress"]
        if up.get("status") != "downloaded":
            return jsonify({"success": False, "error": f"当前状态不允许应用更新: {up.get('status')}"}), 400
        zip_path = Path(up.get("zip_path") or "")
        version = up.get("version") or ""

    if not zip_path.exists():
        with state_lock:
            state["update_progress"].update({"status": "error", "message": "更新文件不存在"})
        return jsonify({"success": False, "error": "更新文件不存在"}), 500
    if not zipfile.is_zipfile(str(zip_path)):
        with state_lock:
            state["update_progress"].update({"status": "error", "message": "更新文件不是合法 zip"})
        return jsonify({"success": False, "error": "更新文件不是合法 zip"}), 500

    # 跨重启 pending 标记（apply_update.py 会读取并执行替换，成功后写 status=done）
    pending = {
        "status": "pending",
        "zip_path": str(zip_path.resolve()),
        "target_dir": str(BASE_DIR.resolve()),
        "version": version,
        "backup_dir": str((BASE_DIR / f"_backup_before_v{version}").resolve()),
        "created_at": datetime.now().isoformat(),
    }
    try:
        with open(str(PENDING_UPDATE_FILE), "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return jsonify({"success": False, "error": f"写入 pending 标记失败: {e}"}), 500

    with state_lock:
        state["update_progress"].update({"status": "applying", "message": "准备替换，即将重启..."})
    add_log(f"[自动更新] 准备应用 v{version}，启动 apply_update.bat...")

    # 启动独立更新脚本（不等待，父子进程解耦）
    bat_path = BASE_DIR / "apply_update.bat"
    if not bat_path.exists():
        with state_lock:
            state["update_progress"].update({"status": "error", "message": "缺少 apply_update.bat"})
        return jsonify({"success": False, "error": "缺少 apply_update.bat，无法应用更新"}), 500

    try:
        # Experience 829940：升级应用与 Flask 分离；独立脚本执行替换与重启
        subprocess.Popen(
            ['cmd.exe', '/C', 'start', '', '/WAIT', 'cmd.exe', '/C', '"' + str(bat_path) + '"'],
            cwd=str(BASE_DIR),
            creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
        )
    except Exception as e:
        with state_lock:
            state["update_progress"].update({"status": "error", "message": f"启动 apply_update.bat 失败: {e}"})
        return jsonify({"success": False, "error": f"启动 apply_update.bat 失败: {e}"}), 500

    # 不在这里 sys.exit — 响应先给前端，bat 脚本会等待 5 秒后自动杀死 Flask + 替换 + 重启
    return jsonify({"success": True, "message": "更新包已准备，将在 5 秒后自动重启应用"})


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


def _process_pending_update():
    """启动时读取跨重启的 .update_pending.json 状态标记，清理并输出结果日志。"""
    if not PENDING_UPDATE_FILE.exists():
        return None
    try:
        with open(str(PENDING_UPDATE_FILE), "r", encoding="utf-8") as f:
            pending = json.load(f)
    except Exception as e:
        # 损坏的标记文件：改名为 .bak 避免阻塞下次启动
        try:
            PENDING_UPDATE_FILE.rename(str(PENDING_UPDATE_FILE) + ".corrupt")
        except Exception:
            pass
        return {"ok": False, "error": f"pending标记解析失败: {e}"}

    status = pending.get("status", "?")
    version = pending.get("version", "?")

    if status == "done":
        # 独立脚本 apply_update.py 已经成功完成替换并写了 done
        # 清理 pending 文件，后续启动不再打扰
        try:
            PENDING_UPDATE_FILE.unlink()
        except Exception:
            pass
        from config_manager import get_version_info
        actual = (get_version_info() or {}).get("version", "?")
        return {
            "ok": True,
            "status": "done",
            "version": version,
            "actual": actual,
            "message": f"✅ 更新完成：v{version}，当前实际版本 v{actual}",
        }
    if status == "pending":
        # 上次替换未完成（比如 bat 被用户中途关闭 / 系统重启杀了进程）
        # 保留 pending 文件以便用户下次再应用，但打个告警
        return {
            "ok": False,
            "status": "pending",
            "version": version,
            "message": f"⚠️ 上一次 v{version} 更新未完成（apply_update 没走完），可再次尝试「应用更新」",
        }
    if status == "error":
        # 替换失败，保留 pending 用于排错
        reason = pending.get("error", "未知错误")
        return {
            "ok": False,
            "status": "error",
            "version": version,
            "message": f"❌ 上次 v{version} 更新失败：{reason}",
        }
    return {"ok": False, "status": status, "version": version, "message": f"未知更新状态: {status}"}


def main():
    """启动 Flask。"""
    from config_manager import get_version_info
    vi = get_version_info()
    ver = vi.get("version", "0.0.0")
    print("=" * 50)
    print(f"MyTool v{ver}")
    print("访问 http://127.0.0.1:9527/")
    print("停止: 关闭本窗口 或 Ctrl+C")

    # 处理跨重启的更新状态
    upd = _process_pending_update()
    if upd:
        print(f"[自动更新] {upd.get('message', '')}")
        # 把结果写进 state.update_progress，前端打开时能看到
        with state_lock:
            state["update_progress"].update({
                "status": "done" if upd.get("ok") else "error",
                "version": upd.get("version", ""),
                "message": upd.get("message", ""),
            })

    print("=" * 50)
    app.run(host="127.0.0.1", port=9527, debug=False, threaded=True)


if __name__ == "__main__":
    main()
