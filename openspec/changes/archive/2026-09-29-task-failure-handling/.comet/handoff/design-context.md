# Comet Design Handoff

- Change: task-failure-handling
- Phase: design
- Mode: compact
- Context hash: 717e13a8a7f9713027c3928f89353e8e2d84be74566c25946e422a251ca32351

Generated-by: comet-handoff.sh
Task hash policy: task-content-v1. Read tasks.md for live completion; excerpts are design-time context.

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/task-failure-handling/proposal.md

- Source: openspec/changes/task-failure-handling/proposal.md
- Lines: 1-35
- SHA256: f829f0a97f4b43920694887ea5bf6f8968441750223c420961b0cc708c74f8bd

```md
# 提案：任务失败处理与状态误判修复（task-failure-handling）

## Why

当前录音分析工具在「任务失败」这条路径上有多个缺陷，且已产生真实的脏数据：

1. **状态误判（已影响真实数据）**：`data/input/test.WAV`（录音 `4bbc286330a4`）当前状态为 `failed`，但它实际上早已完成切分 → 声纹分离 → 转写，**从未做过人工修正**。两个缺陷叠加导致：
   - **误判 corrected**：vue / element / alpine 三套原型页的 `saveText` 在文本框失焦时**无条件**调用 `PUT /text`（缺 native 页的「内容变了才提交」判断）。用户试听时点过片段 1、2、4 的文本框，3 条**内容未变**的原文被标记为 `is_manual=1, asr_source='manual'`，`run_analysis` 收尾因此把状态置为 `corrected`。
   - **误判 failed（当前状态）**：`_FINAL_STATUSES` 漏了 `transcribed` / `corrected`，导致**每次服务重启**都把「已完成分析但未评测」的录音标成 `failed`。该录音已被误标两次。
2. **SSE 进度推送失效**：服务端发送命名事件 `event: update`，前端只用 `es.onmessage`（只收默认 `message` 事件），导致**前端永远收不到进度**；断流时又误报「SSE 连接错误」，「任务不存在」与「网络断线」也无法区分。
3. **失败信息残留**：`update_recording_status` 成功后不清 `failed_reason`，已恢复的录音仍挂着旧失败原因，误导用户。
4. **失败处理能力不足**：失败时 UI 不展示失败阶段与原因、无重试引导；没有任何自动重试；ISE 评测中单句失败被静默跳过，既无记录也无从感知。

## What Changes

- **状态误判修复**：三套原型页 `saveText` 增加「与原值比较，未变不提交」守卫；`_FINAL_STATUSES` 补入 `transcribed`、`corrected`；修复 `test.WAV` 的存量错误数据（还原 3 条误判记录、状态改回 `transcribed`、清 `failed_reason`）。
- **SSE 修复**：前端改收命名事件 `update`；服务端业务错误事件改名 `job_error`，与网络层 error 区分；仅在「从未收到任何事件且连接已关闭」时才报连接错误。
- **清残留**：`update_recording_status` 统一清 `failed_reason`；启动迁移顺带修复存量脏数据。
- **UI 失败展示与引导**：失败原因带失败阶段（如「语音转写阶段失败：…」）；历史列表失败行高亮、给出「继续分析」引导；编辑页失败提示与续跑引导。
- **阶段级自动重试**：segment 重试 1 次，diarize / asr 重试 2 次，指数退避，重试轨迹写入 `run_history`，耗尽后仍按失败收尾。
- **单句评测失败记录**：`evaluations` 表加 `status` / `error_message` 列，单句失败落库；失败句不计入已评测集合，再次评测时自动重跑；前端渲染失败占位。

## 影响范围

- 后端：`src/web/service.py`、`src/web/api.py`、`src/db.py`、`src/schema.sql`
- 前端：`src/web/static/common.js`、四套原型页 `static/prototype/{native,vue,alpine,element}/*-app.js`
- 数据：`evaluations` 表迁移（幂等加列）、`recordings` 存量脏数据修复
- 测试：`tests/` 新增失败路径与 SSE 测试
- 文档：`TODO.md`、`CHANGELOG.md`、版本号

## 不做的事

- 不引入任务队列 / 并发上限 / 任务取消机制（超出本次范围）
- 不重构前端四套原型为单一实现
- 不改变录音状态机的既有语义（评测仍为可选动作，失败句不缺省判定整任务失败）

```

## openspec/changes/task-failure-handling/design.md

- Source: openspec/changes/task-failure-handling/design.md
- Lines: 1-154
- SHA256: 7f9c0ca9d0796e71d32f82f61604a45a48391ed1cfcb35a2715791ec8e41ca83

[TRUNCATED]

```md
---
comet_change: task-failure-handling
role: technical-design
canonical_spec: openspec
status: draft
---

# 设计文档：任务失败处理与状态误判修复（task-failure-handling）

## 现状

任务状态有两层：内存 `JobStore`（`src/web/jobs.py`，服务重启即丢失）与持久化的 `recordings.status`（`src/schema.sql`）。流水线 `run_analysis`（`src/web/service.py:95-230`）为 segment → diarize → asr 三阶段，失败由顶层 `try/except` 收尾；`run_evaluation`（`service.py:233-328`）为 ISE 单句评测循环。SSE 由 `api.py:126-139` 推送、`static/common.js:99-124` 消费。

已确认的三个缺陷（详见 `proposal.md`）：

1. 前端三套原型页 `saveText` 无「未变不提交」守卫 → 试听点击文本框即写入 `is_manual=1` → 状态误判 `corrected`。
2. `_FINAL_STATUSES`（`service.py:52`）漏 `transcribed`/`corrected` → 每次重启把已完成录音误标 `failed`。
3. SSE 服务端发命名事件 `update`，前端只用 `onmessage` → 永远收不到进度，断流时误报「SSE 连接错误」。

## 方案

### 1. 状态误判修复

**前端守卫**（`static/prototype/{vue,element,alpine}/*-app.js`）
渲染片段时保存原始文本副本，`saveText` 提交前比较；相同则不发请求。对齐 `native-app.js:131-141` 的既有行为。

**终态集合**（`src/web/service.py:52`）

```python
_FINAL_STATUSES = (None, "new", "transcribed", "corrected", "evaluated", "failed")
```

`transcribed` / `corrected` 是分析流水线的正常终点（评测是可选动作），不应被视为「处理中断」。`new` 仍保留在集合内：入库但未开始处理的录音同样不算中断。

**存量数据修复**（`4bbc286330a4`，一次性，执行前须经用户确认）

```sql
-- 还原 3 条内容未变的误判记录（segment_index 1/2/4）
UPDATE asr_results SET is_manual = 0, asr_source = 'local'
WHERE segment_id IN (SELECT id FROM segments WHERE recording_id = '4bbc286330a4')
  AND is_manual = 1 AND asr_source = 'manual';
UPDATE recordings SET status = 'transcribed', failed_reason = NULL WHERE id = '4bbc286330a4';
```

> 注意：`has_manual_asr` 的判定条件是 `is_manual = 1 OR asr_source = 'manual'`，两个字段必须一起还原，只改其一会继续命中。

### 2. SSE 修复（protocol 层分离业务错误与传输错误）

**服务端**（`src/web/api.py`）

| 场景 | 事件名 | 说明 |
| --- | --- | --- |
| 进度 / 终态快照 | `update` | 保持不变，每 0.5s 一帧，终态帧后 break |
| 任务不存在（业务错误） | `job_error`（原 `error`） | 改名，从协议上与浏览器原生 error 区分 |

**前端**（`static/common.js` `listenJobSSE`）

- `addEventListener("update", …)` 收进度（替代 `onmessage`）；收到 `completed`/`failed` 立即 `es.close()`（阻止浏览器自动重连）。
- `addEventListener("job_error", …)` 处理「任务不存在或已丢失」，`close()` 后回调失败。
- `es.onerror` 仅在**从未收到任何事件且 `readyState === CLOSED`** 时报「SSE 连接错误」；其余交给浏览器自动重连。

> 取舍：不改服务端发默认事件。命名事件语义更清晰，问题只在前端选错了监听方式；而 `error` 事件名与 EventSource 原生错误回调同名，无法可靠区分，必须改名。

### 3. failed_reason 清除

`src/db.py` `update_recording_status` 的 SQL 加 `failed_reason = NULL`。

理由：全部 6 处调用点语义均为「状态成功推进」，`mark_recording_failed` 是唯一写入方，无反例；比「只在终态清」更不易漏（续跑从 `segmented` 起步时只经过 `diarized` 这一处状态推进）。

存量脏数据由 `_migrate_schema` 末尾的幂等 SQL 修复：

```sql
UPDATE recordings SET failed_reason = NULL WHERE status != 'failed' AND failed_reason IS NOT NULL
```

### 4. 失败展示与重试引导

`service.py` 增加 `_STAGE_LABEL = {"segment": "句子切分", "diarize": "声纹分离", "asr": "语音转写", "evaluate": "发音评测"}`；顶层 `except` 写入的失败原因带阶段名，如「语音转写阶段失败：<原因>」，job message 同步。

前端 `renderHistoryList` 失败行高亮 + 「继续分析」按钮 title 注明「将从最近完成的阶段继续」；编辑页在失败提示下补续跑引导。

```

Full source: openspec/changes/task-failure-handling/design.md

## openspec/changes/task-failure-handling/tasks.md

- Source: openspec/changes/task-failure-handling/tasks.md
- Lines: 1-64
- SHA256: 61595bf5c9dc7accd14672c1c3ac7c8c6447eb932ea7106fad7d8fd422b41fd7

```md
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

```

## openspec/changes/task-failure-handling/specs/task-failure-handling/spec.md

- Source: openspec/changes/task-failure-handling/specs/task-failure-handling/spec.md
- Lines: 1-136
- SHA256: 5ffafcc78eeac3f94875284faf205ecb5f04b4bc5b875607a3d1617ceb0001d4

[TRUNCATED]

```md
# OpenSpec Delta: 任务失败处理与状态误判修复（task-failure-handling）

## ADDED Requirements

### Requirement: 录音处理终态判定

系统 SHALL 将 `transcribed` 与 `corrected` 视为分析流水线的正常终点；处于这些状态的录音不得被服务启动时的中断恢复逻辑标记为失败。

#### Scenario: 服务重启不误标已完成录音

- **WHEN** 服务重启时某录音状态为 `transcribed` 或 `corrected`
- **THEN** `recover_interrupted_recordings` 不改动该录音的状态与失败原因

#### Scenario: 真正中断的录音仍被标记

- **WHEN** 服务重启时某录音状态为 `segmented` 或 `diarized`（处理中被打断）
- **THEN** 该录音被标记为 `failed`，原因为「服务重启导致处理中断…」

### Requirement: 人工修正判定只认可信来源

系统 SHALL 仅在用户实际修改过内容时写入人工修正记录；编辑页在文本内容未发生变化时不得提交更新请求。

#### Scenario: 试听点击文本框不产生人工修正

- **WHEN** 用户试听后点击某片段文本框后离开，但未改动文本内容
- **THEN** 不发送文本更新请求；该片段不产生 `is_manual=1` 记录；录音状态不因试听变为 `corrected`

#### Scenario: 真实修改仍被记录

- **WHEN** 用户在编辑页把某片段文本改成不同内容后离开输入框
- **THEN** 文本更新请求被发送，该片段标记为人工修正；录音状态推进为 `corrected`

#### Scenario: 存量误判数据修复

- **WHEN** 对录音 `4bbc286330a4` 执行一次性数据修复
- **THEN** 3 条内容未变却被标记的 `asr_results` 行还原为 `is_manual=0` 且 `asr_source` 恢复为原转写来源，录音状态由 `failed` 改回 `transcribed` 且清空 `failed_reason`

### Requirement: SSE 任务进度推送

系统 SHALL 通过命名事件 `update` 推送任务进度与终态快照，通过命名事件 `job_error` 推送「任务不存在」这类业务错误；前端 SHALL 分别监听这两个事件，且不得把流正常结束误报为连接错误。

#### Scenario: 前端正确接收进度

- **WHEN** 前端订阅某任务的事件流
- **THEN** 每收到一帧 `update` 事件即刷新进度显示；收到 `completed` 或 `failed` 快照后前端主动关闭连接

#### Scenario: 业务错误与网络断线可区分

- **WHEN** 服务端推送 `job_error`（任务不存在或已丢失）
- **THEN** 前端提示「任务不存在或已丢失（服务可能已重启）」并关闭连接

#### Scenario: 不误报连接错误

- **WHEN** 前端已收到过至少一帧事件后连接被关闭
- **THEN** 不显示「SSE 连接错误」

#### Scenario: 连接从未建立才报错

- **WHEN** 前端从未收到任何事件且连接状态为已关闭
- **THEN** 提示「SSE 连接错误」

### Requirement: 失败原因生命周期

系统 SHALL 在录音状态成功推进时清除该录音的历史失败原因；失败原因只能由失败标记写入。

#### Scenario: 续跑成功后清空失败原因

- **WHEN** 一条 `failed` 录音经「继续分析」成功推进到 `transcribed`（或 `corrected`）
- **THEN** 该录音 `failed_reason` 为空

#### Scenario: 启动迁移修复存量脏数据

- **WHEN** 服务启动执行 schema 迁移
- **THEN** 所有状态不为 `failed` 却残留失败原因的录音，其 `failed_reason` 被清空；该迁移可重复执行且无副作用

### Requirement: 失败信息展示与重试引导

系统 SHALL 在录音处理失败时记录失败所在阶段，并在历史列表中展示失败原因与续跑入口。

#### Scenario: 失败原因包含阶段

```

Full source: openspec/changes/task-failure-handling/specs/task-failure-handling/spec.md
