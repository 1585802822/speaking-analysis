# 验证报告：任务失败处理与状态误判修复（task-failure-handling）

日期：2026-09-29

## 验证项与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 新增测试 | `uv run pytest tests/test_task_failure_handling.py -q` | 通过（14 passed） |
| 全量回归 | `uv run pytest tests/ -q`（comet build check 记录，exit=0） | 通过（189 passed，无回归） |
| 代码规范 | `uv run ruff format src/ tests/ scripts/` + `uv run ruff check --fix src/ tests/ scripts/` | 通过（无需修改，All checks passed） |
| SSE 协议 | 启动服务后 `curl /api/jobs/nonexistent/stream` | 通过：返回 `text/event-stream`，帧为 `event: job_error`，不再直接 HTTP 404 |
| test.WAV 状态 | 服务 API `/api/recordings` 与数据库直接查询 | 通过：`4bbc286330a4` 状态为 `transcribed`，`failed_reason` 为 `null`；3 条误判的 `is_manual=1` 行已还原为 `is_manual=0, asr_source='local'` |
| 重启不误标 | 服务启动日志 + `/api/recordings` 状态不变 | 通过：`transcribed` / `corrected` 已加入 `_FINAL_STATUSES`，启动恢复逻辑不再把它们标为 `failed` |
| 阶段重试（核心路径） | `tests/test_task_failure_handling.py`：monkeypatch 阶段函数前 N 次抛错 | 通过：重试轨迹写入 `run_history`，耗尽后 failed_reason 含阶段名，断点续跑只看 `completed` |
| 单句评测失败（核心路径） | `tests/test_task_failure_handling.py`：mock `analyze` 对特定句抛错 | 通过：失败句 `status='failed'` 落库、不计入已评测集合、再次评测重跑该句 |

## 端到端说明

真实服务层面的「阶段失败 → 重试 → 续跑」与「单句 ISE 失败 → 重评仅跑失败句」需要向运行中的服务注入可控错误（如临时让模型加载失败或让某句评测抛错）。当前代码未提供测试模式开关，因此这两个场景的核心逻辑由单元测试完整覆盖；真实音频/模型的端到端验证留待后续补充。

## 数据修复

已执行 `uv run python scripts/fix_misjudged_manual_asr.py --recording-id 4bbc286330a4 --apply`，把 3 条内容未变却被标记为人工修正的 ASR 行还原，并把该录音状态从 `failed` 修正为 `transcribed`、清空 `failed_reason`。

## 结论

验收标准全部满足：状态误判修复、SSE 事件协议修复、失败原因生命周期管理、阶段级自动重试、单句评测失败记录均验证通过。验证通过。
