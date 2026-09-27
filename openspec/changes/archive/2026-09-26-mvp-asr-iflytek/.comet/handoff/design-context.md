# Comet Design Handoff

- Change: mvp-asr-iflytek
- Phase: design
- Mode: compact
- Context hash: 7043bf33dad70e1a3529f68b6f8bfa506598d981c26e5f52822b8312b2c5c6d5

Generated-by: comet-handoff.sh
Task hash policy: task-content-v1. Read tasks.md for live completion; excerpts are design-time context.

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/mvp-asr-iflytek/proposal.md

- Source: openspec/changes/mvp-asr-iflytek/proposal.md
- Lines: 1-23
- SHA256: 7e1e719067c5c64f60ebea56072ba6c506e8a4848014e7c5b9a3d55ca858a65c

```md
# 需求提案

## 背景

日常录音分析工具目前功能较完整，但用户希望先聚焦最小可用版本（MVP），快速验证核心价值后再逐步扩展。

## 目标

实现一个可运行的最小版本，只保留两个核心能力：
1. **音频分离**：从录音中分离出用户本人的声音（基于已注册声纹）。
2. **发音分析**：对用户语音分析普通话和英语发音是否标准。

## 关键约束

- ASR 必须接入讯飞开放平台 API，不依赖本地 faster-whisper。
- API 失败时直接报错，不自动回退本地模型。
- 发音分析需要真正给出"是否标准"的量化判断，因此使用讯飞 ISE 语音评测 API 打分。

## 成功标准

- 用户可通过 CLI 完成"注册声纹 → 分离音频 → 发音分析"完整流程。
- 分离结果导出为 `user.wav` 和 `other.wav`。
- 分析报告包含发音准确度/流利度/完整度分数及改进建议。

```

## openspec/changes/mvp-asr-iflytek/design.md

- Source: openspec/changes/mvp-asr-iflytek/design.md
- Lines: 1-73
- SHA256: a148a379c33f011294499f4447c02d5623f47b1d77ec1008fac170c93efd9386

```md
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

```

## openspec/changes/mvp-asr-iflytek/tasks.md

- Source: openspec/changes/mvp-asr-iflytek/tasks.md
- Lines: 1-37
- SHA256: a8643923031bc4d63119cedc789e1fb3a234124f09199cd69fc8e14037157d23

```md
# 任务清单

## Open

- [x] 明确 MVP 范围：音频分离 + 发音分析
- [x] 确定 ASR 走讯飞开放平台 API
- [x] 确定发音分析使用讯飞 ISE 语音评测 API 打分

## Design

- [x] 设计模块拆分与数据流
- [x] 确定配置文件变更

## Plan

- [x] 制定实现计划并写入 `.claude/plans/cheeky-hatching-pumpkin.md`

## Build

- [ ] 修改 `src/transcriber.py` 支持讯飞 ASR
- [ ] 新建 `src/iflytek_evaluation_client.py`
- [ ] 新建 `src/separator.py`
- [ ] 修改 `src/pipeline.py` 只保留发音分析
- [ ] 修改 `src/pronunciation_analyzer.py` 接入 ISE 分数
- [ ] 修改 `src/cli.py` 新增 `separate` 命令
- [ ] 修改 `src/reporter.py` 简化报告
- [ ] 修改 `config.yaml` 启用讯飞 API 并补充 ISE 配置
- [ ] 新增单元/集成测试

## Verify

- [ ] 运行测试套件
- [ ] 使用真实/测试音频验证 CLI 流程

## Archive

- [ ] 合并分支并归档 change

```
