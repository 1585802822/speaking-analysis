---
comet_change: task-failure-handling
status: draft
---
# 任务失败处理与状态误判修复（task-failure-handling）实施计划

## 目标

修复录音分析流水线在失败路径上的缺陷：状态误判（试听被当人工修正、重启误标已完成录音）、SSE 进度推送失效、失败原因残留、缺少自动重试与失败可视化，以及 ISE 单句评测失败被静默跳过。同时修复 `data/input/test.WAV`（`4bbc286330a4`）的存量错误数据。

设计依据：`openspec/changes/task-failure-handling/design.md`；验收口径：`openspec/changes/task-failure-handling/specs/task-failure-handling/spec.md`。

## 权威任务清单

任务完成状态以 `openspec/changes/task-failure-handling/tasks.md` 为准，本计划按 comet-task ID 引用。

### ⓪ 状态误判修复

- `2dc2218f-dd06-461f-8e21-72c46f242493` Task 1：三套原型页 `saveText` 加「未变不提交」守卫（`vue-app.js` / `element-app.js` / `alpine-app.js`）
- `91a940fa-1f37-419a-a85a-20a50da25398` Task 2：`_FINAL_STATUSES` 补入 `transcribed`、`corrected`
- `fb637c0b-c87e-447e-aa42-b09044dba4af` Task 3：存量数据修复（`4bbc286330a4`）

### ① SSE 修复

- `b5f8d795-a611-4393-9f77-77c3ba9eb327` Task 4：`_sse_stream` 业务错误事件改名 `job_error`
- `58f942d5-4c7c-476d-86ce-80c59f0750cc` Task 5：`listenJobSSE` 重写

### ② 清残留

- `09d6b867-d9dd-4fb1-af7d-644a1ab0c89d` Task 6：`update_recording_status` 清 `failed_reason`
- `9538f2db-1c5f-40d5-845c-51880501c140` Task 7：`_migrate_schema` 幂等修复存量脏数据

### ③ UI 失败展示与引导

- `2ef7a231-754d-4c7d-84d6-23cf49f0c1c0` Task 8：`_STAGE_LABEL` 与失败原因带阶段
- `632ac22f-0922-468c-ac96-0c28257858ae` Task 9：历史列表与编辑页失败展示、续跑引导

### ④ 阶段级自动重试

- `13659a3f-e2e2-4198-932c-2903a9c1e157` Task 10：`_run_stage_with_retry`
- `0e8a6168-04e2-4596-8717-749816305b25` Task 11：`run_analysis` 抽阶段闭包并接入重试

### ⑤ 单句评测失败记录

- `f10563a7-8e06-414d-a360-961926f8d441` Task 12：`evaluations` 加 `status` / `error_message` 列 + 迁移
- `c54812d6-997b-48df-bb90-f31853fa0d31` Task 13：`save_evaluation` 扩展参数、`get_evaluated_segment_indexes` 只统计成功行
- `a2c12bda-2b9f-4c2a-b733-990477486ff9` Task 14：`run_evaluation` 单句失败落库与提示
- `7076218a-175b-46eb-98c0-887dba3b7e14` Task 15：各原型页渲染失败占位

### 测试与文档

- `4fda8a04-e9f3-477f-8e69-97428d4ddd55` Task 16：新增测试
- `5846d798-28e4-4d49-880e-78d437e8a92a` Task 17：`TODO.md` / `CHANGELOG.md` / 版本号

### 验证

- `5b545589-4c76-42d3-954d-b5990d1487ea` `uv run pytest tests/` 全量通过
- `46e39101-4aea-4c0a-b8b8-a44d3247aaa3` `uv run ruff format` + `ruff check --fix`
- `6a9a8ed0-ce3a-47d4-bec4-e10c17ee15fb` 端到端：SSE 逐帧推进、重启不误标
- `8642cea5-c833-445f-9fb7-2f98c0960e60` 端到端：阶段失败 → 重试 → 失败带阶段名 → 续跑清残留
- `2c57abc1-eaba-490d-86c0-96c0964b8bf3` 端到端：单句评测失败 → 提示 → 重评仅跑失败句
- `2b5097f0-7be3-4188-ab8d-2d9671874cda` 确认 `4bbc286330a4` 数据修复结果

## 实施顺序与提交粒度

每步一个独立分支（`fix/` 或 `feat/`），小步提交；提交前对改动文件执行 `uv run ruff format` 与 `uv run ruff check --fix`。

| 顺序 | 分支 | 覆盖任务 | 说明 |
| --- | --- | --- | --- |
| 1 | `feat/task-failure-handling` | Task 1–17 全部 | Comet 变更分支，按 ⓪→①→②③→⑤→④ 分次提交 |

> Comet 变更使用独立分支 `comet/task-failure-handling`（隔离方式 branch）；实际提交按上述逻辑分组进行，不额外切分多个分支。

## 验收标准

1. `uv run pytest tests/` 全量通过，无回归。
2. 服务重启后，状态为 `transcribed` / `corrected` 的录音不被标记为 `failed`。
3. 前端订阅任务事件流时进度逐帧刷新；任务丢失时提示「任务不存在或已丢失」，不误报「SSE 连接错误」。
4. 阶段失败经重试后仍失败时，`failed_reason` 形如「<阶段名>阶段失败：<原因>」，续跑成功后该字段被清空。
5. 单句评测失败写入 `status='failed'` 记录，不计入已评测集合；再次评测仅重跑失败句，前端可见失败占位。
6. `4bbc286330a4` 状态为 `transcribed`，`failed_reason` 为空，3 条误判记录已还原为 `is_manual=0`。
