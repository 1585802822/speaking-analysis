# 声纹测试与说话人分离规格

## 概述

本变更在现有说话人过滤能力基础上，增加声纹提取的端到端测试，并对预处理后的长片段进行二次切分，实现基于注册声纹的说话人分离。

## 规格项

### S1: 声纹提取测试

- 输入：`input/voiceprint/` 目录下的声纹音频文件（`声纹.wav`、`声纹.m4a`、`英文声纹.m4a`）。
- 处理：`EnrollmentManager.enroll(audio_path)` 调用 `extract_embedding` 提取嵌入。
- 输出：`voiceprint_dir/embedding.pkl` 与 `voiceprint_dir/meta.json`。
- 要求：
  - 对存在的音频文件返回非零归一化嵌入。
  - 对缺失文件抛出 `FileNotFoundError`。
  - 元数据文件 `meta.json` 中 `enrolled` 为 `true`。

### S2: 滑动窗口二次切分

- 输入：`list[Segment]`（来自 `output/preprocessed/`）+ 原始音频路径 + 注册声纹。
- 参数：
  - `window_sec`: 子窗口时长，默认 3.0 秒。
  - `hop_sec`: 滑动步长，默认 1.5 秒。
- 处理：
  - 对每个 Segment 按滑动窗口生成子窗口。
  - 对每个子窗口提取嵌入并计算余弦相似度。
  - 相似度 ≥ `similarity_threshold` 标记为 `user`。
  - 相似度 < `similarity_threshold` 且 ≥ `low_confidence_threshold` 标记为 `other`。
  - 相似度 < `low_confidence_threshold` 标记为 `unknown` 并设置 `needs_review=True`。
- 输出：合并后的 `list[Segment]`，每个 Segment 携带 `speaker_label`、`speaker_confidence`、`needs_review`。

### S3: 合并策略

- 相邻子窗口标签相同时合并为一个 Segment。
- 合并后的 Segment 时间范围连续、不重叠。
- 合并后的 `speaker_confidence` 按时长加权平均。

### S4: 统计输出

- 运行后输出或返回统计信息：
  - 总窗口数
  - 目标说话人窗口数（user）
  - 非目标说话人窗口数（other）
  - 待复核窗口数（needs_review）

## 验收标准

- `tests/test_voiceprint_extraction.py` 全部通过。
- `tests/test_voiceprint_split.py` 全部通过。
- `split_by_voiceprint` 在示例片段上运行不报错。
- 输出统计信息准确。
