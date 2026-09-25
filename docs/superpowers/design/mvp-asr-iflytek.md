---
comet_change: mvp-asr-iflytek
role: technical-design
canonical_spec: openspec
---

# Superpowers Design Doc: MVP 音频分离 + API 发音分析

## 目标

构建日常录音分析工具的最小可用版本（MVP），仅保留：
1. **音频分离**：基于已注册声纹，从录音中分离用户语音与非用户语音。
2. **发音分析**：通过讯飞开放平台 ASR + ISE 语音评测 API，对普通话和英语发音打分。

## 非目标

- 不实现文本分析（填充词、重复、长句等）
- 不实现音频特征分析（语速、停顿、音量等）
- 不实现情感/语气分析
- 不实现文件夹监控、声纹纠偏等高级功能

## 架构图

```
输入音频
  │
  ▼
Preprocessor ──→ 降噪 + VAD + 切分
  │
  ▼
DiarizationModule ──→ 基于注册声纹识别用户片段
  │
  ├──→ Separator ──→ user.wav / other.wav
  │
  ▼
Transcriber (讯飞 ASR API) ──→ 用户片段转写为 Utterance
  │
  ▼
PronunciationAnalyzer (讯飞 ISE API) ──→ 发音分数 + 拼音/音标
  │
  ▼
Reporter ──→ 简化版报告
```

## 关键模块

| 文件 | 职责 |
|------|------|
| `src/transcriber.py` | 新增讯飞 ASR 支持，API 失败直接抛异常 |
| `src/iflytek_evaluation_client.py` | 封装讯飞 ISE 语音评测 API |
| `src/separator.py` | 根据 Segment.is_user 导出用户/非用户音频 |
| `src/pipeline.py` | 只保留发音分析 |
| `src/pronunciation_analyzer.py` | 整合 ASR 文本与 ISE 分数 |
| `src/cli.py` | 新增 `separate` 命令 |
| `src/reporter.py` | 简化报告 |
| `config.yaml` | 启用讯飞 API，补充 ISE 配置 |

## 接口契约

### `iFlytekEvaluationClient.evaluate(audio_path, text, category)`

- `audio_path`: 待评测音频文件路径
- `text`: 参考文本（来自 ASR 结果）
- `category`: 评测题型，如 `read_sentence`
- 返回： dict，包含 `overall_score`, `fluency_score`, `integrity_score`, `accuracy_score`

### `PronunciationAnalyzer.analyze(utterances, audio_path=None)`

- `utterances`: ASR 返回的句子列表
- `audio_path`: 原始音频路径，用于 ISE 评测
- 返回：发音分析的 `AnalysisResult`

## 配置

```yaml
api:
  enabled: true
  provider: iflytek
  iflytek:
    mode: long
    app_id: ""          # 从 IFLYTEK_APP_ID 读取
    api_key: ""         # stream 模式需要
    api_secret: ""      # 从 IFLYTEK_API_SECRET 读取
    language: cn
    evaluation:
      app_id: ""
      api_secret: ""
```

## 验收标准

- `uv run python -m src.cli register enroll.wav` 成功注册声纹
- `uv run python -m src.cli separate input.wav --output-dir out/` 生成 `user.wav` 和 `other.wav`
- `uv run python -m src.cli analyze input.wav` 生成包含发音分数的报告
- 新增测试覆盖 iflytek ASR 和 ISE 评测路径

## 风险

- 讯飞 API 收费
- ISE 对口语化、中英混合文本评分可能偏低
- API 失败直接报错，要求网络与密钥可用
