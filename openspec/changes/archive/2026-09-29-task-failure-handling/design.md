---
comet_change: task-failure-handling
role: technical-design
canonical_spec: openspec
archived-with: 2026-09-29-task-failure-handling
status: final
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

> 取舍：失败阶段直接编入 `failed_reason` 文本，不给 `list_recordings` 增加 N+1 查询或新 API 字段；结构化信息仍完整保留在 `run_history`。

### 5. 阶段级自动重试

`service.py` 新增：

```python
_RETRY_BASE_DELAY = 2.0  # 秒，模块级常量便于测试 patch

def _run_stage_with_retry(db, recording_id, stage, job_store, job_id, fn, max_retries):
    """执行单个阶段，失败按指数退避重试；每次尝试都写 run_history。"""
```

- 每次尝试写 `run_history(stage, "started")`，成功写 `completed`，失败写 `failed` + `error_message`（含第几次尝试）；耗尽后 `raise` 交顶层 `except`。
- 重试期间 `job_store.update` 提示「<阶段>失败，N 秒后重试（x/y）…」；退避 `2s → 4s`。
- 策略：`segment` 重试 1 次（本地切分失败多为数据问题）；`diarize` / `asr` 重试 2 次（涉及模型加载与外部 API，瞬时故障常见）。
- `run_evaluation` 顶层不重试（多为确定性错误），单句失败走第 6 节机制。

> 取舍：重试粒度为**阶段整体**，不拆到阶段内部（如逐句 ASR），避免与 `protect_manual`、`save_segments` 的幂等语义纠缠。`_last_completed_status` 只认 `completed`，`run_history` 只增不改 → 断点续跑逻辑零改动。重试全程在后台 daemon 线程内，不阻塞 API。

### 6. 单句评测失败记录

**schema**（`src/schema.sql` + `_migrate_schema` 幂等加列）

```sql
ALTER TABLE evaluations ADD COLUMN status TEXT DEFAULT 'success';
ALTER TABLE evaluations ADD COLUMN error_message TEXT;
```

对齐 `asr_results` 的既有模式（`status: success|failed` + `error_message`）。

**DB 层**（`src/db.py`）

- `save_evaluation(..., status="success", error_message=None)`：失败行写 `result_json='{}'` + `status='failed'`；覆盖更新时旧失败行可被成功结果覆盖。
- `get_evaluated_segment_indexes`：WHERE 增加 `AND (e.status IS NULL OR e.status = 'success')` → **失败句自动回到待评测集合**，再点「开始评测」即重跑，闭环成立。旧行 `status IS NULL` 按成功兼容。

**服务层**（`service.py` `run_evaluation` 单句循环）：捕获异常 → `logger.warning` + `save_evaluation(..., status="failed", error_message=str(exc))` + 累计 `failed_indexes`；收尾 message 为「ISE 评测完成，N/M 句未评上，可重新评测重试」。录音状态仍置 `evaluated`（保持现有状态机，避免「全部句子失败是否算任务失败」的语义争议）。

**前端**：各原型页 `renderEvaluations` 对 `ev.status === "failed"` 渲染红色失败占位条。

> 取舍：加列而非新建表或往 `result_json` 塞标记。失败与转写结果无关；塞进 `result_json` 会污染结果结构并需同时改查询与前端解析两处。

## 测试策略

`tests/`，全部 mock，不依赖真实音频：

| 用例 | 验证点 |
| --- | --- |
| SSE 事件流 | TestClient 流式请求断言 `event: update` 帧、终态后关流；直接驱动 `_sse_stream` 断言不存在任务发 `job_error` |
| 状态恢复 | `_FINAL_STATUSES` 含 `transcribed`/`corrected` 后 `recover_interrupted_recordings` 不再误标 |
| failed_reason | `mark_recording_failed` → `update_recording_status` → 断言清空；迁移 SQL 幂等 |
| 阶段重试 | monkeypatch 阶段函数「前 2 次抛错第 3 次成功」+ `_RETRY_BASE_DELAY=0`；断言 run_history 轨迹（2 failed + 1 completed）与最终状态；再测全部失败路径的 failed_reason 文案 |
| 单句评测失败 | mock `analyze` 抛错 → 断言 failed 行落库、不计入已评测集合、录音仍 `evaluated`、重评时该句被重跑 |

## 影响与风险

| 改动 | 影响面 | 风险 |
| --- | --- | --- |
| SSE | 四套原型页 + `index.js` 共用 `common.js`，单点修复 | 低（前后端同仓同批上线） |
| `update_recording_status` 清 `failed_reason` | 6 处调用点语义一致 | 极低；迁移 SQL 幂等 |
| 前端 `saveText` 守卫 | 三套原型页 | 低；native 已有同款行为可对照 |
| 阶段重试 | `run_analysis` 结构重组（抽阶段闭包） | 中低；测试需 patch 退避延时 |
| `evaluations` 加列 | schema 迁移、`save_evaluation` 签名、已评测集合语义、前端渲染 | 低；旧行按 `status IS NULL` 兼容 |

## 实施顺序

1. ⓪ 状态误判修复（含存量数据修复，执行前确认）
2. ① SSE 修复
3. ②③ 清残留 + UI 引导
4. ⑤ 单句评测失败记录（先做 DB 迁移）
5. ④ 阶段级重试（结构改动最大，最后做）

每步一个独立分支、小步提交；提交前 `uv run ruff format` + `uv run ruff check --fix`。
