# OpenSpec Delta: 声纹模型升级（ECAPA-TDNN）

## 变更范围

修复并启用 speechbrain ECAPA-TDNN 说话人嵌入，替换当前实际生效的 MFCC 回退：

- 修复 speechbrain 1.1.0 上的导入路径失效（`speechbrain.pretrained` → `speechbrain.inference.speaker`）。
- 修复 Windows 无特权时 `LocalStrategy.SYMLINK` 失败（改用 COPY）。
- 绕过损坏的 torchcodec DLL（音频加载改用 librosa）。
- 声纹注册增加能量 VAD 裁剪 + 3s 分块取均值（消除开头静音污染）。
- 相似度阈值按 ECAPA 实测分布校准（0.75/0.55 → 0.40/0.25）。

## 新增/修改的规格

### S1: 嵌入提取（`src/embeddings.py`）

- `extract_embedding` 与 `extract_embedding_from_array` 优先走 ECAPA（文件与数组两条路径），失败回退 pyannote → MFCC，链路顺序不变。
- ECAPA 分类器模块级惰性单例，避免每片段重复加载。
- 新增 `extract_speaker_center(paths, config)`：
  - 能量门限裁剪：块 RMS 低于（全局峰值 - `enroll_vad_energy_db` dB）的窗口视为静音并跳过。
  - 有效语音按 `enroll_chunk_sec`（默认 3s）分块，块嵌入均值 + L2 归一化为声纹中心。

### S2: 注册（`src/enrollment.py`）

- `enroll` 接受单文件（兼容旧行为与现有测试）或目录/多文件（走 `extract_speaker_center`）。
- voiceprint dict 新增 `model: "ecapa"` 与 `chunk_count` 元信息。

### S3: 配置（`config.yaml`）

- `speaker.similarity_threshold`: 0.75 → 0.40
- `speaker.low_confidence_threshold`: 0.55 → 0.25
- `preprocessing.speaker_filter.similarity_threshold` / `low_confidence_threshold` 同步。
- 新增 `speaker.enroll_chunk_sec: 3.0`、`speaker.enroll_vad_energy_db: 40`。

### S4: 分离脚本（`scripts/separate_enhanced.py`）

- 注册改走 `EnrollmentManager` 多文件入口；分离流程（滑动窗口 + 阈值标记 + 导出）不变。

### S5: 分离输出无重叠（build 阶段用户追加）

- `_merge_same_speaker_windows`：连续同标签窗口聚合为 run（`needs_review` 传播到整个 run），
  相邻 run 的重叠区以中点切开；输出片段严格按时间排序、连续且互不重叠。
- `split_by_voiceprint` 切窗：输入片段先按时间排序；尾窗回退补足整窗长度；不足半秒的片段跳过。
- `_smooth_window_labels`：左右相邻窗口标签一致时消除孤立单窗口翻转。
- 导出前清空输出目录，避免多次运行的旧片段混入。

### S6: 预处理导出顺序保障（build 阶段用户追加）

- 新增 `scripts/preprocess_audio.py`：单一录音 → 降噪/VAD → 按 `(start, end)` 排序导出；
  文件名 `seg_{idx:03d}_{start:07.2f}-{end:07.2f}s.wav`，文件名排序即时间顺序。
- `segments.json` 记录每个片段时间戳；`meta.json` 记录源文件路径与时长。
- `src/preprocessor.py` 新增 `load_denoised()`，导出与 `process` 复用同一降噪结果。
- `test_voiceprint.py` 在切片前校验 meta 记录的来源与实际音频是否一致。

## 验收标准

1. `extract_embedding('input/voiceprint/声纹.m4a')` 返回 192 维、非零维度 > 100。
2. 多文件注册后，两个声纹样本有效语音块对中心的相似度 ≥ 0.40。
3. `enhanced/seg_000.wav` 判定为 user；含他人语音片段能分出 user/other。
4. `tests/` 全量通过。
5. `scripts/separate_enhanced.py` 端到端跑通并导出分离音频。
6. 分离输出任意相邻片段互不重叠（重叠对数 = 0），user/other/unknown 目录的时间范围互斥。
7. 预处理导出片段按时间有序，文件名排序与时间顺序一致，meta.json 可溯源到源录音。
