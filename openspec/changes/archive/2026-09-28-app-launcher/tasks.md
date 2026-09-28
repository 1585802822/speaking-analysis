# 任务清单：应用启动器（app-launcher）

## 需求（open 阶段已确认）

- 一键入口（双击可用）同时拉起：Web 服务（FastAPI，内含前端静态页）+ 目录监控 watch + 自动打开浏览器
- 启动器与前后端解耦：不 import `src/` 任何模块，只通过子进程调用现有 CLI 命令
- 形态：Python 脚本 `scripts/launcher.py` + 双击入口 `scripts/start.bat`（不打包 exe）

## 设计阶段

- [x] 编写设计文档 `openspec/changes/app-launcher/design.md` <!-- comet-task:13cb8393-5cca-401d-b956-2c47a55a78af -->
- [x] 用户确认方案（计划审批通过：Python 脚本 + start.bat，拉起 web+watch+浏览器） <!-- comet-task:940ed705-fdf7-4d5a-95ae-de21b8985499 -->

## 实现阶段

- [x] Task 1: `scripts/launcher.py` — Python 定位（优先 `.venv/Scripts/python.exe`，回退 `uv run python`）、端口预检、拉起 web/watch 子进程（cwd=项目根） <!-- comet-task:ac8e9d2a-a74c-457a-9a1a-78ab49e50a36 -->
- [x] Task 2: `scripts/launcher.py` — 就绪轮询 `http://<host>:<port>/`（超时 ~60s）、就绪后 `webbrowser.open`、Ctrl+C 优雅回收两个子进程（CREATE_NEW_PROCESS_GROUP + CTRL_BREAK）、任一子进程意外退出时清理并以非零码退出 <!-- comet-task:fed6500a-2b1d-46c6-b574-f79ea21b27c7 -->
- [x] Task 3: `scripts/launcher.py` — 参数 `--host`/`--port`/`--no-web`/`--no-watch`/`--no-browser` <!-- comet-task:90182a19-5296-4b3c-b1cd-aa18a38bd85f -->
- [x] Task 4: `scripts/start.bat` — 双击入口，`cd /d "%~dp0\.."` 后 `uv run python scripts\launcher.py %*`，失败 pause <!-- comet-task:3869e85b-5522-438b-8880-4b0728f2850d -->
- [x] Task 5: `tests/test_launcher.py` — Python 定位、端口检测、就绪轮询、参数解析的单元测试（mock，不真起服务） <!-- comet-task:08306dbd-7b37-444d-a222-6aeb976a087d -->
- [x] Task 6: 文档 — `README.md` 新增「快速启动」小节（中英双语）；`CHANGELOG.md` 记一笔（0.2.0 → 0.3.0）；`TODO.md` 更新 <!-- comet-task:99de6a7c-4f70-43a6-a35d-b25fa51d2a21 -->

## 验证阶段

- [x] `uv run pytest tests/test_launcher.py` 通过，且 `uv run pytest tests/` 全量不回归 <!-- comet-task:9eca581c-d21b-44ea-92c5-7a94e338aad1 -->
- [x] `uv run python scripts/launcher.py --no-browser` 实际启动：8000 端口就绪、watch 存活、`http://127.0.0.1:8000/` 可访问 <!-- comet-task:4e9651e9-bf4f-476d-bf5f-f7b917a07768 -->
- [x] Ctrl+C 后两个子进程被回收、端口释放 <!-- comet-task:d0a329fc-13c6-47e2-a644-f4d889224102 -->
- [x] 双击 `scripts/start.bat` 冒烟验证 <!-- comet-task:c0045467-04c8-4c0e-8f1d-dcb96cf34af0 -->
- [x] 提交前 `uv run ruff format` + `uv run ruff check --fix` 改动文件 <!-- comet-task:7b8ec4f4-38b5-430a-aec6-481bc2938149 -->
