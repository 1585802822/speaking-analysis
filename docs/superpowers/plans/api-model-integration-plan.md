# 实施计划：模型 API 化集成（第一阶段）

## 变更目标

将 ASR 转写与声纹嵌入能力从本地重型模型迁移到统一的 Model API Gateway，情感和正音保持本地实现。实现 API 优先、本地回退，并保证配置灵活可扩展。

## 任务清单

### T1: 创建 `src/model_api_client.py`

- 实现 `ModelAPIClient` 类。
- 方法：
  - `transcribe(audio_path: str | Path, language: str | None) -> list[Utterance]`
  - `embed(audio_path: str | Path) -> np.ndarray`
  - 预留 `emotion(...)`、`pronunciation(...)` 接口位置（返回 NotImplemented 或占位）。
- 统一处理：
  - 从 `config["api"]` 读取 `base_url`、`api_key_env`、`timeout`、`endpoints`。
  - 读取环境变量获取 API 密钥。
  - 超时、重试（建议最多 3 次）、失败抛异常供上层回退。
  - 音频格式转换：使用已有 `crop_audio_segment` 或 pydub 确保上传 WAV 16kHz。
- 输出：代码、单元测试桩。

### T2: 扩展 `config.yaml` 与 `src/config.py`

- 在 `config.yaml` 新增 `api` 段：
  - `enabled: bool`
  - `base_url: str`
  - `api_key_env: str`
  - `timeout: int`
  - `endpoints: {asr: str, embed: str}`
- `src/config.py` 无需大改，但确保配置加载不报错；缺失 `api` 段时整体禁用 API。
- 输出：更新后的 `config.yaml`。

### T3: 改造 `src/transcriber.py`

- `Transcriber` 初始化时根据配置创建 `ModelAPIClient`（若启用）。
- `transcribe_user_segments` 流程：
  - 若 API 启用且 client 可用，调用 `client.transcribe`。
  - 若 API 失败或禁用，回退到现有 faster-whisper / 占位逻辑。
- 保持输出类型 `list[Utterance]` 不变。
- 输出：代码、更新后的 `tests/test_transcriber.py`。

### T4: 改造 `src/embeddings.py`

- 新增 API 分支：
  - `extract_embedding` 优先调用 `ModelAPIClient.embed`（若启用）。
  - 失败或禁用时回退现有 speechbrain / pyannote / MFCC 逻辑。
- `extract_embedding_from_array` 保持本地 MFCC 回退（片段级不适合直接上传）。
- 输出：代码、更新后的 `tests/test_enrollment.py` / `tests/test_diarization.py`（可选）。

### T5: 更新 Pipeline 与类型兼容性

- `Pipeline` 无需改动调用顺序，但需确保 `transcriber` 与 `embeddings` 模块在 API 失败时仍返回正确类型。
- 验证 `ProcessingResult`、`AnalysisResult` 等类型不受 API 响应影响。
- 输出：回归测试通过。

### T6: 新增 API 成功/失败单元测试

- 使用 `unittest.mock` 模拟 Gateway 响应：
  - ASR 成功返回 `Utterance` 列表；失败时回退到 faster-whisper 占位。
  - Embedding 成功返回单位向量；失败时回退到 MFCC。
- 测试配置启用/禁用切换。
- 输出：测试代码。

### T7: 端到端验证

- 在 `config.test.yaml` 中配置一个 mock Gateway（或使用真实 API，如果有）。
- 使用 `test data/20260731-112120_trimmed_180s.wav` 跑通 `register` + `analyze`。
- 验证 API 启用与禁用两种模式均生成报告。
- 输出：验证记录、可能的配置模板。

### T8: 文档更新

- 更新 `README.md`：
  - 说明 API 模式与本地模式的区别。
  - 给出 `api` 配置示例。
  - 提示隐私与上传风险。
- 输出：更新后的 `README.md`。

## 顺序依赖

```
T1 (API client)
  ├── T2 (config)
  ├── T3 (transcriber)
  ├── T4 (embeddings)
  │     └── T5 (pipeline regression)
  ├── T6 (unit tests)
  ├── T7 (end-to-end validation)
  └── T8 (README)
```

## 验收标准

- `ModelAPIClient` 实现 `transcribe` 与 `embed`。
- `config.yaml` 支持 `api` 段开关及 endpoint 配置。
- `transcriber.py` / `embeddings.py` 在 API 启用时优先调用 Gateway，失败时回退本地。
- 单元测试覆盖 API 成功与失败路径。
- 示例录音在 API 启用/禁用两种模式下均能跑通完整流水线。
- `README.md` 更新 API 配置与隐私说明。

## 风险与回退

- **风险**：Gateway 不可用或响应格式变化。
- **回退**：所有模块保留现有本地逻辑；配置 `api.enabled: false` 即可完全切回本地运行。
