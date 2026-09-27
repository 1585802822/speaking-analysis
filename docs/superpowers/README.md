# docs/superpowers/ 目录说明

本目录保留项目早期 SuperPowers 阶段产生的可读性产物。经过文档归并后，**权威（canonical）设计文档与变更历史已迁移到 `openspec/`**，本目录只保留未被 OpenSpec 直接吸纳的可视化文件、验证报告以及被 OpenSpec 历史变更引用的计划文件。

## 当前内容

| 路径 | 说明 |
|---|---|
| `specs/speaking-analysis-architecture.json` / `.html` | 项目整体系统架构可视化源文件 |
| `specs/speaking-analysis-pipeline.json` | 项目整体流水线可视化源文件（与 `architecture` 视图描述同一系统，侧重时序） |
| `specs/api-model-integration-architecture.json` / `.html` | API 模型集成变更的架构可视化（该变更已归档于 `openspec/changes/archive/api-model-integration/`） |
| `specs/better-voiceprint-model-architecture.json` / `.html` | 声纹模型升级变更的架构可视化（该变更在 `openspec/changes/better-voiceprint-model/`） |
| `reports/audio-preprocessing-pipeline-verification-report.md` | 音频预处理模块改造的验证报告（对应 `openspec/changes/archive/audio-preprocessing-pipeline/`） |
| `plans/plan.md` | 项目早期整体实施计划，被 `openspec/changes/archive/daily-speaking-analysis/tasks.md` 引用，保留以满足历史链接 |

## 权威文档入口

- **项目总设计**：[`openspec/design.md`](../openspec/design.md)
- **当前/活跃变更**：`openspec/changes/<变更名>/`
- **已归档变更**：`openspec/changes/archive/<变更名>/`
- **Comet 工作流配置与证据**：`.comet/`
- **Claude Code 项目规范**：[`CLAUDE.md`](../CLAUDE.md)

## 维护提示

新增设计文档时，优先写入 `openspec/changes/<变更名>/` 或更新 `openspec/design.md`，避免在 `docs/superpowers/` 中再形成第二份权威来源。`docs/superpowers/` 只用于：

1. 生成架构图/流水线图的可视化源文件；
2. 存放验证报告等辅助性产物；
3. 保留被历史 OpenSpec 工件显式引用的旧文件。
