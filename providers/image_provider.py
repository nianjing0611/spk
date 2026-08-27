"""即梦 CLI 封装：通过 dreamina.exe 调用即梦图生图接口。

支持两种模式：
- run_sync：同步阻塞（--poll=180），MVP 阶段用
- submit + query：异步分离（--poll=0 + 独立轮询），稳定版用
"""
import json
import os
import re
import subprocess
from pathlib import Path
from shutil import which

from config_manager import BASE_DIR, RESOURCE_DIR


def find_dreamina(cli_path: str = "auto") -> str | None:
    """探测 dreamina.exe 路径。

    优先级：手动指定 > BASE/bin > RESOURCE/bin > ~/bin > 系统 PATH
    """
    if cli_path and cli_path != "auto":
        if os.path.isfile(cli_path):
            return cli_path
    candidates = [
        BASE_DIR / "bin" / "dreamina.exe",
        RESOURCE_DIR / "bin" / "dreamina.exe",
        Path.home() / "bin" / "dreamina.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    found = which("dreamina") or which("dreamina.exe")
    return found


def _run_dreamina(args: list, timeout: int = 300) -> dict:
    """执行 dreamina 命令（数组形式，不 shell=True），返回解析后的 JSON dict。"""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"gen_status": "fail", "fail_reason": "CLI 超时"}
    except FileNotFoundError:
        return {"gen_status": "fail", "fail_reason": "dreamina.exe 未找到"}
    except Exception as e:
        return {"gen_status": "fail", "fail_reason": f"CLI 异常: {e}"}

    return _parse_output(result.stdout or "", result.stderr or "")


def _parse_output(stdout: str, stderr: str = "") -> dict:
    """解析 dreamina CLI 的 stdout JSON。"""
    # 先尝试直接 JSON 解析
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass
    # 回退：从输出里提取 JSON 对象
    m = re.search(r"\{.*\}", stdout, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {
        "gen_status": "fail",
        "fail_reason": f"输出解析失败: {(stdout or stderr)[:200]}",
    }


def login(cli_path: str = "auto") -> dict:
    """引导用户登录即梦账号（登录是交互式的，需在终端执行）。"""
    exe = find_dreamina(cli_path)
    if not exe:
        return {"success": False, "error": "dreamina.exe 未找到，请在设置面板配置 cli_path"}
    return {"success": True, "exe": exe, "message": "请在终端运行: {exe} login".format(exe=exe)}


def submit(
    image_path: str,
    prompt: str,
    ratio: str = "1:1",
    cli_path: str = "auto",
    model_version: str = "5.0",
    resolution_type: str = "2k",
) -> dict:
    """异步提交图生图任务（--poll=0），立即返回 submit_id。

    返回即梦 JSON：{gen_status, submit_id, fail_reason, ...}
    """
    exe = find_dreamina(cli_path)
    if not exe:
        return {"gen_status": "fail", "fail_reason": "dreamina.exe 未找到"}
    args = [
        exe, "image2image",
        f"--images={image_path}",
        f"--prompt={prompt}",
        f"--ratio={ratio}",
    ]
    if model_version:
        args.append(f"--model_version={model_version}")
    if resolution_type:
        args.append(f"--resolution_type={resolution_type}")
    args.append("--poll=0")
    return _run_dreamina(args, timeout=60)


def query(submit_id: str, cli_path: str = "auto") -> dict:
    """轮询任务结果，返回 {gen_status, result_json, fail_reason}。"""
    exe = find_dreamina(cli_path)
    if not exe:
        return {"gen_status": "fail", "fail_reason": "dreamina.exe 未找到"}
    args = [exe, "query_result", f"--submit_id={submit_id}"]
    return _run_dreamina(args, timeout=120)


def run_sync(
    image_path: str,
    prompt: str,
    ratio: str = "1:1",
    cli_path: str = "auto",
    timeout: int = 300,
) -> dict:
    """同步图生图（--poll=180 阻塞等待，MVP 阶段用）。

    内部调 submit + 循环 query，统一返回格式。
    """
    exe = find_dreamina(cli_path)
    if not exe:
        return {"gen_status": "fail", "fail_reason": "dreamina.exe 未找到"}
    cmd = [
        exe, "image2image",
        f"--images={image_path}",
        f"--prompt={prompt}",
        f"--ratio={ratio}",
        "--poll=180",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="ignore",
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"gen_status": "fail", "fail_reason": "CLI 超时（5 分钟）"}
    except FileNotFoundError:
        return {"gen_status": "fail", "fail_reason": "dreamina.exe 未找到"}
    return _parse_output(result.stdout or "", result.stderr or "")


def list_remote(cli_path: str = "auto", limit: int = 100) -> dict:
    """查远端任务列表（崩溃恢复用）。"""
    exe = find_dreamina(cli_path)
    if not exe:
        return {"tasks": [], "error": "dreamina.exe 未找到"}
    args = [exe, "list_task", f"--limit={limit}"]
    return _run_dreamina(args, timeout=60)


def credit(cli_path: str = "auto") -> dict:
    """查积分余额。"""
    exe = find_dreamina(cli_path)
    if not exe:
        return {"total_credit": 0, "error": "dreamina.exe 未找到"}
    args = [exe, "user_credit"]
    return _run_dreamina(args, timeout=30)


def extract_image_url(result: dict) -> str | None:
    """从即梦返回结果提取图片 URL。"""
    rj = result.get("result_json") or {}
    images = rj.get("images") or []
    if images and isinstance(images, list):
        return images[0].get("image_url")
    return None
