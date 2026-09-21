# API 模型集成设计文档

## 1. 背景与目标

当前实现依赖本地重型模型（faster-whisper、speechbrain/pyannote.audio、emotion2vec、phonemizer）。这些模型体积大、首次下载慢、对硬件有要求，且在本项目早期验证中难以快速跑通。

用户原则：

1. **只有当使用 AI 能显著好于不使用 AI 的部分才使用 AI**。
2. **AI 来源尽量集中**，用尽可能少的 API 解决多种问题；API 应全能，但不能为了普适性忽视性能。

基于现有本地回退能力评估：

- **声纹嵌入**：本地 MFCC 统计特征区分说话人能力弱，API 嵌入显著更好 → **优先 API 化**。
- **ASR 转写**：本地 tiny 模型在测试样本上无输出， heavier 模型下载/运行成本高；API 可稳定获得转写结果 → **优先 API 化**。
- **情感/语气**：本地 librosa 韵律分析已能给出演示级标签；API 不一定显著优于本地 → **保持本地**。
- **正音/音素**：本地 pypinyin + phonemizer 已能给出基础提示；API 收益待验证 → **保持本地**。

因此本次变更目标：
- **将 ASR 与声纹嵌入集中到一个 Model API Gateway**。
- **保留本地模块**：音频预处理、说话人匹配（基于 API 返回的嵌入在本地做余弦相似度）、文本规则分析、音频韵律特征、情感/正音、报告生成。
- **保持可扩展**：Gateway 预留 Emotion / Pronunciation 端点，后续收益验证后可快速接入。
- **保持向后兼容**：当 API 不可用时自动回退到现有本地逻辑。

## 2. 架构概览

见同目录下的交互式架构图：

- `api-model-integration-architecture.html`

核心边界：

- **本地运行时**：CLI、Pipeline、Preprocessor、Diarization、TextAnalyzer、AudioAnalyzer、EmotionAnalyzer、PronunciationAnalyzer、Reporter。
- **Model API Gateway**：统一提供 ASR 与 Speaker Embedding 能力（可扩展）。

## 3. 模块变更计划

### 3.1 新增 `src/model_api_client.py`

封装对单一 Model API Gateway 的调用：

- `ModelAPIClient.transcribe(audio_path, language)` → `list[Utterance]`
- `ModelAPIClient.embed(audio_path)` → `np.ndarray`（用于注册与 diarization）
- （预留）`ModelAPIClient.emotion(...)`
- （预留）`ModelAPIClient.pronunciation(...)`

统一处理：
- 单一 `base_url`、单一 API 密钥从环境变量或配置文件读取。
- 请求超时、重试、失败回退。
- 输入音频格式转换（WAV/PCM 16kHz）。
- 通过配置 `endpoints` 分别指定 `/asr`、`/embed` 路径，兼容不同 Gateway 实现。

### 3.2 改造现有模块

| 模块 | 当前行为 | 变更后 |
|---|---|---|
| `src/transcriber.py` | 加载 faster-whisper | 优先调用 `ModelAPIClient.transcribe`，失败回退 faster-whisper / 占位文本 |
| `src/embeddings.py` | 本地 speechbrain/pyannote/MFCC | 优先调用 `ModelAPIClient.embed`，失败回退本地 MFCC |
| `src/emotion_analyzer.py` | emotion2vec / librosa 回退 | 保持本地，未来可接入 Gateway emotion 端点 |
| `src/pronunciation_analyzer.py` | pypinyin + phonemizer | 保持本地，未来可接入 Gateway pronunciation 端点 |
| `src/config.py` | 无 | 保持；配置项新增 `api` 段 |

### 3.3 配置变更

`config.yaml` 新增 `api` 段（示例）：

```yaml
api:
  enabled: true
  base_url: https://your-ai-gateway.example.com
  api_key_env: AI_GATEWAY_API_KEY
  timeout: 120
  endpoints:
    asr: /v1/audio/transcriptions
    embed: /v1/audio/embeddings
```

当 `api.enabled` 为 `false` 或某个 endpoint 未配置时，该能力使用本地回退。

### 3.4 隐私与错误处理

- 上传音频前需明确告知用户；默认不上传非必要片段。
- API 失败时记录日志并回退，不中断流水线。
- 声纹注册音频可选择本地 MFCC 或 API 嵌入，由配置决定。

## 4. 接口约束

- 保持 `src/types.py` 中的 `Segment`、`Utterance`、`Word`、`AnalysisResult`、`ProcessingResult` 不变。
- 保持 CLI 命令不变：`register`、`analyze`、`watch`、`correct`。
- `Pipeline.process` 调用顺序不变，只是内部模块根据配置选择 API 或本地实现。

## 5. 验收标准

- [ ] 新增 `src/model_api_client.py` 并实现 `transcribe` 与 `embed`，预留 emotion/pronunciation 接口。
- [ ] `config.yaml` 新增 `api` 配置段，支持启用/禁用及 endpoint 配置。
- [ ] `transcriber.py` 与 `embeddings.py` 优先使用 Gateway，失败时回退到本地逻辑。
- [ ] 单元测试覆盖 Gateway 成功与失败回退路径。
- [ ] 使用示例录音验证 API 启用与禁用两种模式均能跑通完整流水线。
- [ ] README 更新 API 配置说明与隐私提示。

## 6. 未来扩展

- 当情感/正音的 API 收益被验证后，在 Gateway 与客户端中新增对应 endpoint。
- 支持流式 ASR 接口，降低长音频延迟。
- 支持 API 调用配额/费用监控。
