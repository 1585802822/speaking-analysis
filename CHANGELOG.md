# Changelog

本项目所有显著变更都会记录在此文件中。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)：修 bug 末位 +1，新功能中位 +1，破坏性大改首位 +1。

## [Unreleased]

### 新增

- 阶段级自动重试：分析流水线各阶段失败后自动重试（句子切分 1 次，声纹分离 / 语音转写 2 次，指数退避 2s→4s），每次尝试的起止与错误完整写入 `run_history`；耗尽后仍按失败收尾并记录失败阶段。由于 `_last_completed_status` 只认 `completed`，重试不破坏断点续跑。
- 单句评测失败记录：`evaluations` 表新增 `status` / `error_message` 列（启动时幂等迁移）。ISE 单句失败改为落库而非静默跳过，失败行不计入已评测集合，因此再次评测会自动只重跑失败句；评测完成消息提示「N/M 句未评上」，编辑页对失败句显示失败占位与原因。
- 失败可视化：历史列表失败行高亮，失败原因带失败阶段（如「语音转写阶段失败：…」），并提供「继续分析」续跑引导。
- 新增一次性修复脚本 `scripts/fix_misjudged_manual_asr.py`：还原「内容未变却被标记为人工修正」的 ASR 行，默认只预览，`--apply` 才写入。

### 修复

- 录音状态误判为 `failed`：`_FINAL_STATUSES` 漏了 `transcribed` / `corrected`，导致**每次服务重启**都把「分析已完成但未评测」的录音标记为失败。现补入这两个状态——它们是分析流水线的正常终点，评测只是可选的后续动作。
- 试听被误判为人工修正：Vue / Element / Alpine 三套原型页的文本框在失焦时无条件提交，试听时点一下文本框就会写入 `is_manual=1`，进而把录音状态误判为 `corrected`。现三套页面均增加「内容未变不提交」守卫，对齐原生页行为。
- SSE 进度推送失效：服务端推送的是命名事件 `event: update`，前端却只用 `es.onmessage`（按 SSE 协议仅接收无 `event` 字段的默认消息），导致进度**永远收不到**，且流正常结束时误报「SSE 连接错误」。现改为监听 `update`，业务错误改用 `job_error` 事件与浏览器网络层错误区分，并仅在「从未收到任何事件且连接已关闭」时才报连接错误。
- 失败原因残留：`update_recording_status` 在状态成功推进时一并清空 `failed_reason`（该字段只由 `mark_recording_failed` 写入）；启动迁移顺带修复存量脏数据——状态不为 `failed` 却残留失败原因的录音会被清空。
- 浏览器自动请求 `/favicon.ico` 返回 404 的日志噪音：`src/web/main.py` 新增 `/favicon.ico` 路由返回 204 No Content（`include_in_schema=False`）。
- `scripts/start.bat` 双击报错 `scripts\scripts\launcher.py`：移除批处理内 UTF-8 中文注释（cmd 按 GBK 解析导致字节错位、`cd` 失效），改为英文 ASCII 注释 + CRLF 换行 + 绝对路径 `%~dp0launcher.py` 双保险；新增 `.gitattributes`（`*.bat eol=crlf`）与 `TestStartBat` 防回归测试。

- 浏览器版 Web UI Demo：基于 FastAPI + SSE 提供后端 API，前端同时实现 4 套原型（原生 HTML+JS、Vue 3 CDN、Alpine.js CDN、Vue 3 + Element Plus CDN），支持目录扫描、音频分析、ASR 文本/说话人标签修正、ISE 评测结果展示与键盘快捷键。
- ASR 切换为讯飞「录音文件转写大模型版」（Ifasr_llm）：新增 `iFlytekLlmASRClient` 与工厂 `build_llm_asr_client`，走 `上传音频获取 orderId → 轮询 getResult` 流程，HMAC-SHA1 签名；`api.iflytek.mode` 新增 `llm`。
- 发音评测新增讯飞「Spark VAA 语音分析」可选实现 `iFlytekVoiceInsightClient`（`src/iflytek_evaluation_client.py`），走 `创建任务 → 轮询结果` 流程，HMAC-SHA256 鉴权；`evaluation.mode` 新增 `voice_insight` 选项（默认仍为 `ise`）。
- 新增实测脚本 `scripts/test_iflytek_live.py`（Ifasr_llm + Spark VAA）与 `scripts/test_ise_live.py`（Ifasr_llm + ISE，已从流式版 ASR 切换为 Ifasr_llm）。
- 发音评测 ISE 结果改为**音素级发音细节**：中文句子评测结果从 `word` 层级下沉到 `phone` 层级（声母/韵母是否正确），报告与实测脚本可逐音素展示发音不标准的位置（`ise_phone` finding）。
- 断点续跑与状态记忆：录音状态机扩展为 `new → segmented → diarized → transcribed → corrected → evaluated`（另有 `failed`），每个阶段起止写入 `run_history` 表；分析/评测按状态跳过已完成阶段，服务重启后自动标记中断录音并可从断点继续。
- 手工修正保护：用户修正过的说话人标签（`speaker_corrections`）和 ASR 文本（`is_manual`）在普通重跑时不被覆盖，仅「强制重新分析」（`force=true`）才清空重来。
- 音频 API 适配层 `src/audio_adapter.py`：统一把任意格式/采样率/声道音频转成 16kHz 单声道 WAV（PCM_16）或 int16 PCM 字节流，librosa 失败时 ffmpeg 兜底；`validate_input` 预校验文件可读性与大小/时长限制（Ifasr_llm ≤500MB、≤5h）。
- 统一录音 ID：新增 `src/recording_id.py`，按音频文件解析路径生成 md5 前 12 位作为 `recording_id`，同名文件不冲突；重跑切分后自动清理孤儿片段（数据库行 + WAV 文件）。
- 新增旧产物迁移脚本 `scripts/migrate_legacy_output.py`：把 `data/output/01_preprocessed`、`02_separated` 及旧报告归档到 `data/output/archive/legacy/`。

### 变更

- 状态文案：`failed` 由「处理中断」改为「处理失败」，与真实失败原因（服务重启、阶段报错）区分。
- 历史列表与编辑页的「继续分析」按钮补充说明：将从最近完成的阶段继续，不会重跑已完成的阶段。
- `config.yaml` 默认 `iflytek.mode: llm`、`language: autodialect`（中英+方言自动识别）；`evaluation.mode` 默认 `ise`（`model_code: xdeepseekv31` 为 voice_insight 备选）。
- `.env.example` 补充说明：app_id / api_key / api_secret 三者复用同一套凭证，服务器靠不同 host+path 区分服务。
- 数据库目录规范为 `data/db/`；SQLite schema 新增 `run_history` 表、`recordings` 表新增 `created_at`/`run_count`/`failed_reason` 字段、`asr_results` 表新增 `is_manual` 字段（旧库启动时自动幂等迁移）。
- Web API 新增：`POST /api/recordings/{id}/continue`（从断点继续分析）、`DELETE /api/recordings/{id}`（删除整条录音）、`POST /api/recordings/{id}/reset`（重置中间结果）、`POST /api/recordings/{id}/evaluate?force=`（继续/重评 ISE）。
- 前端 4 套原型的历史列表按状态显示操作按钮（继续分析 / 编辑 / 运行 ISE / 重新评测 / 删除），编辑页支持继续分析与重新评测。
- `config.yaml` 切分参数调整：`pause_threshold_sec: 0.7`，新增 `target_sentence_sec: 2.0`（相邻短句合并目标句长）。

### 修复

- 说话人标签收敛为 user / other 二分：不再产生 needs_review 档（相似度 ≥ 阈值判为 user，其余一律 other），旧数据在读取层归一化为 other。
- 非 user 句改用本地 faster-whisper 转写（首次使用时懒加载，服务启动不被大模型拖慢）；user 句 API 失败或结果为空时自动回退本地模型，不再大面积出现占位文本。
- 句子切分优化：停顿阈值 0.4 → 0.7 秒、句边界取停顿终点（不吞下一句开头）、长句在能量谷处切分、相邻短句合并到 2 秒以上，减少「一句话从中间切开」。
- 键盘快捷键修复：事件直接派发到列表容器（不再依赖焦点冒泡），新增 `x` 键一键翻转 user/other；修复 Alpine 版 `init()` 被自动调用导致的双重注册。
- 前端依赖本地化到 `src/web/static/vendor/`（Vue / Element Plus / Alpine），页面不再依赖 unpkg / jsdelivr CDN，Element Plus 版可正常使用。
- UI 细节：状态文案「已校正」改为「待校对」；「继续分析」按钮仅在分析中断时显示并附带说明；时长/处理时间显示精简；文件名不显示扩展名。

### 说明

- Spark VAA 只接收音频外链 `audioFileURL`，本地文件需先转成公网可访问的 URL（普通内网机器需自行解决外链/内网穿透），故默认评测仍走 ISE。

## [0.2.0] - 2026-09-24

### 新增

- 接入讯飞开放平台 ASR（录音文件识别 / 流式听写），API 启用时失败直接报错、不回退本地模型。
- 新增讯飞语音评测（ISE）客户端 `src/iflytek_evaluation_client.py`，输出准确度/流利度/完整度量化分数。
- 新增 `src/separator.py` 与 `separate` CLI 命令，按声纹把录音切分为 `user.wav` / `other.wav`。
- 发音分析改为优先 ISE 打分（可配置 `standard_threshold` 判定是否标准），本地拼音/音标提示仅作回退。

### 变更

- `config.yaml` 启用讯飞 API 并补充 ISE 评测配置；`analysis.pronunciation.standard_threshold` 默认 80。
- 报告 `详细发现` 章节更名为 `发音评测结果`。
- `.env.example` 新增 `IFLYTEK_APP_ID` / `IFLYTEK_API_KEY` / `IFLYTEK_API_SECRET` 说明。

## [0.1.0] - 2026-09-01

### 初始版本

- 搭建录音分析流水线骨架（预处理、声纹、分离、转写、报告）。
