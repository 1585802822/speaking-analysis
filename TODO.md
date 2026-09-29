# TODO

三栏清单：开工前先读，完工后更新。

## 待办

- [ ] force 重跑 test.WAV 全流程（新切分参数 + 双模型 ASR 生效；60 分钟音频 + 本地 large-v3 转写耗时较长，建议夜间执行）
- [ ] 重跑后 SQL 验收：段数约 700 上下（远低于旧 2321）、user 句有真实文本（无占位、无大面积「转写结果为空」）、other 句 asr_source='local' 且有真实文本

## 进行中

- [ ] `task-failure-handling` 变更（Comet classic，分支 `comet/task-failure-handling`）：状态误判修复 + SSE 修复 + 失败处理

## 已完成

- [x] 任务失败处理与状态误判修复（`task-failure-handling`）：
  - 状态误判：`_FINAL_STATUSES` 补入 `transcribed` / `corrected`，重启不再把已完成分析的录音误标为 failed
  - 试听误判：Vue / Element / Alpine 三套页面文本框加「内容未变不提交」守卫（对齐原生页）
  - 存量数据：`4bbc286330a4` 的 3 条误判人工修正行已还原，状态 `failed` → `transcribed`，`failed_reason` 清空
  - SSE：前端改监听命名事件 `update`，业务错误改用 `job_error`，不再误报「SSE 连接错误」
  - 失败原因残留：状态推进时清空 `failed_reason`，启动迁移修复存量脏数据
  - 阶段级自动重试（段 1 次 / 分离与转写 2 次，指数退避，轨迹入 run_history）
  - 单句 ISE 评测失败落库（`evaluations` 加 `status` / `error_message`），可重跑、前端可见
  - 新增 `tests/test_task_failure_handling.py`（13 个用例），全量 188 个测试通过
- [x] 消除 `/favicon.ico` 404 日志噪音：`src/web/main.py` 新增路由返回 204，新增 `test_favicon`
- [x] 修复 `scripts/start.bat` 双击报错（`scripts\scripts\launcher.py`）：中文注释改 ASCII + CRLF + 绝对路径 `%~dp0launcher.py`，新增 `TestStartBat` 防回归测试与 `.gitattributes`
- [x] 一键启动器：`scripts/launcher.py`（解耦、纯标准库、子进程拉起 web+watch+浏览器）+ `scripts/start.bat` 双击入口；12 个单元测试 + 实际启动/Ctrl+C 回收/start.bat 冒烟全部通过
- [x] 前端依赖本地化：Vue / Element Plus / Alpine 下载到 `src/web/static/vendor/`，移除 unpkg / jsdelivr CDN 引用
- [x] UI 修复：「继续分析」按钮收敛 + 说明提示；状态文案「待校对」；文件名去扩展名；时长/处理时间精简（formatTime / formatDateTime）
- [x] 说话人二分类 user / other（needs_review 不再产生，读取层归一化旧数据）
- [x] 句子切分修复：停顿阈值 0.7s、句边界取停顿终点、长句能量谷切分、相邻短句合并（test.WAV 实测 707 段、中位 4.12s、<1s 仅 4 段）
- [x] ASR 双模型：user 句走 API（失败/空回退本地），other 句本地 faster-whisper 懒加载
- [x] 快捷键修复：容器直派发事件、x 键翻转 user/other、Alpine init() 双重注册修复
- [x] 全部 160 个测试通过；4 套原型 headless 渲染验证通过
