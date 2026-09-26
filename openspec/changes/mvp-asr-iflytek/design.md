# 设计文档

## 概述

本次改动为日常录音分析工具构建 MVP：仅保留声纹注册、音频分离、API ASR 转写、语音评测打分四个核心环节。

## 架构

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
Transcriber (讯飞 API) ──→ 用户片段转写为 Utterance
  │
  ▼
PronunciationAnalyzer (讯飞 ISE API) ──→ 发音分数 + 拼音/音标
  │
  ▼
Reporter ──→ 简化版报告
```

## 模块职责

- `src/transcriber.py`：新增讯飞 ASR 支持，API 失败直接抛异常。
- `src/iflytek_evaluation_client.py`（新建）：封装讯飞 ISE 评测 API。
- `src/separator.py`（新建）：根据 Segment.is_user 导出用户/非用户音频。
- `src/pronunciation_analyzer.py`：整合 ASR 文本与 ISE 分数，生成发音建议。
- `src/pipeline.py`：只保留发音分析，移除文本/音频/情感分析器。
- `src/cli.py`：新增 `separate` 命令。
- `src/reporter.py`：简化报告模板。
- `config.yaml`：启用讯飞 API，补充 ISE 配置。

## 数据流

1. `cli analyze` 调用 `Pipeline.process(audio_path)`。
2. `Pipeline` 用 `Preprocessor` 切分音频。
3. `DiarizationModule.split_by_voiceprint` 识别用户片段。
4. `Transcriber` 调用讯飞 ASR 获取带时间戳的文本。
5. `PronunciationAnalyzer` 对每个用户片段调用 ISE 评测，结合拼音/音标输出分数。
6. `Reporter` 生成 Markdown/JSON 报告。

## 错误处理

- 未注册声纹：明确提示用户先执行 `register`。
- 讯飞 ASR/ISE 鉴权或网络失败：抛出异常，终止流程，不自动回退本地模型。
- 某个片段 ISE 评测失败：记录警告，跳过该片段，继续处理其他片段。

## 配置

```yaml
api:
  enabled: true
  provider: iflytek
  iflytek:
    mode: long          # ASR 模式：long | stream
    app_id: ""          # 从环境变量 IFLYTEK_APP_ID 读取
    api_key: ""         # stream 模式需要
    api_secret: ""      # 从环境变量 IFLYTEK_API_SECRET 读取
    language: cn        # long: cn | en; stream: zh_cn | en_us
    evaluation:
      app_id: ""        # 可与 ASR 相同
      api_secret: ""    # 可与 ASR 相同
```

环境变量名通过 `api_key_env` 字段指定。
