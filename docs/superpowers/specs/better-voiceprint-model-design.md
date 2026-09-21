# 声纹模型升级设计文档（ECAPA-TDNN）

## 1. 背景与问题

当前 `src/embeddings.py` 的说话人嵌入提取链为：Model API Gateway → speechbrain ECAPA → pyannote → 本地 MFCC 回退。实测现状：

- **speechbrain 路径失效**：代码使用已弃用的 `speechbrain.pretrained` 导入路径，在 speechbrain 1.1.0 上触发 `speechbrain.integrations.k2_fsa` 懒加载失败（k2_fsa 未安装）；且默认 `LocalStrategy.SYMLINK` 在 Windows 无特权时抛 WinError 1314。
- **pyannote 路径失效**：`pyannote/embedding` 为 HF 门控仓库，未授权（401）。
- **实际全部回退 MFCC**：MFCC 均值/方差统计特征区分说话人能力弱——同人/异人相似度都挤在 0.75+，现有阈值 0.75 基本失去筛选力。
- **torchcodec DLL 损坏**：`torchaudio.load` 加载 m4a 失败（libtorchcodec_core4.dll 无法加载），需改用 librosa 加载后转 tensor。

## 2. 实测证据（2026-08-19，本机 CPU）

用 `speechbrain.inference.speaker.EncoderClassifier`（`spkrec-ecapa-voxceleb`，192 维）验证：

| 场景 | ECAPA 余弦相似度 | MFCC 现状 |
|---|---|---|
| 同一人 中文 3s 块 × 英文 3s 块 | 0.48–0.79（典型 0.6–0.7） | 无区分力 |
| 同文件有效语音块两两 | 0.73–0.86 | — |
| 静音/开头噪声块 vs 有效语音 | ≈ 0（-0.1–0.1） | — |
| 整段嵌入（含开头静音污染） vs 有效块 | **-0.06**（被污染） | — |
| 模型加载（缓存命中后） | 2.9s | — |
| 单块推理（3s 音频） | <1s | — |

关键发现：

1. ECAPA 区分力充分：同人（跨语言）≥0.48，静音/异人 ≈0，中间带清晰。
2. **声纹样本开头存在静音/噪声**，整段嵌入会被拉偏（自相似 -0.06）→ 注册必须先做有效语音检测与裁剪。
3. 现有阈值 0.75 对 ECAPA 过高（同人典型 0.6–0.7 会被误判为 other）。

## 3. 方案（已确认决策）

- **D1 模型**：修复并启用 speechbrain ECAPA-TDNN（`spkrec-ecapa-voxceleb`），保持 API Gateway → ECAPA → MFCC 回退链不变。
- **D2 注册策略**：分块 + VAD 裁剪。注册音频先用能量门限跳过静音，取有效语音 3s 块的嵌入均值（归一化）作为声纹中心。
- **D3 阈值校准**：按实测分布校准——`similarity_threshold: 0.40`、`low_confidence_threshold: 0.25`（同人下界 0.48 留余量；静音/异人 ≈0）。

## 4. 架构

```text
input/voiceprint/*.m4a
  │ librosa 加载 (16kHz mono, 替代 torchaudio.load)
  ▼
能量 VAD 裁剪（跳过开头/尾部静音）
  │
  ▼ 3s 滑窗分块（仅有效语音）
┌──────────────────────────┐
│ ECAPA-TDNN (speechbrain) │ ← speechbrain.inference.speaker
│ LocalStrategy.COPY       │ ← Windows 兼容
└───────────┬──────────────┘
            ▼ 块嵌入均值 + L2 归一化
embedding.pkl（声纹中心）+ meta.json
            │
enhanced/seg_*.wav → 滑动窗口嵌入 → 余弦比对(阈值 0.40/0.25) → user/other/unknown
```

## 5. 变更清单

### 5.1 `src/embeddings.py`

- ECAPA 导入路径改为 `speechbrain.inference.speaker`（保留 `speechbrain.pretrained` 旧路径兜底，兼容旧版本）。
- `from_hparams` 增加 `local_strategy=LocalStrategy.COPY`（Windows symlink 权限规避）。
- 音频加载改为 librosa（绕过 torchcodec DLL 问题），16kHz 单声道后转 torch tensor。
- 新增模块级 ECAPA 惰性单例（避免每片段重复加载 2.9s）。
- `extract_embedding_from_array` 增加 ECAPA 路径：数组 → tensor → `encode_batch`（当前该函数只走 MFCC，`split_by_voiceprint` 全靠它，这是分离质量的关键）。
- 新增 `extract_speaker_center(paths, config)`：能量 VAD 裁剪 + 3s 分块 + 块均值归一化。

### 5.2 `src/enrollment.py`

- `enroll` 支持多文件注册：传入目录或多个路径时用 `extract_speaker_center`；单文件保持旧整段逻辑兼容（现有测试依赖单文件签名）。
- 落盘的 voiceprint dict 增加 `model: "ecapa"` 标记与块数元信息。

### 5.3 `config.yaml`

- `speaker.similarity_threshold: 0.75 → 0.40`
- `speaker.low_confidence_threshold: 0.55 → 0.25`
- `preprocessing.speaker_filter` 两项同步。
- 新增 `speaker.enroll_chunk_sec: 3.0`、`speaker.enroll_vad_energy_db: 40`（能量门限，低于峰值该分贝值的块视为静音）。

### 5.4 `scripts/separate_enhanced.py`

- 注册改用 `EnrollmentManager` 多文件入口（走 ECAPA 中心），分离流程不变。

## 6. 验收标准

1. `extract_embedding('input/voiceprint/声纹.m4a')` 返回 192 维嵌入，非零维度 > 100（真实模型而非 MFCC 的 40 维）。
2. 重新注册后，`声纹.m4a` 与 `英文声纹.m4a` 有效语音块对声纹中心的相似度 ≥ 0.40（user 判定）。
3. `enhanced/seg_000.wav`（此前判定 user）窗口相似度 ≥ 0.40；存在明显他人语音的片段（seg_011 等）能分出 user/other 两类。
4. 现有 pytest 全量通过（`tests/`）。
5. 分离导出流程 `scripts/separate_enhanced.py` 端到端跑通。

## 7. 风险与回退

- **风险**：ECAPA 首次运行需下载模型（~85MB，已缓存到 `tmp/spkrec-ecapa-voxceleb`）；推理比 MFCC 慢（每 3s 窗 <1s，577s 语音全量分离预计 <10 分钟）。
- **回退**：ECAPA 任一环节失败自动落回 pyannote → MFCC，行为与升级前一致；阈值配置仅影响判别边界，MFCC 回退下略保守但不破坏流程。
