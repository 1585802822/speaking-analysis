# 任务清单：修复 start.bat 双击报错（start-bat-encoding）

## 需求

- 修复双击 `scripts/start.bat` 报 `scripts\scripts\launcher.py` 的问题（UTF-8 中文注释 + LF 换行导致 cd 失效）

## 实现阶段

- [x] Task 1: 重写 `scripts/start.bat`（ASCII 注释 + `%~dp0..` cd + 绝对路径 `%~dp0launcher.py` + CRLF） <!-- comet-task:abba4d15-0c78-49ad-a5e2-72ebcf876219 -->
- [x] Task 2: `tests/test_launcher.py` 新增 `TestStartBat`（断言纯 ASCII） <!-- comet-task:36d346b3-8f1f-4500-b232-16803b34249b -->
- [x] Task 3: 新增 `.gitattributes`（`*.bat text eol=crlf`） <!-- comet-task:04d52558-f483-439b-a48e-68fcd8c9e3bb -->
- [x] Task 4: 版本 0.3.0 → 0.3.1，CHANGELOG / TODO 更新 <!-- comet-task:2c66c6fa-dfe2-436f-ab2d-41393a27042d -->

## 验证阶段

- [x] `uv run pytest tests/test_launcher.py` 与全量 `pytest tests/` 通过 <!-- comet-task:d65e17c8-6706-4b49-b216-a043d06975b6 -->
- [x] 在 `scripts\` 目录为 cwd 时运行 `cmd /c start.bat --no-browser` 复现双击场景，确认无 `scripts\scripts` 报错、服务正常、停止后端口释放 <!-- comet-task:c0b48008-8e9c-40bb-b7e1-ed41e6e058cb -->
- [x] `od -c scripts/start.bat` 确认无中文、CRLF <!-- comet-task:a6594378-c6d8-4923-8172-8a17188e96d2 -->
