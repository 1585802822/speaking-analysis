---
archived-with: 2026-09-28-app-launcher
status: final
---
# 应用启动器（app-launcher）实施计划

## 目标

新增与前后端解耦的一键启动入口：`scripts/launcher.py`（纯标准库，仅子进程调用现有 CLI）+ `scripts/start.bat`（双击入口），同时拉起 Web 服务（含前端）、目录监控 watch，并就绪后自动打开浏览器。

## 权威任务清单

任务完成状态以 `openspec/changes/app-launcher/tasks.md` 为准，本计划按 comet-task ID 引用：

### 实现

- `ac8e9d2a-a74c-457a-9a1a-78ab49e50a36` Task 1：`scripts/launcher.py` — `find_python` / `is_port_in_use` / `build_commands` / `start_processes`
- `fed6500a-2b1d-46c6-b574-f79ea21b27c7` Task 2：`scripts/launcher.py` — `wait_ready` / `stop_processes` / 常驻监控与异常收尾
- `90182a19-5296-4b3c-b1cd-aa18a38bd85f` Task 3：`scripts/launcher.py` — `parse_args` 与 `main` 流程编排
- `3869e85b-5522-438b-8880-4b0728f2850d` Task 4：`scripts/start.bat` — 双击入口
- `08306dbd-7b37-444d-a222-6aeb976a087d` Task 5：`tests/test_launcher.py` — 单元测试（全 mock）
- `99de6a7c-4f70-43a6-a35d-b25fa51d2a21` Task 6：README / CHANGELOG / TODO 更新

### 验证

- `9eca581c-d21b-44ea-92c5-7a94e338aad1` pytest 通过且不回归
- `4e9651e9-bf4f-476d-bf5f-f7b917a07768` 实际启动验证（端口就绪、watch 存活、首页可访问）
- `d0a329fc-13c6-47e2-a644-f4d889224102` Ctrl+C 回收验证
- `c0045467-04c8-4c0e-8f1d-dcb96cf34af0` start.bat 双击冒烟
- `7b8ec4f4-38b5-430a-aec6-481bc2938149` ruff format + check

## 验收标准

1. 双击 `scripts/start.bat` 后，Web 服务就绪并自动打开 `http://127.0.0.1:8000/`，watch 同步运行。
2. Ctrl+C 后两个子进程均被回收、端口释放。
3. 启动器不 import `src/` 任何模块（解耦）。
4. `uv run pytest tests/` 全量通过。
