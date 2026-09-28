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
