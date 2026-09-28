# 提案：修复 start.bat 双击报错（start-bat-encoding）

## Why

用户双击 `scripts/start.bat` 时报错 `can't open file '...\scripts\scripts\launcher.py'`：bat 第 4 行 `cd /d "%~dp0\.."` 未生效，工作目录仍停在 `scripts\`，相对路径 `scripts\launcher.py` 被叠加成 `scripts\scripts\launcher.py`。根因是 bat 内 UTF-8 中文注释被 cmd 按 GBK 解析导致字节错位，`cd /d` 行被吞；叠加 LF 换行放大解析不稳定。

## What Changes

- 重写 `scripts/start.bat`：注释全英文 ASCII，`cd /d "%~dp0.."`，传参改绝对路径 `"%~dp0launcher.py"`，换行 CRLF。
- `tests/test_launcher.py` 新增 `TestStartBat`，断言 start.bat 纯 ASCII 防回归。
- 新增根目录 `.gitattributes`（`*.bat text eol=crlf`）。
- 版本 0.3.0 → 0.3.1，CHANGELOG / TODO 同步。
