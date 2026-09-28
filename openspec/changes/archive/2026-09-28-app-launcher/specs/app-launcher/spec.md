# OpenSpec Delta: 应用启动器（app-launcher）

## ADDED Requirements

### Requirement: 一键启动器（scripts/launcher.py）

启动器 SHALL 以纯标准库实现，不 import `src/` 任何模块，仅通过子进程调用现有 CLI 命令，与前后端解耦。

#### Scenario: 默认一键启动

- **WHEN** 用户运行 `uv run python scripts/launcher.py`
- **THEN** 启动器以项目根为 cwd 拉起 `python -m src.cli web --host 127.0.0.1 --port 8000` 与 `python -m src.cli watch` 两个子进程，轮询 `http://127.0.0.1:8000/` 就绪后自动打开浏览器

#### Scenario: Python 解释器定位

- **WHEN** `<项目根>/.venv/Scripts/python.exe` 存在
- **THEN** 启动器直接使用该解释器；否则回退 `uv run python`

#### Scenario: 端口占用预检

- **WHEN** 目标端口已被占用
- **THEN** 启动器友好报错并以退出码 2 退出，提示使用 `--port` 换端口

#### Scenario: 优雅退出

- **WHEN** 用户按 Ctrl+C 或任一子进程意外退出
- **THEN** 启动器先 CTRL_BREAK/terminate 再 kill 回收全部子进程，释放端口

#### Scenario: 可选开关

- **WHEN** 传入 `--no-web` / `--no-watch` / `--no-browser` / `--host` / `--port`
- **THEN** 对应组件被跳过或使用指定地址端口；`--no-web` 与 `--no-watch` 同时使用时报错退出

### Requirement: 双击入口（scripts/start.bat）

项目 SHALL 提供 `scripts/start.bat` 双击入口，切换到项目根目录后调用 `uv run python scripts/launcher.py` 并透传参数，失败时 pause 显示报错。

#### Scenario: 双击启动

- **WHEN** 用户双击 `scripts/start.bat`
- **THEN** Web 服务与 watch 监控被拉起，浏览器自动打开首页

### Requirement: 启动器单元测试

项目 SHALL 在 `tests/test_launcher.py` 覆盖启动器关键函数：Python 定位、端口占用检测、就绪轮询、参数解析；测试全部 mock，不真正启动服务、不依赖真实音频。

#### Scenario: 测试可独立运行

- **WHEN** 运行 `uv run pytest tests/test_launcher.py`
- **THEN** 全部测试通过且无需网络、音频或真实服务
