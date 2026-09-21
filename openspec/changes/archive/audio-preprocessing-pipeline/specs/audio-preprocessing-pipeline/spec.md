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
