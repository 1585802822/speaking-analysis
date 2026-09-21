# 声纹模型升级实施计划

## 目标

修复并启用 speechbrain ECAPA-TDNN 说话人嵌入，替换实际生效的 MFCC 回退；注册增加 VAD 裁剪分块；阈值按实测校准。

## 任务列表

### Task 1: `src/embeddings.py` — ECAPA 修复与增强

1. 新增 `_get_ecapa_classifier(config)` 模块级惰性单例：
   - 导入 `speechbrain.inference.speaker.EncoderClassifier`（失败时回退旧路径 `speechbrain.pretrained`）。
   - `from_hparams(..., local_strategy=LocalStrategy.COPY)`。
   - 加载后清理 `sys.modules` 中的 DeprecatedModuleRedirect/LazyModule 代理（沿用现有 `_cleanup_broken_speechbrain_imports`）。
2. 新增 `_ecapa_embed_array(y, sr, classifier)`：数组 → `torch.from_numpy(...).unsqueeze(0).float()` → `encode_batch` → squeeze → numpy。
3. `extract_embedding_from_array`：ECAPA 优先（经单例），失败回退 MFCC（现有行为）。
4. `extract_embedding` 文件路径版：保留 API Gateway 优先；speechbrain 分支改用 librosa 加载（绕过 torchcodec）+ 单例 + COPY 策略；pyannote/MFCC 回退不变。
5. 新增 `extract_speaker_center(audio_paths, config)`：
   - librosa 加载每个文件（16kHz mono）。
   - 能量 VAD：按帧（帧长 = chunk_sec/3）计算 RMS，低于（全局峰值 dB - `enroll_vad_energy_db`）的帧判为静音；仅保留连续有效语音区间。
   - 按 `enroll_chunk_sec` 切 3s 块（不足 1.5s 的尾块丢弃）。
   - 块嵌入均值 → L2 归一化 → 返回 (center, chunk_count, model_name)。

### Task 2: `src/enrollment.py` — 多文件注册

1. `enroll(audio_path)`：单文件保持现有整段逻辑（兼容测试），但落盘 dict 增加 `model` 与 `chunk_count` 字段。
2. 新增 `enroll_multi(audio_paths)`：调用 `extract_speaker_center`，落盘 voiceprint 与 meta（samples 记录全部文件）。

### Task 3: `config.yaml` — 阈值与新参数

1. `speaker.similarity_threshold: 0.40`、`speaker.low_confidence_threshold: 0.25`。
2. `preprocessing.speaker_filter.similarity_threshold: 0.40`、`low_confidence_threshold: 0.25`。
3. 新增 `speaker.enroll_chunk_sec: 3.0`、`speaker.enroll_vad_energy_db: 40`。

### Task 4: `scripts/separate_enhanced.py` — 注册入口切换

1. `reenroll_voiceprint` 改用 `EnrollmentManager.enroll_multi`（或直接 `extract_speaker_center`），meta 记录块数。
2. 分离流程不变。

### Task 5: 验证

1. 单元验证：`extract_embedding` 返回 192 维、非零 >100；`extract_speaker_center` 块数 ≥2/文件。
2. `pytest tests/` 全量通过。
3. 端到端：重跑 `scripts/separate_enhanced.py`，确认 seg_000 判 user、混合片段分出 user/other。

### Task 6: 修复分离输出重叠（build 阶段用户追加，2026-08-19）

用户反馈：说话人分离后音频有重合，不同说话人未分开。根因：滑窗 hop(1.5s) < window(3s)，
`_merge_same_speaker_windows` 直接按窗口端点拼接，相邻说话人 run 共享重叠区音频；
且连续 unknown(needs_review) 窗口不合并导致碎片化；过短尾窗嵌入失真导致标签抖动。

1. `src/diarization.py` `_merge_same_speaker_windows`：同标签窗口聚合为 run（needs_review
   传播），相邻 run 重叠区以中点切开，输出严格有序、连续、互不重叠。
2. `split_by_voiceprint` 切窗：片段先按时间排序；尾窗回退补足整窗（≥3s），不足半秒片段跳过。
3. 新增 `_smooth_window_labels`：左右邻居一致时消除孤立单窗口标签翻转。
4. 导出脚本（separate_enhanced.py / test_voiceprint.py）：导出前清空输出目录（防旧片段混入），
   片段按时间排序，文件名带时间戳。

### Task 7: 预处理导出顺序保障（build 阶段用户追加，2026-08-19）

用户反馈：预处理后音频顺序错乱。根因：旧导出为临时脚本（未入库），文件名无时间戳、
元数据不记源文件，且现有 segments.json 时间戳来自 5670s 录音(20260727-090126.wav)而
下游按 20260731-112120.wav(4638s) 切片，源与时间戳错配。

1. 新增 `scripts/preprocess_audio.py`：单一录音 → 降噪/VAD → 按 (start,end) 排序导出，
   文件名 `seg_{idx:03d}_{start:07.2f}-{end:07.2f}s.wav`（文件名排序即时间顺序），
   segments.json 记录每片段时间戳，meta.json 记录源文件与时长（来源可校验）。
2. `src/preprocessor.py` 新增 `load_denoised()` 公共方法，导出与 process 复用同一降噪结果。
3. `test_voiceprint.py` 增加源文件一致性校验：meta.json 记录的来源与实际音频不一致时告警。

## 风险与回退

- ECAPA 不可用时全链自动回退（行为同升级前）。
- 阈值变更影响 MFCC 回退路径的判定边界（可接受，见设计文档 §7）。
