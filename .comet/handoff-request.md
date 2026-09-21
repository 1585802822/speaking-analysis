# Subagent Handoff Request: 日常录音分析工具

## 当前状态

已完成项目骨架、CLI、配置、音频预处理、文本分析、音频特征分析、报告生成。以下模块仍为占位实现，需要接入真实模型或补全逻辑：

1. **声纹注册与识别** (`src/enrollment.py`, `src/diarization.py`)
   - 使用 speechbrain 或 pyannote.audio 提取声纹嵌入。
   - diarization 后计算与注册声纹的余弦相似度，筛选用户语音。
   - 支持增量更新（正面/负面样本）。

2. **ASR 转写** (`src/transcriber.py`)
   - 接入 faster-whisper 本地模型。
   - 支持中英混合、词/句级时间戳。
   - 按用户语音片段裁剪后转写。

3. **情感/语气分析** (`src/emotion_analyzer.py`)
   - 接入 emotion2vec 或类似本地模型。
   - 输出情绪标签和语气起伏描述。

4. **发音标准/正音分析** (`src/pronunciation_analyzer.py`)
   - 中文：使用 pypinyin 检测声调/韵母疑似偏差。
   - 英文：使用 phonemizer + ASR 音素对齐检测音素问题。
   - 给出练习建议。

5. **声纹纠偏闭环**
   - 在 Markdown 报告中为低置信度片段添加确认/否认入口。
   - 实现确认后的增量更新。

6. **端到端测试**
   - 准备示例录音或生成合成音频。
   - 验证完整流水线输出符合预期。

## 约束

- 保持现有接口和类型定义（`src/types.py`）。
- 所有音频与声纹数据本地处理，不上传云端。
- 代码需与现有 CLI、Pipeline、Reporter 兼容。
- 如果当前环境无法安装/运行重型模型，至少写出完整集成代码并标注 TODO。

## 期望产物

- 更新的 `src/*.py` 文件。
- 补充的测试文件。
- 简短实现摘要和未验证项说明。
