# 任务清单：声纹模型升级

## 设计阶段

- [x] 编写设计文档 `docs/superpowers/specs/better-voiceprint-model-design.md`
- [x] 用户确认三项决策（ECAPA 修复启用 / VAD 分块注册 / 阈值 0.40-0.25）
- [x] archify 数据流图（`better-voiceprint-model-architecture.html/.json`）

## 实现阶段

- [x] Task 1: `src/embeddings.py` — ECAPA 导入修复（`speechbrain.inference.speaker`）+ `LocalStrategy.COPY` + librosa 加载 + 模块级单例
- [x] Task 2: `src/embeddings.py` — `extract_speaker_center` 能量 VAD 裁剪 + 3s 分块均值 + L2 归一化
- [x] Task 3: `src/enrollment.py` — `enroll`/`enroll_multi` 多文件注册，落盘 `model` 与 `chunk_count`
- [x] Task 4: `config.yaml` — 阈值校准 0.40/0.25，新增 `enroll_chunk_sec`/`enroll_vad_energy_db`
- [x] Task 5: `scripts/separate_enhanced.py` — 注册入口切换 `enroll_multi`
- [x] Task 6（用户 build 阶段追加）: `src/diarization.py` — 修复分离输出重叠：run 聚合 + 重叠区中点切界 + 满长尾窗 + 标签平滑
- [x] Task 7（用户 build 阶段追加）: `scripts/preprocess_audio.py` — 预处理按时间排序导出 + 时间戳文件名 + meta.json 源信息；导出脚本清空旧产物
- [x] 新增/更新单元测试（`tests/test_voiceprint_split.py` 等，全量 70 通过）

## 验证阶段

- [x] `pytest tests/` 全量通过（70 passed）
- [x] 真实音频端到端：seg_000 分离输出有序、连续、无重叠（12 碎片段 → 5 段）
- [x] 真实音频端到端：预处理导出文件名排序 == 时间顺序
- [x] 2026-08-20 清除旧测试产物后对 test1/test2/test3 全新跑批（output/01_preprocessed + output/02_separated，含 README.md 记录；新增 scripts/separate_test_data.py 按录音分组批处理分离）
- [ ] 用户对最终分离/预处理产物人工抽听确认
