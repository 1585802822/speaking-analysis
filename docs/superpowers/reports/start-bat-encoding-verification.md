# 验证报告：修复 start.bat 双击报错（start-bat-encoding）

日期：2026-09-28

## 问题与根因

双击 `scripts/start.bat` 报 `can't open file '...\scripts\scripts\launcher.py'`：bat 内 `cd /d "%~dp0\.."` 未生效，cwd 仍为 `scripts\`，相对路径 `scripts\launcher.py` 被叠加成 `scripts\scripts\launcher.py`。

根因：bat 含 **UTF-8 中文注释**，`cmd.exe` 按 GBK 解析导致字节错位、`cd` 行被上一行注释吞掉；LF 换行放大了解析不稳定。

## 验证项与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 单元测试 | `uv run pytest tests/test_launcher.py` | 通过（14 passed，含新增 TestStartBat 2 项） |
| 全量回归 | `uv run pytest tests/ -q` | 通过（174 passed，exit=0，已录为 verify 检查） |
| 字节检查 | `od -c scripts/start.bat` | 通过：全 ASCII、换行均为 `\r\n` |
| 双击等价场景 | `Start-Process scripts\start.bat`（WorkingDirectory=scripts） | 通过：`/` 与 `/api/recordings` 均 200，web/watch 子进程存活 |
| 双击 cwd 场景 | 从 `scripts\` 为 cwd 运行 `.\start.bat --no-browser` | 通过：服务 200，不再出现 `scripts\scripts` 报错 |
| 优雅回收 | 停止后检查 | 通过：端口释放（连接失败 000）、0 残留进程 |

## 补充说明

- 诊断中发现：在 cmd 中裸调用 `start.bat`（不带路径）会被 cmd 当作内置 `start` 命令解析而报「不是内部或外部命令」。这不影响真实双击——explorer 传完整路径调用，已用 `Start-Process` 验证通过。
- 新增 `TestStartBat` 断言 start.bat 纯 ASCII + CRLF，防止未来再引入中文注释导致同类错位。

## 结论

验收标准全部满足。修复有效，验证通过。
