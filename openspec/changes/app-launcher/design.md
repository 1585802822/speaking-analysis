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
