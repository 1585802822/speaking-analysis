# OpenSpec Delta: 声纹测试与说话人分离

## 变更范围

为本项目增加声纹提取的端到端测试，并在现有 `DiarizationModule` 基础上扩展“滑动窗口二次切分 + 声纹比对”能力，实现对预处理片段的说话人分离。

## 新增/修改的规格

### S1: 声纹提取测试

- 新增 `tests/test_voiceprint_extraction.py`：
  - 测试 `EnrollmentManager.enroll(audio_path)` 能从 `input/voiceprint/声纹.wav` 提取并保存 `embedding.pkl` + `meta.json`。
  - 测试 `extract_embedding` 对 wav、m4a 返回非零归一化向量。
  - 测试缺失文件时抛出 `FileNotFoundError`。

### S2: 滑动窗口二次切分

- 扩展 `src/diarization.py` 新增 `split_by_voiceprint(segments, audio_path, voiceprint, window_sec=3.0, hop_sec=1.5)`：
  - 对每个输入 `Segment` 按滑动窗口生成子窗口。
  - 对每个子窗口提取嵌入（复用 `_extract_segment_embedding`）。
  - 计算与注册声纹的余弦相似度。
  - 根据 `similarity_threshold` 与 `low_confidence_threshold` 标记 `speaker_label` 与 `needs_review`。
  - 合并连续同标签子窗口，返回新的 `Segment` 列表。

### S3: 合并策略

- 新增辅助方法 `_merge_same_speaker_windows(windows)`：
  - 输入为带标签的子窗口列表（每个窗口含 `start`、`end`、`speaker_label`、`speaker_confidence`）。
  - 相邻窗口标签相同时合并，置信度取加权平均（按时长加权）。
  - 输出连续、不重叠的 `Segment` 列表。

### S4: 统计与可观测

- `split_by_voiceprint` 返回的每个 `Segment` 携带：
  - `speaker_label`: `"user"` / `"other"` / `"unknown"`
  - `speaker_confidence`: 余弦相似度
  - `needs_review`: 低于低置信度阈值时为 `True`
- 新增独立脚本/CLI 入口，输出统计：
  - 总窗口数、目标说话人窗口数、非目标说话人窗口数、待复核窗口数。

### S5: 接口约束

- `DiarizationModule` 现有方法签名不变。
- `EnrollmentManager` 与 `extract_embedding` 行为不变。
- `Segment` 核心字段不变，仅使用已有扩展字段。

## 验收标准

- [ ] `tests/test_voiceprint_extraction.py` 通过。
- [ ] `tests/test_voiceprint_split.py` 通过。
- [ ] `src/diarization.py` 新增 `split_by_voiceprint` 并能在示例片段上运行。
- [ ] 对 `input/voiceprint/` 中真实声纹文件提取成功。
- [ ] 对 `output/preprocessed/` 中片段运行后可输出 user/other/needs_review 统计。
- [ ] README 或测试文档说明如何运行声纹测试。

## 依赖

- 复用现有 `librosa`、`numpy` 依赖。
- 可选依赖 `speechbrain`、`pyannote.audio`、`torch` 若已安装则自动使用，否则回退 MFCC。

## 未来扩展

- 引入无监督说话人聚类，支持未知说话人数目场景。
- 支持按说话人输出独立音频文件。
