# 任务清单：任务失败处理与状态误判修复（task-failure-handling）

## 需求（open 阶段已确认）

- 修复 `test.WAV`（`4bbc286330a4`）的状态误判：三套原型页 `saveText` 加「未变不提交」守卫；`_FINAL_STATUSES` 补入 `transcribed`、`corrected`；修复该录音的存量错误数据
- 修复 SSE：前端改收命名事件 `update`；业务错误事件改名 `job_error` 与网络断线区分；不再误报「SSE 连接错误」
- 成功后清除 `recordings.failed_reason` 残留（含存量脏数据）
- 失败时 UI 展示失败阶段与原因，并给出「继续分析」引导
- 阶段级自动重试：segment 1 次、diarize / asr 2 次，指数退避，轨迹写 `run_history`
- 单句 ISE 评测失败落库（`evaluations` 加列），不计入已评测集合，可重跑，前端可见

## 设计阶段

- [ ] 编写设计文档并登记 `design_doc`
- [ ] 用户确认方案

## 实现阶段

### ⓪ 状态误判修复

- [ ] Task 1: 三套原型页 `saveText`（`vue-app.js`、`element-app.js`、`alpine-app.js`）加「与加载时原值比较，未变不提交」守卫，对齐 `native-app.js` 行为
- [ ] Task 2: `src/web/service.py` `_FINAL_STATUSES` 补入 `"transcribed"`、`"corrected"`
- [ ] Task 3: 存量数据修复脚本/一次性 SQL：还原 `4bbc286330a4` 的 3 条误判 `asr_results`（`is_manual=0`、`asr_source` 还原）、`recordings.status` 改回 `transcribed`、清 `failed_reason`

### ① SSE 修复

- [ ] Task 4: `src/web/api.py` `_sse_stream` 业务错误事件 `event: error` → `event: job_error`
- [ ] Task 5: `src/web/static/common.js` `listenJobSSE` 重写：`addEventListener("update")` 收进度、终态 `close()`、`job_error` 分支、`onerror` 仅在零消息且连接关闭时报错

### ② 清残留

- [ ] Task 6: `src/db.py` `update_recording_status` SQL 增加 `failed_reason = NULL`
- [ ] Task 7: `_migrate_schema` 追加幂等数据修复：`status != 'failed'` 的行清空 `failed_reason`

### ③ UI 失败展示与引导

- [ ] Task 8: `src/web/service.py` 增加 `_STAGE_LABEL`，失败原因带阶段名，job message 同步
- [ ] Task 9: `common.js` `renderHistoryList` 失败行高亮 + 「继续分析」引导；编辑页失败提示与续跑引导

### ④ 阶段级自动重试

- [ ] Task 10: `src/web/service.py` 新增 `_run_stage_with_retry`（指数退避、`_RETRY_BASE_DELAY` 常量、run_history 轨迹）
- [ ] Task 11: `run_analysis` 三阶段主体抽为闭包并接入重试（segment=1，diarize/asr=2）；`run_evaluation` 顶层不重试

### ⑤ 单句评测失败记录

- [ ] Task 12: `src/schema.sql` `evaluations` 加 `status`、`error_message` 列；`_migrate_schema` 幂等加列
- [ ] Task 13: `save_evaluation` 扩展 `status`/`error_message` 参数；`get_evaluated_segment_indexes` 只统计成功行
- [ ] Task 14: `run_evaluation` 单句失败落库并统计，收尾 message 提示「N 句未评上」
- [ ] Task 15: 各原型页 `renderEvaluations` 渲染失败占位

### 测试与文档

- [ ] Task 16: `tests/` 新增：SSE 事件流、`failed_reason` 清除与迁移、阶段重试轨迹与耗尽、单句评测失败重跑、`_FINAL_STATUSES` 恢复行为
- [ ] Task 17: 更新 `TODO.md`、`CHANGELOG.md`、版本号

## 验证阶段

- [ ] `uv run pytest tests/` 全量通过、不回归
- [ ] `uv run ruff format` + `uv run ruff check --fix` 改动文件
- [ ] 端到端：启动服务，SSE 进度逐帧推进；重启服务不再误标已完成录音
- [ ] 端到端：制造阶段失败 → 重试提示 → failed 带阶段名 → 续跑成功且 `failed_reason` 清空
- [ ] 端到端：制造部分 ISE 失败 → 提示「N 句未评上」→ 重评仅跑失败句
- [ ] 确认 `4bbc286330a4` 状态为 `transcribed` 且 3 条误判记录已还原
