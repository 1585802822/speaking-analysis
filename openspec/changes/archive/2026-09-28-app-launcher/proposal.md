# 提案：应用启动器（app-launcher）

## Why

当前启动本工具需要多个手动步骤：一个终端跑 `uv run python -m src.cli web` 启动 Web 服务，另一个终端跑 `python -m src.cli watch` 启动目录监控，再手动打开浏览器。日常使用门槛高、易漏步骤。

## What Changes

- 新增 `scripts/launcher.py`：与前后端解耦的一键启动器（纯标准库，仅通过子进程调用现有 CLI），一键拉起 Web 服务（含前端）+ watch 监控，就绪后自动打开浏览器，Ctrl+C 优雅回收。
- 新增 `scripts/start.bat`：双击入口。
- 新增 `tests/test_launcher.py` 单元测试；README 新增「快速启动」小节；版本 0.2.0 → 0.3.0。
