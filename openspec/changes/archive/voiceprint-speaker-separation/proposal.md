# 变更提案：声纹测试与说话人分离

## 目标

1. 测试声纹识别模块：从 `input/voiceprint/` 中的声纹文件提取嵌入，验证 `EnrollmentManager` 与 `extract_embedding` 的稳定性。
2. 进一步分割预处理结果：对 `output/preprocessed/` 中已有的 VAD 片段按滑动窗口二次切分。
3. 实现说话人分离：基于注册声纹比对，把目标说话人片段与非目标说话人片段分开。

## 背景

当前 `src/diarization.py` 已支持按声纹过滤片段，但缺少：

- 针对真实声纹文件的端到端提取测试。
- 对长片段的二次切分能力，导致一个片段内可能混合多个说话人。
- 一键运行声纹测试与分离的命令入口。

## 预期收益

- 声纹提取流程有自动化测试覆盖，避免回归。
- 预处理后的片段经过二次分割，目标说话人纯度更高。
- 为后续完整 diarization 功能奠定基础。

## 范围

- 新增 `tests/test_voiceprint_extraction.py` 测试声纹提取。
- 扩展 `src/diarization.py` 新增 `split_by_voiceprint` 方法。
- 新增 `tests/test_voiceprint_split.py` 测试二次切分逻辑。
- 新增 CLI/脚本入口，便于用户一键测试声纹并查看分离统计。

## 非目标

- 本期不引入无监督聚类说话人分离（diarization）。
- 不上传声纹到云端，保持本地处理。

## 验收标准

- 声纹提取测试通过，能处理 wav/m4a 格式。
- 二次切分测试通过，能正确合并连续同说话人窗口。
- 对 `output/preprocessed/` 的示例片段可运行分离并输出统计报告。
