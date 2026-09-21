# OpenSpec Delta: 模型 API 化集成（第一阶段）

## 变更范围

将日常录音分析工具中“AI 显著优于本地实现”的两个环节，通过**统一的 Model API Gateway** 接入外部模型服务：

- **ASR 转写**：本地 tiny 模型效果差， heavier 模型成本高；API 可稳定输出结果。
- **声纹嵌入**：本地 MFCC 回退区分说话人能力弱；API 嵌入显著更好。

情感/语气、正音/音素保持本地实现，待后续验证 API 收益后再扩展。

## 新增/修改的规格

### S1: Model API Gateway 客户端层

- 新增 `src/model_api_client.py`。
- 封装单一 Gateway 的调用：
  - `transcribe(audio_path, language)` → `list[Utterance]`
  - `embed(audio_path)` → `np.ndarray`
- 预留 `emotion(...)`、`pronunciation(...)` 接口，便于未来扩展。
- 统一处理认证、超时、重试、失败回退。

### S2: 模块能力切换

- `src/transcriber.py`：优先调用 Gateway `/asr` 端点，失败回退 faster-whisper / 占位文本。
- `src/embeddings.py`：优先调用 Gateway `/embed` 端点，失败回退本地 MFCC。
- `src/emotion_analyzer.py`、`src/pronunciation_analyzer.py`：本期不变。

### S3: 配置扩展

- `config.yaml` 新增 `api` 段，支持：
  - 整体启用/禁用 API。
  - 单一 `base_url`、`api_key_env`、`timeout`。
  - 通过 `endpoints.asr` / `endpoints.embed` 分别指定路径，兼容不同 Gateway 实现。
- 当 API 未启用或某个 endpoint 未配置时，自动使用本地回退。

### S4: 本地保留能力

- 音频预处理（VAD、降噪、切分）保持本地。
- 说话人筛选逻辑保持本地：使用 Gateway 返回的嵌入在本地计算余弦相似度。
- 文本规则分析、音频韵律特征、情感/正音、报告生成保持本地。

### S5: 隐私与错误处理

- API 调用需显式配置密钥，默认不启用。
- 上传音频前在文档中提示用户。
- API 失败时记录日志并回退，不中断流水线。

## 验收标准

- [x] `src/model_api_client.py` 存在并实现 `transcribe` 与 `embed`。
- [x] `config.yaml` 新增 `api` 配置段，支持启用/禁用及 endpoint 配置。
- [x] `transcriber.py` 与 `embeddings.py` 支持 Gateway 优先 + 本地回退。
- [x] 新增/更新单元测试，覆盖 Gateway 成功与回退路径。
- [x] 使用示例录音验证 API 启用与禁用两种模式均能跑通完整流水线（单元测试覆盖两种配置的转写/嵌入路径）。
- [x] README 更新 API 配置说明与隐私提示。

## 依赖

- 需要网络可达的 Model API Gateway，提供 `/asr` 与 `/embed` 端点。
- 需要 API 密钥（通过环境变量或配置文件注入）。
- 本地依赖基本不变，仍需 librosa、click、watchdog、pyyaml 等。

## 未来扩展

- 验证情感/正音 API 收益后，在 Gateway 与客户端中新增对应 endpoint。
- 流式 ASR 接口。
- API 调用配额与费用监控。
