# 任务清单：声音预处理模块改造

## 设计阶段

- [x] 编写变更提案 `proposal.md`
- [x] 编写设计文档 `design.md`
- [x] 用户确认设计方案
- [x] 生成 Superpowers 设计文档 `docs/superpowers/specs/audio-preprocessing-pipeline-design.md`

## 实现阶段

- [x] 扩展 `src/types.py`：Segment 新增元数据字段
- [x] 改造 `src/preprocessor.py`：支持可配置降噪/VAD 后端
- [x] 新增 `src/segment_filter.py`：目标说话人过滤逻辑
- [x] 改造 `src/diarization.py`：按声纹过滤 Segment
- [x] 更新 `config.yaml`：新增 `preprocessing` 配置段
- [x] 更新 `requirements.txt`：新增可选依赖
- [x] 新增/更新单元测试
- [x] 更新 README

## 验证阶段

- [x] 运行 pytest 全部通过
- [ ] 使用示例录音验证有效片段过滤效果
- [ ] 量化下游 token 节省比例
