# 声音预处理模块改造设计文档

## 1. 背景与目标

当前 `src/preprocessor.py` 已实现：

- **降噪**：基于固定前 100ms 噪声谱的谱减法，对非平稳噪声效果有限。
- **VAD**：基于能量阈值，对底噪、喘息声、键盘声等容易产生误判。
- **切分**：在 VAD 语音段内按 onset 自然切分，控制片段时长。

本次变更目标：

1. **更干净的语音段**：通过更稳健的降噪 + VAD，把“非语音”提前过滤掉。
2. **更聚焦目标说话人**：在预处理阶段就结合声纹信息，只保留高置信度的目标说话人片段。
3. **为大模型节省 token**：下游转写、文本分析、情感/正音等大模型调用，只发生在“有效片段”上。
4. **保持本地优先**：与项目隐私约束一致，核心模型继续跑在本地。

## 2. 设计原则

- **能本地就不上云**：音频不上传，模型本地加载。
- **可降级**：任何本地模型加载失败时，自动回退到当前能量 VAD / 谱减法实现。
- **可观测**：每个 Segment 携带元数据（开始时间、结束时间、VAD 置信度、声纹置信度、说话人标签），便于调试与人工复核。
- **可配置**：所有阈值进入 `config.yaml`，方便针对不同录音环境调参。

## 3. 方案选型

### 方案 A：本地轻量增强（本期推荐）

| 环节 | 当前 | 改造后 |
|---|---|---|
| 降噪 | 固定谱减法 | `noisereduce` 谱门控 或 `RNNoise` |
| VAD | 能量阈值 | `silero-vad`（本地 ONNX） |
| 有效片段 | VAD 边界 | VAD 边界 + 最短/最长时长约束 |
| 目标说话人过滤 | 无 | 对 VAD 语音段跑声纹，过滤非目标说话人 |

- **效果**：预计过滤 30–50% 的非语音/非目标内容，显著降低下游 token。
- **成本**：模型体积约 15–25MB，CPU 实时；无 API 费用；工程改动小。
- **风险**：多人重叠或远场语音可能漏判，可通过置信度阈值 + 用户纠偏机制补偿。

### 方案 B：先说话人分离，再声纹锁定

在方案 A 基础上增加说话人分离（diarization）：

- 降噪：`DeepFilterNet` 或 `RNNoise`
- VAD：`silero-vad`
- 说话人分离：`pyannote.audio` 本地版 或 ECAPA 聚类
- 目标说话人过滤：diarization 后只保留目标说话人簇

- **效果**：预计过滤 50–70%，对多人对话最干净。
- **成本**：模型体积数百 MB，显存/内存占用高，首帧延迟大；工程复杂度高。
- **建议**：作为二期扩展，待方案 A 稳定后再引入。

### 方案 C：云端 API 预处理（不推荐）

将降噪 / VAD / diarization 全部走云端 API。

- **效果**：精度最高，开发最快。
- **成本**：按音频时长计费；录音需上传，与项目“优先本地处理，保护录音隐私”约束冲突。

## 4. 架构概览

```text
输入音频
  │
  ▼
┌─────────────────┐
│  降噪模块        │  noisereduce / RNNoise（可配置）
│  src/preprocessor│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  VAD 模块        │  silero-vad（可配置）
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  切分模块        │  自然停顿 / 最大时长强制切分
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  目标说话人过滤  │  声纹比对，低置信度标记待纠偏
│  src/diarization │
└────────┬────────┘
         │
         ▼
有效 Segment 列表  →  下游转写 / 文本分析 / 情感 / 正音
```

## 5. 模块变更计划

### 5.1 改造 `src/preprocessor.py`

- 新增 `_denoise_nr(y)`：基于 `noisereduce` 的谱门控降噪。
- 新增 `_vad_silero(y, sr)`：基于 `silero-vad` 的语音活动检测。
- 保留现有 `_denoise` 与 `_vad` 作为降级实现。
- `process(path)` 根据配置选择降噪/VAD 实现，输出 `list[Segment]`。
- 每个 `Segment` 新增元数据字段（见 5.3）。

### 5.2 新增 `src/segment_filter.py`（可选，推荐）

封装有效片段判断逻辑：

- `filter_target_speaker(segments, enroll_embedding, threshold)`：只保留声纹相似度高于阈值的片段。
- `mark_low_confidence(segments, threshold)`：低置信度片段打上 `needs_review` 标签，供报告纠偏入口使用。

### 5.3 扩展 `src/types.py`

```python
@dataclass
class Segment:
    start: float
    end: float
    vad_confidence: float = 1.0
    speaker_label: str | None = None
    speaker_confidence: float | None = None
    needs_review: bool = False
```

### 5.4 改造 `src/diarization.py`

- 新增 `filter_segments_by_voiceprint(segments, audio, enroll_embedding)`：
  - 对输入的 `Segment` 列表逐段提取嵌入。
  - 与注册声纹比对，保留目标说话人片段。
  - 低置信度片段标记 `needs_review=True`。
- 与 `Preprocessor` 联动：`Pipeline` 先调用 `Preprocessor.process`，再调用 `Diarization.filter_segments_by_voiceprint`。

### 5.5 配置变更

`config.yaml` 新增 `preprocessing` 段：

```yaml
preprocessing:
  denoise:
    backend: noisereduce  # noisereduce | rnnoise | spectral
    noise_sample_sec: 0.1  # 仅 spectral 使用
  vad:
    backend: silero       # silero | energy
    min_speech_duration_ms: 250
    max_silence_duration_ms: 500
    threshold: 0.5        # silero 置信度阈值
  segmentation:
    target_sample_rate: 16000
    min_segment_duration_sec: 1.0
    max_segment_duration_sec: 30.0
  speaker_filter:
    enabled: true
    similarity_threshold: 0.70
    low_confidence_threshold: 0.55
```

## 6. 接口约束

- 保持 `Segment` 在 `src/types.py` 中的核心字段 `start`、`end` 不变，新增字段均有默认值，向后兼容。
- `Preprocessor.process(path)` 签名不变。
- `Diarization` 对外新增方法，不破坏现有方法。
- CLI 命令 `register`、`analyze`、`watch`、`correct` 行为不变。

## 7. 验收标准

- [ ] `src/preprocessor.py` 支持 `noisereduce` / `RNNoise` / 谱减法三种降噪后端，可配置切换。
- [ ] `src/preprocessor.py` 支持 `silero-vad` / 能量 VAD 两种 VAD 后端，可配置切换。
- [ ] `config.yaml` 新增 `preprocessing` 段，覆盖降噪、VAD、切分、说话人过滤阈值。
- [ ] `src/types.py` 的 `Segment` 新增 `vad_confidence`、`speaker_label`、`speaker_confidence`、`needs_review` 字段。
- [ ] `src/diarization.py` 新增按声纹过滤 Segment 的能力，并标记低置信度片段。
- [ ] 新增/更新单元测试，覆盖降噪/VAD 后端切换、说话人过滤、降级路径。
- [ ] 使用示例录音验证：有效片段过滤后，下游转写 token 显著减少（量化指标写入测试或文档）。
- [ ] README 更新预处理配置说明与模型下载/隐私提示。

## 8. 未来扩展

- 引入 `pyannote.audio` 本地 diarization（方案 B），进一步提升多人场景过滤精度。
- 支持根据录音环境自动估计噪声样本（而非固定前 100ms）。
- 增加“片段质量评分”维度（信噪比、混响、重叠度），供下游选择是否送入大模型。
