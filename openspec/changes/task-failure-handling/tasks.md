# 任务清单：任务失败处理与状态误判修复（task-failure-handling）

## 需求（open 阶段已确认）

- 修复 `test.WAV`（`4bbc286330a4`）的状态误判：三套原型页 `saveText` 加「未变不提交」守卫；`_FINAL_STATUSES` 补入 `transcribed`、`corrected`；修复该录音的存量错误数据
- 修复 SSE：前端改收命名事件 `update`；业务错误事件改名 `job_error` 与网络断线区分；不再误报「SSE 连接错误」
- 成功后清除 `recordings.failed_reason` 残留（含存量脏数据）
- 失败时 UI 展示失败阶段与原因，并给出「继续分析」引导
- 阶段级自动重试：segment 1 次、diarize / asr 2 次，指数退避，轨迹写 `run_history`
- 单句 ISE 评测失败落库（`evaluations` 加列），不计入已评测集合，可重跑，前端可见

## 设计阶段

- [x] 编写设计文档并登记 `design_doc` <!-- comet-task:81a1bedc-02b8-4c8f-8f7d-9b14b3ec503b -->
- [x] 用户确认方案 <!-- comet-task:fce0f66a-3edb-4c50-9f9b-472dac950479 -->

## 实现阶段

### ⓪ 状态误判修复

- [ ] Task 1: 三套原型页 `saveText`（`vue-app.js`、`element-app.js`、`alpine-app.js`）加「与加载时原值比较，未变不提交」守卫，对齐 `native-app.js` 行为 <!-- comet-task:2dc2218f-dd06-461f-8e21-72c46f242493 -->
- [ ] Task 2: `src/web/service.py` `_FINAL_STATUSES` 补入 `"transcribed"`、`"corrected"` <!-- comet-task:91a940fa-1f37-419a-a85a-20a50da25398 -->
- [ ] Task 3: 存量数据修复脚本/一次性 SQL：还原 `4bbc286330a4` 的 3 条误判 `asr_results`（`is_manual=0`、`asr_source` 还原）、`recordings.status` 改回 `transcribed`、清 `failed_reason` <!-- comet-task:fb637c0b-c87e-447e-aa42-b09044dba4af -->

### ① SSE 修复

- [ ] Task 4: `src/web/api.py` `_sse_stream` 业务错误事件 `event: error` → `event: job_error` <!-- comet-task:b5f8d795-a611-4393-9f77-77c3ba9eb327 -->
- [ ] Task 5: `src/web/static/common.js` `listenJobSSE` 重写：`addEventListener("update")` 收进度、终态 `close()`、`job_error` 分支、`onerror` 仅在零消息且连接关闭时报错 <!-- comet-task:58f942d5-4c7c-476d-86ce-80c59f0750cc -->

### ② 清残留

- [ ] Task 6: `src/db.py` `update_recording_status` SQL 增加 `failed_reason = NULL` <!-- comet-task:09d6b867-d9dd-4fb1-af7d-644a1ab0c89d -->
- [ ] Task 7: `_migrate_schema` 追加幂等数据修复：`status != 'failed'` 的行清空 `failed_reason` <!-- comet-task:9538f2db-1c5f-40d5-845c-51880501c140 -->

### ③ UI 失败展示与引导

- [ ] Task 8: `src/web/service.py` 增加 `_STAGE_LABEL`，失败原因带阶段名，job message 同步 <!-- comet-task:2ef7a231-754d-4c7d-84d6-23cf49f0c1c0 -->
- [ ] Task 9: `common.js` `renderHistoryList` 失败行高亮 + 「继续分析」引导；编辑页失败提示与续跑引导 <!-- comet-task:632ac22f-0922-468c-ac96-0c28257858ae -->

### ④ 阶段级自动重试

- [ ] Task 10: `src/web/service.py` 新增 `_run_stage_with_retry`（指数退避、`_RETRY_BASE_DELAY` 常量、run_history 轨迹） <!-- comet-task:13659a3f-e2e2-4198-932c-2903a9c1e157 -->
- [ ] Task 11: `run_analysis` 三阶段主体抽为闭包并接入重试（segment=1，diarize/asr=2）；`run_evaluation` 顶层不重试 <!-- comet-task:0e8a6168-04e2-4596-8717-749816305b25 -->

### ⑤ 单句评测失败记录

- [ ] Task 12: `src/schema.sql` `evaluations` 加 `status`、`error_message` 列；`_migrate_schema` 幂等加列 <!-- comet-task:f10563a7-8e06-414d-a360-961926f8d441 -->
- [ ] Task 13: `save_evaluation` 扩展 `status`/`error_message` 参数；`get_evaluated_segment_indexes` 只统计成功行 <!-- comet-task:c54812d6-997b-48df-bb90-f31853fa0d31 -->
- [ ] Task 14: `run_evaluation` 单句失败落库并统计，收尾 message 提示「N 句未评上」 <!-- comet-task:a2c12bda-2b9f-4c2a-b733-990477486ff9 -->
- [ ] Task 15: 各原型页 `renderEvaluations` 渲染失败占位 <!-- comet-task:7076218a-175b-46eb-98c0-887dba3b7e14 -->

### 测试与文档

- [ ] Task 16: `tests/` 新增：SSE 事件流、`failed_reason` 清除与迁移、阶段重试轨迹与耗尽、单句评测失败重跑、`_FINAL_STATUSES` 恢复行为 <!-- comet-task:4fda8a04-e9f3-477f-8e69-97428d4ddd55 -->
- [ ] Task 17: 更新 `TODO.md`、`CHANGELOG.md`、版本号 <!-- comet-task:5846d798-28e4-4d49-880e-78d437e8a92a -->

## 验证阶段

- [ ] `uv run pytest tests/` 全量通过、不回归 <!-- comet-task:5b545589-4c76-42d3-954d-b5990d1487ea -->
- [ ] `uv run ruff format` + `uv run ruff check --fix` 改动文件 <!-- comet-task:46e39101-4aea-4c0a-b8b8-a44d3247aaa3 -->
- [ ] 端到端：启动服务，SSE 进度逐帧推进；重启服务不再误标已完成录音 <!-- comet-task:6a9a8ed0-ce3a-47d4-bec4-e10c17ee15fb -->
- [ ] 端到端：制造阶段失败 → 重试提示 → failed 带阶段名 → 续跑成功且 `failed_reason` 清空 <!-- comet-task:8642cea5-c833-445f-9fb7-2f98c0960e60 -->
- [ ] 端到端：制造部分 ISE 失败 → 提示「N 句未评上」→ 重评仅跑失败句 <!-- comet-task:2c57abc1-eaba-490d-86c0-96c0964b8bf3 -->
- [ ] 确认 `4bbc286330a4` 状态为 `transcribed` 且 3 条误判记录已还原 <!-- comet-task:2b5097f0-7be3-4188-ab8d-2d9671874cda -->
