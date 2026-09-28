"""应用启动器：一键拉起 Web 服务（含前端）与目录监控，并自动打开浏览器.

与前后端解耦：不 import src/ 任何模块，仅通过子进程调用现有 CLI 命令
（`python -m src.cli web` / `python -m src.cli watch`）。

用法：
    uv run python scripts/launcher.py [--host 127.0.0.1] [--port 8000]
                                      [--no-web] [--no-watch] [--no-browser]
"""

from __future__ import annotations

import argparse
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

# 项目根目录（本文件位于 <root>/scripts/launcher.py）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

READY_TIMEOUT_SEC = 60.0  # 首次启动需加载 torch 等重依赖，等待时间放宽
READY_POLL_INTERVAL_SEC = 1.0
STOP_TIMEOUT_SEC = 10.0


def find_python(project_root: Path) -> list[str]:
    """定位运行后端的 Python 命令前缀.

    优先使用项目 .venv 中的解释器（避免 uv 每次 sync 检查的开销），
    不存在时回退 `uv run python`。
    """
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return [str(venv_python)]
    return ["uv", "run", "python"]


def is_port_in_use(host: str, port: int) -> bool:
    """TCP 连接探测端口是否已被占用."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def wait_ready(host: str, port: int, timeout: float = READY_TIMEOUT_SEC) -> bool:
    """轮询首页直至 HTTP 响应或超时，返回是否就绪."""
    url = f"http://{host}:{port}/"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status < 500:
                    return True
        except OSError:
            pass  # 服务尚未就绪，继续等待
        time.sleep(READY_POLL_INTERVAL_SEC)
    return False


def build_commands(
    python_prefix: list[str], host: str, port: int, with_web: bool, with_watch: bool
) -> dict[str, list[str]]:
    """组装各组件的子进程命令（均以项目根为 cwd 运行）."""
    commands: dict[str, list[str]] = {}
    if with_web:
        commands["web"] = [
            *python_prefix,
            "-m",
            "src.cli",
            "web",
            "--host",
            host,
            "--port",
            str(port),
        ]
    if with_watch:
        commands["watch"] = [*python_prefix, "-m", "src.cli", "watch"]
    return commands


def start_processes(commands: dict[str, list[str]], cwd: Path) -> dict[str, subprocess.Popen]:
    """拉起全部子进程；Windows 下使用独立进程组以便发送 CTRL_BREAK."""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    processes: dict[str, subprocess.Popen] = {}
    for name, cmd in commands.items():
        print(f"[launcher] 启动 {name}: {' '.join(cmd)}")
        processes[name] = subprocess.Popen(cmd, cwd=cwd, creationflags=creationflags)
    return processes


def stop_processes(processes: dict[str, subprocess.Popen]) -> None:
    """优雅回收子进程：先 CTRL_BREAK/terminate，超时后 kill."""
    for name, proc in processes.items():
        if proc.poll() is not None:
            continue
        print(f"[launcher] 正在停止 {name} (pid={proc.pid}) ...")
        try:
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
        except OSError:
            pass
    deadline = time.monotonic() + STOP_TIMEOUT_SEC
    for proc in processes.values():
        remaining = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
    for proc in processes.values():
        proc.wait()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="日常录音分析工具一键启动器")
    parser.add_argument("--host", default="127.0.0.1", help="Web 服务监听地址")
    parser.add_argument("--port", default=8000, type=int, help="Web 服务监听端口")
    parser.add_argument("--no-web", action="store_true", help="不启动 Web 服务")
    parser.add_argument("--no-watch", action="store_true", help="不启动目录监控")
    parser.add_argument("--no-browser", action="store_true", help="不就绪后自动打开浏览器")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with_web = not args.no_web
    with_watch = not args.no_watch

    if not with_web and not with_watch:
        print("[launcher] --no-web 与 --no-watch 不能同时使用：没有可启动的组件。")
        return 2

    if with_web and is_port_in_use(args.host, args.port):
        print(
            f"[launcher] 端口 {args.host}:{args.port} 已被占用，"
            f"请先关闭占用进程或使用 --port 指定其他端口。"
        )
        return 2

    python_prefix = find_python(PROJECT_ROOT)
    commands = build_commands(python_prefix, args.host, args.port, with_web, with_watch)
    processes = start_processes(commands, PROJECT_ROOT)

    exit_code = 0
    try:
        if with_web:
            print(f"[launcher] 等待 Web 服务就绪（最长 {READY_TIMEOUT_SEC:.0f}s）...")
            if wait_ready(args.host, args.port):
                url = f"http://{args.host}:{args.port}/"
                print(f"[launcher] 服务已就绪: {url}")
                if not args.no_browser:
                    webbrowser.open(url)
            else:
                print("[launcher] 等待超时，服务未就绪；请查看上方日志排查。")
                stop_processes(processes)
                return 1

        print("[launcher] 全部组件运行中，按 Ctrl+C 停止。")
        # 常驻监控：任一子进程退出则整体收尾
        while True:
            for name, proc in processes.items():
                code = proc.poll()
                if code is not None:
                    print(f"[launcher] 子进程 {name} 已退出，退出码 {code}")
                    exit_code = code if code else 1
                    return exit_code
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[launcher] 收到 Ctrl+C，正在停止所有组件...")
    finally:
        stop_processes(processes)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
