# Comet Design Handoff

- Change: app-launcher
- Phase: design
- Mode: compact
- Context hash: f8f22729220c4dcfe3e8418d77f32b69338ddf09df950c551f46bb0d59fe8b7d

Generated-by: comet-handoff.sh
Task hash policy: task-content-v1. Read tasks.md for live completion; excerpts are design-time context.

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/app-launcher/proposal.md

- Source: openspec/changes/app-launcher/proposal.md
- Lines: 1-25
- SHA256: f99f3fe2cde06ec91e75f3bfe9e9cc014ffd8d100b65106133a93ea22428d512

```md
# 提案：应用启动器（app-launcher）

## 背景与问题

当前启动本工具需要多个手动步骤：

1. 开一个终端运行 `uv run python -m src.cli web` 启动 Web 服务（FastAPI 托管 API 与前端静态页）；
2. 另开一个终端运行 `uv run python -m src.cli watch` 启动录音目录监控；
3. 手动打开浏览器访问 `http://127.0.0.1:8000/`。

对日常使用（非开发场景）门槛高、易漏步骤。

## 目标

提供一个**双击即用**的入口，一键完成：启动 Web 服务（含前端）+ 启动目录监控 watch + 服务就绪后自动打开浏览器。

## 关键约束（已与用户确认）

- 启动器与前后端**解耦**：不 import `src/` 任何模块，仅通过子进程调用现有 CLI 命令；前后端内部改动不影响启动器。
- 形态：**Python 脚本 + start.bat**（`scripts/launcher.py` + `scripts/start.bat`），不使用 PyInstaller 打包 exe。
- 遵循项目目录规范：根目录只放配置文件与全局文档，启动器落位 `scripts/`。

## 非目标

- 不改造前后端代码；不引入新的依赖；不做跨平台（项目本身限定 Windows x64）。

```

## openspec/changes/app-launcher/design.md

- Source: openspec/changes/app-launcher/design.md
- Lines: 1-61
- SHA256: 997f7258dbbf6762661ae7d7a010aa7980491d25adf3ff6107e4707a8b883e52

```md
---
comet_change: app-launcher
role: technical-design
canonical_spec: openspec
---

# 设计文档：应用启动器（app-launcher）

## 现状

- 后端入口：`src/cli.py` 的 `web` 命令（uvicorn，默认 `127.0.0.1:8000`）；`watch` 命令为录音目录监控。
- 前端：`src/web/static/` 静态文件由 FastAPI 直接托管，同源相对路径调 API，无需独立前端服务。
- 环境：Windows x64 only，`.venv/` 已存在，uv 已安装。
- `config.yaml` 与 `data/` 均为相对 CWD 路径 → 子进程必须以项目根目录为 cwd。

## 方案

### 组件

```
scripts/launcher.py   # 核心启动器（纯标准库）
scripts/start.bat     # 双击入口，透传参数
```

### 启动流程

1. 解析参数：`--host`（默认 127.0.0.1）、`--port`（默认 8000）、`--no-web`、`--no-watch`、`--no-browser`。
2. 定位 Python：优先 `<项目根>/.venv/Scripts/python.exe`（避免 uv 每次 sync 检查的开销），不存在则回退 `uv run python`。
3. 端口预检：TCP 连接探测，被占则报错退出并提示换 `--port`。
4. 拉起子进程（cwd=项目根，Windows 下 `CREATE_NEW_PROCESS_GROUP`）：
   - `python -m src.cli web --host <host> --port <port>`（`--no-web` 跳过）
   - `python -m src.cli watch`（`--no-watch` 跳过）
5. 就绪等待：轮询 `http://<host>:<port>/` 至 HTTP 响应或超时（~60s，首次加载 torch 等重依赖较慢）；就绪后 `webbrowser.open`（`--no-browser` 跳过）。
6. 常驻监控：任一子进程意外退出 → 打印退出码、清理另一进程、以非零码退出；Ctrl+C / 控制台关闭 → 先 `CTRL_BREAK_EVENT`/terminate 再 kill 两个子进程。

### 解耦设计

启动器不 import `src/` 任何模块，仅通过子进程组合现有 CLI 命令；自身无业务逻辑，前后端内部实现变化不影响它。若未来前端独立部署，只需在 launcher 中增加一条子进程命令，无需改动前后端。

### start.bat

```bat
@echo off
cd /d "%~dp0\.."
uv run python scripts\launcher.py %*
if errorlevel 1 pause
```

### 测试策略

`tests/test_launcher.py` 覆盖关键纯函数，全部 mock，不真起服务、不依赖真实音频：

- Python 解释器定位（`.venv` 存在/不存在两条路径）
- 端口占用检测（socket 绑定模拟占用/空闲）
- 就绪轮询（mock urllib：成功、超时）
- 参数解析默认值与 `--no-*` 开关

### 文档

- `README.md` 新增「快速启动」小节（中英双语，先中后英）。
- `CHANGELOG.md` 记一笔，版本号 0.2.0 → 0.3.0；`TODO.md` 同步。

```

## openspec/changes/app-launcher/tasks.md

- Source: openspec/changes/app-launcher/tasks.md
- Lines: 1-29
- SHA256: 3b2dafa05b09e580479e92cc31f776c6be7e4287f16540a396831114e0512c29

```md
# 任务清单：应用启动器（app-launcher）

## 需求（open 阶段已确认）

- 一键入口（双击可用）同时拉起：Web 服务（FastAPI，内含前端静态页）+ 目录监控 watch + 自动打开浏览器
- 启动器与前后端解耦：不 import `src/` 任何模块，只通过子进程调用现有 CLI 命令
- 形态：Python 脚本 `scripts/launcher.py` + 双击入口 `scripts/start.bat`（不打包 exe）

## 设计阶段

- [x] 编写设计文档 `openspec/changes/app-launcher/design.md`
- [x] 用户确认方案（计划审批通过：Python 脚本 + start.bat，拉起 web+watch+浏览器）

## 实现阶段

- [ ] Task 1: `scripts/launcher.py` — Python 定位（优先 `.venv/Scripts/python.exe`，回退 `uv run python`）、端口预检、拉起 web/watch 子进程（cwd=项目根）
- [ ] Task 2: `scripts/launcher.py` — 就绪轮询 `http://<host>:<port>/`（超时 ~60s）、就绪后 `webbrowser.open`、Ctrl+C 优雅回收两个子进程（CREATE_NEW_PROCESS_GROUP + CTRL_BREAK）、任一子进程意外退出时清理并以非零码退出
- [ ] Task 3: `scripts/launcher.py` — 参数 `--host`/`--port`/`--no-web`/`--no-watch`/`--no-browser`
- [ ] Task 4: `scripts/start.bat` — 双击入口，`cd /d "%~dp0\.."` 后 `uv run python scripts\launcher.py %*`，失败 pause
- [ ] Task 5: `tests/test_launcher.py` — Python 定位、端口检测、就绪轮询、参数解析的单元测试（mock，不真起服务）
- [ ] Task 6: 文档 — `README.md` 新增「快速启动」小节（中英双语）；`CHANGELOG.md` 记一笔（0.2.0 → 0.3.0）；`TODO.md` 更新

## 验证阶段

- [ ] `uv run pytest tests/test_launcher.py` 通过，且 `uv run pytest tests/` 全量不回归
- [ ] `uv run python scripts/launcher.py --no-browser` 实际启动：8000 端口就绪、watch 存活、`http://127.0.0.1:8000/` 可访问
- [ ] Ctrl+C 后两个子进程被回收、端口释放
- [ ] 双击 `scripts/start.bat` 冒烟验证
- [ ] 提交前 `uv run ruff format` + `uv run ruff check --fix` 改动文件

```

## openspec/changes/app-launcher/specs/app-launcher/spec.md

- Source: openspec/changes/app-launcher/specs/app-launcher/spec.md
- Lines: 1-34
- SHA256: 4355cd020be7c2f7e7e9dba219207acbafe21c1954a6610ffd10f7622030d27c

```md
# OpenSpec Delta: 应用启动器（app-launcher）

## 变更范围

新增一个与前后端解耦的一键启动入口：双击 `scripts/start.bat`（或 `uv run python scripts/launcher.py`）即可同时拉起 Web 服务（FastAPI 托管 API 与前端静态页）、目录监控 watch，并在服务就绪后自动打开浏览器。

解耦约束：启动器不 import `src/` 任何模块，仅通过子进程调用现有 CLI（`python -m src.cli web` / `python -m src.cli watch`），前后端内部实现改动不影响启动器。

## 新增/修改的规格

### S1: 启动器（`scripts/launcher.py`，新增）

- 纯标准库实现（`subprocess`/`socket`/`urllib`/`webbrowser`/`argparse`/`signal`）。
- Python 解释器定位：优先 `<项目根>/.venv/Scripts/python.exe`，不存在则回退 `uv run python`。
- 子进程均以项目根目录为 cwd（`config.yaml` 与 `data/` 为相对路径）。
- 启动前端口预检：TCP 探测 `<host>:<port>` 被占则友好报错退出，提示换 `--port`。
- 就绪等待：轮询 `http://<host>:<port>/` 至 HTTP 响应或超时（默认 ~60s，首次加载重依赖较慢），就绪后 `webbrowser.open` 打开首页。
- 优雅退出：捕获 Ctrl+C / 控制台关闭；Windows 下子进程以 `CREATE_NEW_PROCESS_GROUP` 创建，先 `CTRL_BREAK_EVENT`/terminate 再 kill；任一子进程意外退出时打印退出码、清理另一进程并以非零码退出。
- 参数：`--host`（默认 127.0.0.1）、`--port`（默认 8000）、`--no-web`、`--no-watch`、`--no-browser`。

### S2: 双击入口（`scripts/start.bat`，新增）

- `cd /d "%~dp0\.."` 切到项目根，`uv run python scripts\launcher.py %*` 透传参数。
- 启动失败时 `pause`，让双击用户看到报错。

### S3: 测试（`tests/test_launcher.py`，新增）

- 覆盖 Python 定位（mock `.venv` 存在/不存在）、端口占用检测（socket 绑定模拟）、就绪轮询（mock urllib 成功/超时）、参数解析默认值与 `--no-*` 开关。
- 不依赖真实音频、不真正启动服务。

### S4: 文档

- `README.md` 新增「快速启动」小节（中英双语，先中后英）。
- `CHANGELOG.md` 记录新功能，版本号 0.2.0 → 0.3.0；`TODO.md` 同步。

```
