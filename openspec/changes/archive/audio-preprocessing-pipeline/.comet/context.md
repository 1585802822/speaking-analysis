# Comet Design Handoff

- Change: audio-preprocessing-pipeline
- Phase: design
- Mode: full
- Context hash: 6a6feb315de2efbe10e18d45a9c21c2723217326ee6d91453d650745b324a002

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/audio-preprocessing-pipeline/proposal.md

- Source: openspec/changes/audio-preprocessing-pipeline/proposal.md
- Lines: 1-42
- SHA256: 2c304ad8516e790cdae14614f8c630d943f42250f69be1846b7a324ed80f9d27

```md
# 变更提案：声音预处理模块改造

## 目标

升级音频预处理模块，使其能够：

1. 更有效地降噪，抑制非平稳噪声。
2. 更准确地检测语音活动（VAD），减少误判。
3. 在预处理阶段结合声纹信息，只保留目标说话人的有效片段。
4. 显著减少下游大模型（ASR、文本分析、情感/正音）需要处理的音频时长，从而节省 token。

## 背景

当前 `src/preprocessor.py` 使用固定前 100ms 的谱减法降噪和基于能量阈值的 VAD。在以下场景表现不佳：

- 背景噪声非平稳（空调、键盘、车辆声）。
- 录音电平变化大，能量阈值需要频繁调整。
- 多人对话场景下，非目标说话人片段也会被送入下游，浪费 token。

## 预期收益

- 有效片段过滤后，下游大模型调用时长预计减少 30–50%（方案 A）。
- 提升转写准确率，减少大模型因噪声产生的幻觉文本。
- 保持本地处理，不上传录音，符合隐私约束。

## 范围

- 改造 `src/preprocessor.py`：支持可配置的降噪/VAD 后端。
- 扩展 `src/types.py`：Segment 新增元数据字段。
- 改造 `src/diarization.py`：按声纹过滤 Segment。
- 新增/更新配置、测试、文档。

## 非目标

- 本期不上线完整的说话人分离（diarization）功能（方案 B），仅作为未来扩展预留接口。
- 不使用云端 API 进行预处理，保持本地优先。

## 验收标准

- 配置可切换降噪/VAD 后端。
- 有效片段过滤后，示例录音的下游 token 消耗可量化降低。
- 单元测试覆盖新后端、降级路径、声纹过滤。

```

## openspec/changes/audio-preprocessing-pipeline/design.md

- Source: openspec/changes/audio-preprocessing-pipeline/design.md
- Lines: 1-71
- SHA256: d5167792b2578f1280f01293e4a339d3f37c955f3b494f07d859eea177ef4ff8

```md
# OpenSpec Delta: 声音预处理模块改造

## 变更范围

升级音频预处理模块，实现更稳健的降噪、VAD 和目标说话人过滤，使下游大模型只对“有效片段”进行处理，从而节省 token。

## 新增/修改的规格

### S1: 可配置降噪后端

- `src/preprocessor.py` 支持三种降噪后端：
  - `noisereduce`：基于谱门控，可学习噪声样本。
  - `rnnoise`：轻量神经网络降噪。
  - `spectral`：现有固定谱减法，作为回退。
- 后端通过 `config.yaml` 的 `preprocessing.denoise.backend` 配置。

### S2: 可配置 VAD 后端

- `src/preprocessor.py` 支持两种 VAD 后端：
  - `silero`：本地 ONNX 模型，准确率高于能量法。
  - `energy`：现有能量阈值 VAD，作为回退。
- 后端通过 `config.yaml` 的 `preprocessing.vad.backend` 配置。
- VAD 边界结合最短/最长时长约束生成 Segment。

### S3: Segment 元数据扩展

- `src/types.py` 的 `Segment` 新增字段：
  - `vad_confidence: float`
  - `speaker_label: str | None`
  - `speaker_confidence: float | None`
  - `needs_review: bool`
- 新增字段均有默认值，保持向后兼容。

### S4: 目标说话人过滤

- `src/diarization.py` 新增 `filter_segments_by_voiceprint(segments, audio, enroll_embedding)`：
  - 对 Segment 逐段提取声纹嵌入。
  - 与注册声纹比对，保留相似度高于 `similarity_threshold` 的片段。
  - 相似度低于 `low_confidence_threshold` 的片段标记 `needs_review=True`。
- 过滤结果用于下游转写、文本分析、情感/正音。

### S5: 配置扩展

- `config.yaml` 新增 `preprocessing` 段：
  - `denoise.backend`、`noise_sample_sec`
  - `vad.backend`、`min_speech_duration_ms`、`max_silence_duration_ms`、`threshold`
  - `segmentation.target_sample_rate`、`min_segment_duration_sec`、`max_segment_duration_sec`
  - `speaker_filter.enabled`、`similarity_threshold`、`low_confidence_threshold`

### S6: 降级策略

- 当配置的本地模型（noisereduce、RNNoise、silero-vad）加载失败时，自动回退到 energy VAD + spectral 降噪。
- 降级路径需记录日志，不中断流水线。

## 验收标准

- [ ] 降噪/VAD 后端可通过配置切换，并有单元测试覆盖。
- [ ] Segment 新增元数据字段，不影响现有调用。
- [ ] 声纹过滤能正确保留目标说话人片段并标记低置信度片段。
- [ ] 示例录音处理后，下游转写 token 消耗可量化降低。
- [ ] README 更新配置说明与模型下载/隐私提示。

## 依赖

- 新增可选依赖：`noisereduce`、`silero-vad`（或对应模型文件）。
- 本地依赖基本不变，仍需 librosa、numpy 等。

## 未来扩展

- 引入 `pyannote.audio` 本地 diarization，实现多人场景下的精确说话人分离。
- 增加片段质量评分（信噪比、混响、重叠度）。

```

## openspec/changes/audio-preprocessing-pipeline/tasks.md

- Source: openspec/changes/audio-preprocessing-pipeline/tasks.md
- Lines: 1-25
- SHA256: fccba32b1dbdcbf508096ff46929d648181f24ab844099a730197fbc178139ef

```md
# 任务清单：声音预处理模块改造

## 设计阶段

- [x] 编写变更提案 `proposal.md`
- [x] 编写设计文档 `design.md`
- [ ] 用户确认设计方案
- [ ] 生成 Superpowers 设计文档 `docs/superpowers/specs/audio-preprocessing-pipeline-design.md`

## 实现阶段

- [ ] 扩展 `src/types.py`：Segment 新增元数据字段
- [ ] 改造 `src/preprocessor.py`：支持可配置降噪/VAD 后端
- [ ] 新增 `src/segment_filter.py`：目标说话人过滤逻辑
- [ ] 改造 `src/diarization.py`：按声纹过滤 Segment
- [ ] 更新 `config.yaml`：新增 `preprocessing` 配置段
- [ ] 更新 `requirements.txt`：新增可选依赖
- [ ] 新增/更新单元测试
- [ ] 更新 README

## 验证阶段

- [ ] 运行 pytest 全部通过
- [ ] 使用示例录音验证有效片段过滤效果
- [ ] 量化下游 token 节省比例

```
