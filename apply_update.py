"""独立自动更新脚本（由 apply_update.bat 在 Flask 退出后调用）。

读取 BASE_DIR/.update_pending.json → 备份旧文件 → 解压 MyTool_v{ver}.zip 覆盖 → 校验 → 写 status=done。
失败时写 status=error，并尽量回滚。

退出码: 0 成功, 1 失败
"""
import os
import sys
import json
import shutil
import zipfile
import traceback
from pathlib import Path

# 脚本自身目录 = 软件根目录（与 app.py / 启动.bat 同级）
BASE_DIR = Path(__file__).resolve().parent
PENDING_FILE = BASE_DIR / ".update_pending.json"
LOG_FILE = BASE_DIR / "_updates" / f"apply_{os.getpid()}.log"


def log(msg: str):
    """写控制台 + 日志文件（bat 运行时控制台可能一闪而过，留日志排错）。"""
    line = f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(exist_ok=True)
        with open(str(LOG_FILE), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def mark_status(pending: dict, status: str, error: str = ""):
    pending["status"] = status
    if error:
        pending["error"] = error
    try:
        with open(str(PENDING_FILE), "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"[WARN] 写pending失败: {e}")


def main() -> int:
    log(f"=== apply_update 启动 ===")
    log(f"BASE_DIR = {BASE_DIR}")

    if not PENDING_FILE.exists():
        log(f"[EXIT] 找不到 {PENDING_FILE.name}，无需应用更新")
        return 0

    pending = {}
    try:
        with open(str(PENDING_FILE), "r", encoding="utf-8") as f:
            pending = json.load(f)
    except Exception as e:
        log(f"[FATAL] 读取 pending 失败: {e}")
        return 1

    zip_path = Path(pending.get("zip_path", ""))
    target_dir = Path(pending.get("target_dir", ""))
    backup_dir = Path(pending.get("backup_dir", "") or str(BASE_DIR / f"_backup_before_{pending.get('version','x')}"))
    version = pending.get("version", "?")

    log(f"版本: {version}")
    log(f"更新包: {zip_path} (存在={zip_path.exists()})")
    log(f"目标目录: {target_dir}")
    log(f"备份目录: {backup_dir}")

    # 1. 基础校验
    if not zip_path.exists():
        mark_status(pending, "error", f"更新包不存在: {zip_path}")
        log(f"[FATAL] 更新包不存在")
        return 1
    if not zipfile.is_zipfile(str(zip_path)):
        mark_status(pending, "error", f"更新包不是合法zip")
        log(f"[FATAL] 更新包不是合法 zip")
        return 1

    # 2. 枚举 zip 里的所有条目，决定要覆盖哪些文件（跳过空目录条目）
    with zipfile.ZipFile(str(zip_path), "r") as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]

    log(f"zip 内共 {len(names)} 个文件（非目录）")
    if not names:
        mark_status(pending, "error", "zip 内无任何文件")
        return 1

    # 3. 备份（把 target_dir 下**已经存在且即将被覆盖**的旧文件，按相对路径 move 到 backup_dir）
    #    这样回滚时只需把 backup_dir 的内容复制回来
    backup_dir.mkdir(parents=True, exist_ok=True)
    rollback_list: list[tuple[Path, Path]] = []  # (src_in_target, backup_src_in_backup_dir)

    def safe_rel(p: Path, base: Path) -> str:
        try:
            return str(p.resolve().relative_to(base.resolve()))
        except Exception:
            return p.name

    try:
        for rel in names:
            old_file = target_dir / rel
            if not old_file.exists():
                continue
            # 防止相对路径穿越
            try:
                old_file.resolve().relative_to(target_dir.resolve())
            except Exception:
                log(f"[SKIP] 越界路径，不处理: {rel}")
                continue
            bk_file = backup_dir / rel
            bk_file.parent.mkdir(parents=True, exist_ok=True)
            # 备份目标如果已存在（可能上次残留），先删再搬
            if bk_file.exists():
                try: bk_file.unlink()
                except Exception as e: log(f"[WARN] 清理旧备份失败 {bk_file}: {e}")
            shutil.move(str(old_file), str(bk_file))
            rollback_list.append((old_file, bk_file))
        log(f"已备份 {len(rollback_list)} 个旧文件到 {backup_dir}")

        # 4. 解压覆盖（按相对路径写到 target_dir）
        extracted = 0
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            for rel in names:
                dst = target_dir / rel
                # 越界保护
                try:
                    dst.resolve().relative_to(target_dir.resolve())
                except Exception:
                    log(f"[SKIP] zip含越界条目，跳过: {rel}")
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                # 解出到临时文件再 move，避免中途损坏
                tmp = dst.with_suffix(dst.suffix + ".new")
                try:
                    with zf.open(rel) as src_fp, open(str(tmp), "wb") as dst_fp:
                        shutil.copyfileobj(src_fp, dst_fp)
                    if dst.exists():
                        dst.unlink()
                    tmp.replace(str(dst))
                    extracted += 1
                except Exception as e:
                    # 解压中途失败 → 立刻回滚
                    log(f"[FATAL] 解压失败 {rel}: {e}")
                    raise RuntimeError(f"解压 {rel} 失败: {e}")
        log(f"解压并覆盖完成，共 {extracted} 个文件")

        # 5. 最小校验：关键文件存在 + version.json 能读
        checks = [
            target_dir / "app.py",
            target_dir / "version.json",
            target_dir / "启动.bat",
        ]
        for c in checks:
            if not c.exists():
                raise RuntimeError(f"校验失败，关键文件缺失: {c}")
        with open(str(target_dir / "version.json"), "r", encoding="utf-8") as f:
            vi = json.load(f)
        actual_ver = vi.get("version", "?")
        log(f"校验通过，新的 version.json → {actual_ver}")

        # 6. 标记 done（main 启动时会读到并清理 pending）
        mark_status(pending, "done")
        log(f"=== 应用更新成功：v{version} → v{actual_ver} ===")
        return 0

    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        log(f"[FATAL] 应用更新失败，开始回滚...\n{err}")
        # 回滚：把 rollback_list 里的备份 move 回来
        restored = 0
        for (old_target, bk_src) in rollback_list:
            try:
                if not bk_src.exists():
                    continue
                old_target.parent.mkdir(parents=True, exist_ok=True)
                if old_target.exists():
                    old_target.unlink()
                shutil.move(str(bk_src), str(old_target))
                restored += 1
            except Exception as re:
                log(f"[WARN] 回滚失败 {old_target}: {re}")
        log(f"回滚完成，恢复 {restored}/{len(rollback_list)} 个旧文件。备份目录保留: {backup_dir}")
        mark_status(pending, "error", str(e))
        return 1


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as e:
        log(f"[UNEXPECTED] {traceback.format_exc()}")
        rc = 1
    sys.exit(rc)
