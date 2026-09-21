# 声纹测试与说话人分离设计文档

## 1. 背景与目标

用户希望：

1. **测试声纹识别模块**：从 `input/voiceprint/` 中的声纹文件提取嵌入，验证 `EnrollmentManager` 与 `extract_embedding` 的稳定性。
2. **进一步分割预处理结果**：`output/preprocessed/` 中已有的片段是按 VAD 与最大时长切分后的结果，但在多人或长段语音中仍可能包含多个说话人。
3. **实现说话人分离**：基于已注册声纹，对预处理片段再做一次“滑动窗口二次切分 + 声纹比对”，将目标说话人与非目标说话人分离，只保留目标说话人片段。

## 2. 设计原则

- **本地优先**：继续复用 `extract_embedding` 的本地 MFCC / speechbrain / pyannote 回退链。
- **可降级**：重型模型不可用时，使用 MFCC 统计特征仍可跑通测试。
- **可观测**：每个片段保留 `speaker_label`、`speaker_confidence`、`needs_review` 元数据。
- **不破坏既有接口**：`DiarizationModule` 新增方法，不修改现有 `identify_user` / `filter_segments_by_voiceprint` 签名。

## 3. 方案选型

### 方案 A：基于注册声纹的二次切分与筛选（本期）

- 对 `output/preprocessed/` 中的每个片段，按滑动窗口进一步切分（例如 2–5 秒）。
- 对每个子窗口提取嵌入，与注册声纹比余弦相似度。
- 根据相似度阈值把子窗口标记为 `user` / `other` / `needs_review`。
- 合并连续同标签子窗口，生成最终的目标说话人片段。

- **效果**：在已有预处理基础上进一步提纯目标说话人，工程改动小。
- **成本**：无新增依赖，CPU 可跑。

### 方案 B：无监督说话人聚类（二期）

- 不依赖注册声纹，对所有片段做嵌入聚类（k-means / 谱聚类）。
- 需要预先知道说话人数目或启发式估计。
- **成本**：需要更多样本来稳定聚类，本期不采用。

## 4. 架构概览

```text
input/voiceprint/声纹.wav
  │
  ▼
┌─────────────────────────┐
│ EnrollmentManager.enroll │  提取并保存 embedding.pkl + meta.json
│  src/enrollment.py       │
└───────────┬─────────────┘
            │
            ▼
   注册声纹 embedding
            │
            ▼
output/preprocessed/segment_*.wav
  │
  ▼
┌────────────────────────────────────┐
│ DiarizationModule.split_by_voiceprint│  滑动窗口二次切分 + 声纹比对
│  src/diarization.py                 │
└───────────┬────────────────────────┘
            │
            ▼
   目标说话人片段（user）
   非目标说话人片段（other）
   低置信度片段（needs_review）
```

## 5. 模块变更计划

### 5.1 新增 `tests/test_voiceprint_extraction.py`

- 测试 `EnrollmentManager.enroll` 能从 `input/voiceprint/声纹.wav` 正常提取并保存声纹。
- 测试 `extract_embedding` 对常见音频格式（wav/m4a）返回非零向量。
- 测试声纹文件缺失时给出明确错误。

### 5.2 扩展 `src/diarization.py`

- 新增 `split_by_voiceprint(segments, audio_path, voiceprint, window_sec=3.0, hop_sec=1.5)`：
  - 对每个长片段按滑动窗口二次切分。
  - 对每个窗口提取嵌入并计算与注册声纹的相似度。
  - 根据阈值标记标签。
  - 合并连续同说话人窗口，返回新的 `Segment` 列表。
- 新增辅助方法 `_merge_same_speaker_windows(windows)`：合并连续同标签窗口。

### 5.3 新增 `tests/test_voiceprint_split.py`

- 使用模拟嵌入验证窗口切分逻辑。
- 验证合并后片段时间不重叠、连续。
- 验证低置信度窗口标记 `needs_review`。

### 5.4 新增可执行脚本/命令

- 在 `src/cli.py` 或独立脚本中新增 `test-voiceprint` 入口，便于用户一键运行：
  - 提取 `input/voiceprint/` 声纹。
  - 对 `output/preprocessed/` 片段跑二次分割。
  - 输出统计报告（总片段数、目标说话人片段数、待复核片段数）。

## 6. 接口约束

- `Segment` 核心字段不变。
- `DiarizationModule` 现有方法签名不变。
- `EnrollmentManager` 现有方法签名不变。
- `extract_embedding` 行为不变。

## 7. 验收标准

- [ ] 新增 `tests/test_voiceprint_extraction.py` 并通过。
- [ ] 新增 `tests/test_voiceprint_split.py` 并通过。
- [ ] `src/diarization.py` 新增 `split_by_voiceprint` 方法，能对预处理片段二次分割。
- [ ] 使用 `input/voiceprint/` 中的真实声纹文件可成功提取并保存声纹。
- [ ] 对 `output/preprocessed/` 中的片段运行分割后，生成带 `speaker_label` 的新片段列表。
- [ ] 输出统计报告，包含 user/other/needs_review 数量。
- [ ] README 或测试文档说明如何运行声纹测试。

## 8. 风险与回退

- 重型 embedding 模型（speechbrain/pyannote）未安装时，MFCC 特征区分度有限，可能导致相似度绝对值偏低；通过阈值可配置 + `needs_review` 标记缓解。
- 输入音频过短或静音时，嵌入可能为零向量，已有零向量安全处理。
