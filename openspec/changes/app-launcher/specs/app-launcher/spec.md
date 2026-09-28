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
