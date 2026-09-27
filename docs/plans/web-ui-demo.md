# Web UI Demo 实现说明

## 目标

为「日常录音分析工具」提供一套**浏览器版交互 Demo**，让用户可以：

1. 输入目录路径，由后端扫描音频文件（支持本地/网络挂载路径）；
2. 选择文件后触发预处理、声纹分离、ASR，实时通过 SSE 查看进度；
3. 在界面上逐句确认/修正 ASR 文本和说话人标签，结果实时写回 SQLite；
4. 手动触发 ISE 评测，并在每句下方展示评分与音素级错误；
5. 通过键盘快捷键（↑/↓/u/o/n/s/Space）快速操作。

同时实现 **4 套前端原型**（原生 HTML+JS、Vue 3、Alpine.js、Vue 3 + Element Plus），供最终选型对比。

## 技术栈

- **后端**：FastAPI + uvicorn，内存式后台任务（`threading.Thread`），SSE 推送进度。
- **数据库**：复用原有 SQLite，新增 `list_recordings`、`update_asr_text`、`update_speaker_label`、`save_evaluation`、`get_evaluations` 等方法。
- **前端**：4 套页面均通过 CDN 引入框架，无 npm/构建工具；共用 `common.js`（API 客户端、SSE、工具函数）和 `styles.css`。

## 新增文件

```
src/web/
├── __init__.py
├── main.py          # FastAPI 应用工厂、静态文件、CORS
├── api.py           # REST + SSE 路由
├── schemas.py       # Pydantic 请求/响应模型
├── jobs.py          # 内存任务状态
└── service.py       # 分析/评测后台任务编排

src/web/static/
├── index.html       # 入口页：列出 4 套原型
├── index.js
├── styles.css       # 共享样式
├── common.js        # API/SSE/快捷键工具
└── prototype/
    ├── native/      # 原生 HTML+JS
    ├── vue/         # Vue 3 CDN
    ├── alpine/      # Alpine.js CDN
    └── element/     # Vue 3 + Element Plus CDN

tests/test_web_api.py
docs/plans/web-ui-demo.md
```

## 修改文件

- `pyproject.toml` / `uv.lock`：新增 `fastapi`、`uvicorn[standard]`。
- `src/cli.py`：新增 `web` 子命令启动服务。
- `src/db.py`：新增数据库方法，支持 `needs_review` 标签的校正。
- `src/schema.sql`：新增 `evaluations(segment_id, eval_type)` 唯一索引。

## 后端 API 概览

| Method | Path | 说明 |
|--------|------|------|
| GET | `/` | 入口页 |
| GET | `/api/recordings` | 历史列表 |
| GET | `/api/recordings/{id}/transcription` | 完整转写视图 |
| POST | `/api/scan` | 扫描目录 |
| POST | `/api/analyze` | 启动分析，返回 `job_ids` |
| GET | `/api/jobs/{job_id}` | 任务快照 |
| GET | `/api/jobs/{job_id}/stream` | SSE 进度流 |
| GET | `/api/recordings/{id}/segments/{idx}/audio` | 片段音频 |
| PUT | `/api/recordings/{id}/segments/{idx}/speaker` | 更新说话人标签 |
| PUT | `/api/recordings/{id}/segments/{idx}/text` | 更新 ASR 文本 |
| POST | `/api/recordings/{id}/evaluate` | 启动 ISE 评测 |
| GET | `/api/recordings/{id}/evaluations` | 获取评测结果 |

## 运行方式

```bash
# 1. 安装依赖（已写入 pyproject.toml）
uv sync

# 2. 启动 Web 服务
uv run python -m src.cli web --host 127.0.0.1 --port 8000

# 3. 浏览器打开 http://127.0.0.1:8000/
#    在首页选择任意一套原型进入。
```

## 验证

```bash
uv run pytest tests/test_web_api.py -v
uv run pytest tests/ -v
```

## 断点续跑与状态记忆

- 录音状态机：`new → segmented → diarized → transcribed → corrected → evaluated`，`failed` 表示中断/失败。
- 每个阶段开始/结束/失败都会写入 `run_history` 表；失败原因记录在 `recordings.failed_reason`。
- `run_analysis` 按 `recordings.status` 跳过已完成阶段；`failed` 状态自动回退到最近一次完成的阶段继续。
- 人工修正过的说话人标签（有 `speaker_corrections` 记录）和 ASR 文本（`asr_source='manual'`）默认受保护，重跑不覆盖；只有「强制重新分析」（`force=true`）才清空重来。
- `run_evaluation` 默认跳过已评测句子，`force=true` 时重新评测全部。
- 服务重启后，内存中的任务丢失；启动时会把非终态录音标记为 `failed`，界面显示「继续分析」按钮，点击后从断点继续。
- 前端历史列表按状态显示操作：继续分析 / 编辑 / 运行 ISE / 重新评测 / 删除。

## 数据目录

```
data/
├── input/           # 用户原始录音
├── segments/{id}/   # 句子片段 WAV + meta.json + diarization.json
├── output/          # 最终报告
├── output/archive/legacy/  # 旧产物归档（一次性迁移脚本 scripts/migrate_legacy_output.py）
├── voiceprint/      # 声纹数据
└── db/              # SQLite 数据库
```

- `recording_id` 统一由 `src/recording_id.py::recording_id_from_path` 生成（路径 md5 前 12 位），同名文件不冲突。
- 重跑切分后调用 `Database.cleanup_orphan_segments` 清理孤儿片段（数据库行 + WAV 文件）。
- API：`DELETE /api/recordings/{id}` 删除整条录音；`POST /api/recordings/{id}/reset` 重置中间结果。

## 音频 API 适配

- `src/audio_adapter.py` 统一把任意输入（mp3/wav/m4a/flac、任意采样率/声道）转为 16kHz 单声道 WAV（PCM_16）或 int16 PCM 字节流，librosa 失败时 ffmpeg 兜底。
- `validate_input` 在分析开始时校验文件可读性与大小/时长限制（Ifasr_llm ≤500MB、≤5h）。
- `Transcriber._crop_to_wav`、`audio_utils.export_segment` 等已统一复用该适配层。

## 已知限制

- 后台任务为内存存储，服务重启后任务状态丢失；断点续跑通过数据库状态 + `run_history` 恢复（见上文）。
- 首次使用本地 faster-whisper 时，会从网络下载模型文件，耗时取决于网络。
- 路径扫描无白名单限制，仅用于本地 demo。
- Spark VAA 需要公网音频外链，默认评测走 ISE。
- 4 套前端原型目前页面结构一致，主要用于对比框架写法与交互体验。
