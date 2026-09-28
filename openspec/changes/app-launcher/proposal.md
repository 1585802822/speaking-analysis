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
