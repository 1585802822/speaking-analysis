# 实现计划：声音预处理模块改造

## 变更目标

升级 `src/preprocessor.py` 及相关模块，实现可配置降噪/VAD、Segment 元数据扩展、目标说话人过滤，使下游大模型只对有效片段进行处理，节省 token。

## 任务分解

### 任务 1：扩展 `src/types.py`

- 为 `Segment` 新增字段：
  - `vad_confidence: float = 1.0`
  - `speaker_label: str | None = None`
  - `speaker_confidence: float | None = None`
  - `needs_review: bool = False`
- 确保新增字段均有默认值，现有调用不受影响。

### 任务 2：新增可选依赖

- 在 `requirements.txt` 中新增可选依赖：
  - `noisereduce`
  - `silero-vad`（或对应模型加载依赖）
- 保持现有依赖不变。

### 任务 3：改造 `src/preprocessor.py`

- 新增 `_denoise_nr(y, sr)`：基于 `noisereduce.reduce_noise` 的谱门控降噪。
- 新增 `_denoise_rnnoise(y, sr)`：基于 `rnnoise` 的神经网络降噪（如依赖可用）。
- 保留 `_denoise(y)` 作为 `spectral` 后端。
- 新增 `_vad_silero(y, sr)`：加载 `silero-vad` 模型并返回语音区间。
- 保留 `_vad(y, sr)` 作为 `energy` 后端。
- `process(path)` 根据 `config.yaml` 选择后端；模型加载失败时自动降级。
- 将 VAD 置信度写入 `Segment.vad_confidence`。

### 任务 4：新增 `src/segment_filter.py`

- 实现 `filter_target_speaker(segments, audio, enroll_embedding, config)`：
  - 对每个 Segment 提取声纹嵌入。
  - 计算与注册声纹的余弦相似度。
  - 保留高于 `similarity_threshold` 的片段。
  - 低于 `low_confidence_threshold` 的片段标记 `needs_review=True`。
- 实现 `mark_low_confidence(segments, threshold)` 辅助函数。

### 任务 5：改造 `src/diarization.py`

- 新增 `filter_segments_by_voiceprint(segments, audio, enroll_embedding)`，内部调用 `segment_filter`。
- 保持现有声纹注册/比对接口不变。

### 任务 6：更新 `config.yaml`

新增 `preprocessing` 段（详见设计文档 5.5）。确保：
- 所有阈值可配置。
- 默认值与当前行为兼容（即默认 `spectral` + `energy`）。

### 任务 7：更新 Pipeline 调用顺序

- 在 `src/pipeline.py` 中：
  1. `Preprocessor.process(audio)` 生成 Segment 列表。
  2. 如果 `speaker_filter.enabled` 为 true 且已注册声纹，调用 `Diarization.filter_segments_by_voiceprint`。
  3. 将过滤后的 Segment 列表传给下游转写/分析模块。

### 任务 8：单元测试

- 测试降噪后端切换（mock 模型加载）。
- 测试 VAD 后端切换与降级。
- 测试 Segment 元数据字段默认值与赋值。
- 测试声纹过滤：高相似度保留、低相似度标记、空注册embedding绕过。
- 测试配置读取与默认值。

### 任务 9：集成验证

- 使用示例录音跑通完整流水线。
- 统计过滤前后片段总时长，计算 token 节省比例。
- 验证降级路径：删除可选依赖后仍能通过 energy/spectral 跑通。

### 任务 10：文档更新

- 更新 README：新增预处理配置说明、模型下载提示、隐私说明。
- 更新 `openspec/changes/audio-preprocessing-pipeline/tasks.md` 任务状态。

## 依赖关系

```
任务 1 (types) ──→ 任务 3 (preprocessor)
                 ──→ 任务 4 (segment_filter)
                 ──→ 任务 5 (diarization)
任务 2 (deps)    ──→ 任务 3 (preprocessor)
任务 3/4/5       ──→ 任务 7 (pipeline)
任务 6 (config)  ──→ 任务 3/7
任务 7           ──→ 任务 8 (tests)
                 ──→ 任务 9 (integration)
                 ──→ 任务 10 (docs)
```

## 验收标准

- [ ] pytest 全部通过。
- [ ] 示例录音有效片段过滤后，下游处理时长减少 ≥30%。
- [ ] 配置切换与降级路径可验证。
- [ ] README 与任务清单已更新。

## 风险与应对

| 风险 | 应对 |
|---|---|
| `silero-vad` / `noisereduce` 安装失败 | 默认回退到 energy/spectral，不阻塞流水线。 |
| 声纹过滤误删目标语音 | 通过 `needs_review` 标记低置信度片段，用户可在报告中纠偏。 |
| 配置变更影响现有测试 | 保持默认值与旧行为一致，新增测试覆盖新配置路径。 |
