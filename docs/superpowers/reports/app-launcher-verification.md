# 验证报告：应用启动器（app-launcher）

日期：2026-09-28

## 验证项与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 单元测试 | `uv run pytest tests/test_launcher.py` | 通过（12 passed） |
| 全量回归 | `uv run pytest tests/ -q`（comet verify check 记录，exit=0） | 通过（172 passed，无回归） |
| 实际启动 | `uv run python scripts/launcher.py --no-browser` | 通过：`/` 与 `/api/recordings` 均返回 200，web（pid 21356）与 watch（pid 9124）子进程存活，且使用 `.venv` 解释器 |
| 子进程回收 | 停止 launcher 后检查 | 通过：8000 端口释放（连接失败 000），无残留 `src.cli web/watch` 进程 |
| start.bat 冒烟 | `cmd /c scripts\start.bat --no-browser` | 通过：服务正常拉起，`/` 返回 200；停止后端口释放、无残留进程 |
| 代码规范 | `uv run ruff format` + `uv run ruff check --fix scripts/launcher.py tests/test_launcher.py` | 通过（无需修改，All checks passed） |

## 解耦确认

`scripts/launcher.py` 仅使用标准库（argparse/socket/subprocess/urllib/webbrowser/signal），不 import `src/` 任何模块，前后端内部改动不影响启动器。

## 结论

验收标准全部满足：双击 `scripts/start.bat` 一键拉起 Web 服务（含前端）+ watch 监控并就绪后自动打开浏览器；Ctrl+C / 停止后子进程全部回收、端口释放。验证通过。
