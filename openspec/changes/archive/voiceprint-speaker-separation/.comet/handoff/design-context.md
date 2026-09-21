# Design Context: voiceprint-speaker-separation

## Goal
测试声纹识别模块，从声纹文件提取声纹，对预处理的测试结果进一步分割，实现说话人分离。

## Key Artifacts
- Design Doc: docs/superpowers/specs/voiceprint-speaker-separation-design.md
- Delta Spec: openspec/changes/voiceprint-speaker-separation/specs/voiceprint-speaker-separation/spec.md
- Proposal: openspec/changes/voiceprint-speaker-separation/proposal.md

## Modules
- src/enrollment.py
- src/diarization.py
- src/embeddings.py
- src/types.py

## Test Data
- input/voiceprint/声纹.wav
- output/preprocessed/segment_*.wav
