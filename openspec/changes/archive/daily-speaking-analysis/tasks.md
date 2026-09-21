:phase: build
:plan: docs/superpowers/plans/plan.md

# 任务清单：日常录音分析工具

## 待办

- [ ] T13: 端到端集成测试（待真实音频/模型环境验证）

## 进行中

- [ ] T2: 文件夹监控（骨架完成，待真实音频验证）
- [ ] T3: 音频预处理（VAD/降噪/切分逻辑已实现，待真实音频验证）
- [ ] T7: 文本分析（规则已实现，待真实 ASR 输入验证）
- [ ] T8: 音频特征分析（语速/停顿/音量/清晰度已实现，待真实音频验证）
- [ ] T11: 报告生成（Markdown/JSON 已实现，待真实数据验证）

## 已完成

- [x] Design Node：完成架构设计、生成架构图、编写设计文档与 OpenSpec delta spec
- [x] T1: 项目骨架与配置（config.yaml、requirements.txt、CLI、目录结构、模块接口）
- [x] Plan Node：制定 13 项任务实施计划
- [x] Execute Node 首轮：实现核心骨架与无模型依赖模块
- [x] T4: 声纹注册（ EnrollmentManager + speechbrain/pyannote 回退 MFCC 实现）
- [x] T5: 说话人分离与匹配（DiarizationModule 余弦相似度筛选 + 低置信度标记）
- [x] T6: ASR 转写（faster-whisper 集成 + 占位降级）
- [x] T9: 情感/语气分析（emotion2vec 占位 + librosa 韵律特征回退）
- [x] T10: 发音标准/正音分析（pypinyin + phonemizer 集成 + 低置信度提示）
- [x] T12: 声纹纠偏闭环（report/corrections.json + CLI correct 命令 + 增量更新）
