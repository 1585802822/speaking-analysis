# 验证报告：MVP 讯飞 ASR + 发音分析

## 验证命令

```bash
uv run pytest tests/ -v --tb=short
```

## 结果

- **111 passed, 12 warnings in 27.11s**
- 本次 MVP 变更涉及的核心模块均覆盖测试：
  - `src/transcriber.py`：讯飞 ASR 与本地回退路径
  - `src/iflytek_evaluation_client.py`：ISE 评测客户端
  - `src/separator.py`：音频分离
  - `src/pipeline.py`：简化后的发音分析流水线
  - `src/pronunciation_analyzer.py`：ISE 分数接入与发音问题标记
  - `src/cli.py`：`separate` 子命令
  - `src/reporter.py`：简化报告输出

## 关键发现

- `transcriber.py` 在 API 成功时优先返回 Gateway/讯飞结果，API 失败时按配置回退到本地 faster-whisper 或占位逻辑。
- `iflytek_evaluation_client.py` 正确封装了讯飞 ISE 流式评测接口，返回音素级分数与建议。
- `pronunciation_analyzer.py` 成功将 ISE 分数映射为 `standard`/`not_standard` 标签，并生成具体字词/音素级发现。
- `cli.py` 的 `separate` 命令可正常解析并触发分离流程。
- 默认配置 `config.yaml` 已启用讯飞 API 段并补充 ISE 相关配置项。

## 待后续验证

- 在真实讯飞 API 密钥与网络环境下运行完整端到端流程。
- 使用真实多人对话录音验证 `separator.py` 与声纹过滤的集成效果。
- 对比讯飞 ASR 与本地 faster-whisper 在中文口语、中英混合场景下的准确率差异。
