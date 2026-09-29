# task-failure-handling Specification

## Purpose
TBD - created by archiving change task-failure-handling. Update Purpose after archive.

## Requirements

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

- **WHEN** 某阶段在耗尽重试后仍然失败
- **THEN** 该录音 `failed_reason` 形如「<阶段名>阶段失败：<原因>」，阶段名取自句子切分 / 声纹分离 / 语音转写 / 发音评测

#### Scenario: 历史列表提供续跑入口

- **WHEN** 历史列表中存在 `failed` 状态的录音
- **THEN** 该行以醒目样式展示失败原因，并提供「继续分析」操作，提示将从最近完成的阶段继续

### Requirement: 阶段级自动重试

系统 SHALL 对分析流水线各阶段执行有限次自动重试，重试过程与结果 SHALL 完整记录在 `run_history`。

#### Scenario: 瞬时故障被重试吸收

- **WHEN** 语音转写阶段首次调用抛出异常，后续调用成功
- **THEN** 该阶段被重试，`run_history` 记录失败与成功轨迹，任务最终标记为完成

#### Scenario: 重试次数按阶段区分

- **WHEN** 句子切分阶段失败
- **THEN** 最多重试 1 次；声纹分离与语音转写阶段失败时最多重试 2 次

#### Scenario: 重试耗尽后按失败收尾

- **WHEN** 某阶段在耗尽全部重试后仍失败
- **THEN** 该录音被标记为 `failed` 并记录失败阶段，任务状态为 `failed`，退避等待不阻塞其他任务

#### Scenario: 重试不破坏断点续跑

- **WHEN** 某阶段重试若干次后最终成功
- **THEN** 断点续跑的起点判定不受失败尝试记录影响（只依据最近一次 `completed`）

### Requirement: 单句评测失败记录

系统 SHALL 记录 ISE 评测中单句失败的结果，使其可被查询、展示与重跑。

#### Scenario: 单句失败落库

- **WHEN** 某片段的 ISE 评测抛出异常
- **THEN** 该片段写入一条评测记录，状态为 `failed` 并携带错误信息；其余片段继续评测

#### Scenario: 失败句不计入已评测集合

- **WHEN** 查询某录音已完成评测的片段集合
- **THEN** 状态为 `failed` 的评测记录不计入该集合

#### Scenario: 失败句可重跑

- **WHEN** 用户对同一录音再次发起评测且未选择强制重跑
- **THEN** 上次失败的片段被重新评测，已成功的片段被跳过

#### Scenario: 结果可感知

- **WHEN** 某次评测存在失败片段
- **THEN** 任务完成消息提示未评上的句数与总数；编辑页对失败片段展示失败占位与错误信息
