#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新 Edge 登录快照副本。

背景：
  chrome-devtools MCP（项目根 .mcp.json）用 --userDataDir 指向一份专用副本，
  让 MCP 启动的浏览器能继承日常 Edge 的登录状态，同时与日常 Edge 互不干扰。
  这份副本是"快照"：当网站登录过期后，运行本脚本重新复制刷新即可。

用法（在项目根目录执行）：
  uv run python scripts/refresh_edge_profile.py
  uv run python scripts/refresh_edge_profile.py --no-kill  # Edge 运行时需加（否则复制失败）

注意：
  本脚本的源/目标路径与 .mcp.json 的 --userDataDir 必须保持一致，
  若改动其中一处，记得同步另一处。
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# 统一按 UTF-8 输出，避免 Windows 控制台中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 源：日常 Edge 的用户数据目录
EDGE_USER_DATA = Path(r"C:\Users\Administrator\AppData\Local\Microsoft\Edge\User Data")
# 目标：chrome-devtools MCP 使用的专用副本（与 .mcp.json 的 --userDataDir 一致）
PROFILE_DIR = Path(r"C:\Users\Administrator\AppData\Local\edge-mcp-profile")

# 需要复制的"文件"（相对 User Data 根目录；同名 -journal 文件会自动一并复制）
FILES_TO_COPY = [
    "Local State",  # cookie 解密密钥，必须
    Path("Default") / "Login Data",  # 保存的账号/密码表单
    Path("Default") / "Login Data For Account",
    Path("Default") / "Preferences",  # 浏览器偏好
    Path("Default") / "Secure Preferences",
    Path("Default") / "Web Data",  # 表单/自动填充数据
    Path("Default") / "Extension Cookies",  # 扩展的 cookie
]

# 需要复制的"目录"（相对 User Data 根目录，整体复制到副本对应位置）
DIRS_TO_COPY = [
    Path("Default") / "Network",  # cookie 实际存放处（新版 Edge）
    Path("Default") / "Local Storage",  # 部分网站用 localStorage 存 token
    Path("Default") / "IndexedDB",  # 部分网站用 IndexedDB 存登录态
    Path("Default") / "Local Extension Settings",
    Path("Default") / "Extension State",
    Path("Default") / "Extension Rules",
]


def edge_is_running() -> bool:
    """检查是否有 Edge 主进程（msedge.exe，不含 webview2）在运行。"""
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq msedge.exe"],
        capture_output=True,
    )
    # 用字节判断 ASCII 的进程名，避开 Windows 控制台编码问题
    return b"msedge.exe" in result.stdout


def kill_edge() -> None:
    print("检测到 Edge 正在运行，正在结束其进程……")
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    time.sleep(2)  # 等文件锁释放
    print("Edge 已结束。")


def copy_file(src: Path, dst: Path) -> None:
    """复制单个文件，并顺带复制同名 -journal 文件（若存在）。"""
    if not src.exists():
        print(f"  跳过（不存在）：{src.as_posix()}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    # SQLite 数据库常带 -journal 回滚日志，一并复制保证一致
    journal = Path(str(src) + "-journal")
    if journal.exists():
        shutil.copy2(journal, Path(str(dst) + "-journal"))
    print(f"  已复制文件：{src.relative_to(EDGE_USER_DATA).as_posix()}")


def copy_dir(src: Path, dst: Path) -> None:
    """整体复制一个目录；先删旧目录再复制，避免残留过期文件。"""
    if not src.exists():
        print(f"  跳过（不存在）：{src.as_posix()}")
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"  已复制目录：{src.relative_to(EDGE_USER_DATA).as_posix()}")


def count_cookies() -> int:
    """读取副本里的 cookie 数量，用于验证复制结果。"""
    cookie_db = PROFILE_DIR / "Default" / "Network" / "Cookies"
    if not cookie_db.exists():
        return -1
    try:
        con = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True)
        n = con.execute("select count(*) from cookies").fetchone()[0]
        con.close()
        return n
    except Exception:
        return -1


def main() -> int:
    parser = argparse.ArgumentParser(description="刷新 Edge 登录快照副本")
    parser.add_argument(
        "--no-kill",
        action="store_true",
        help="不自动结束 Edge 进程（Edge 在运行时，cookie 等文件被锁，复制会失败）",
    )
    args = parser.parse_args()

    print("== 刷新 Edge 登录快照副本 ==")
    print(f"源（日常 Edge）：{EDGE_USER_DATA}")
    print(f"目标（MCP 副本）：{PROFILE_DIR}")
    print()

    # 1. 处理 Edge 运行状态：文件被锁就复制不了，必须先关 Edge
    if edge_is_running():
        if args.no_kill:
            print("检测到 Edge 正在运行，但指定了 --no-kill。")
            print("cookie 等文件被 Edge 独占锁住，复制会失败，请先关闭 Edge 再运行。")
            return 1
        kill_edge()
        print()

    # 2. 复制登录相关文件
    print("复制登录相关文件……")
    for rel in FILES_TO_COPY:
        copy_file(EDGE_USER_DATA / rel, PROFILE_DIR / rel)

    # 3. 复制登录相关目录
    print("复制登录相关目录……")
    for rel in DIRS_TO_COPY:
        copy_dir(EDGE_USER_DATA / rel, PROFILE_DIR / rel)

    # 4. 验证
    print()
    print("验证复制结果……")
    n = count_cookies()
    if n > 0:
        print(f"✅ 副本 cookie 数量：{n} 条，登录态已刷新。")
    else:
        print("⚠️ 未能读取副本 cookie，请检查复制是否完整。")

    print()
    print("完成。现在可以重新打开 Edge 了（副本与日常 Edge 互不干扰）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
