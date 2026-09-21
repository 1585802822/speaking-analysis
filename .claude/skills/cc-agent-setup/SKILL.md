---
name: cc-agent-setup
description: 项目初始化与 CLAUDE.md 管理规范套件（Project initialization & CLAUDE.md governance toolkit）。主功能：在空目录按规范模板初始化新项目（选模板、复制为 CLAUDE.md、执行【一次性】初始化：git init、生成 README/TODO/CHANGELOG/.gitignore/.env.example、建目录、按技术栈初始化、首提交）；目录已有 CLAUDE.md 时做整合而非覆盖。子功能：按十维清单工作流生成个性化 CLAUDE.md（临时的或可复用模板，可复用模板沉淀入本 skill）。仅要代码库文档式 CLAUDE.md 请用内置 /init。
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Glob, Grep, AskUserQuestion, Bash(git init *), Bash(git add *), Bash(git commit *), Bash(git status*), Bash(mkdir *), Bash(wc *), Bash(npm init*), Bash(npm i *), Bash(npm install *), Bash(uv init*), Bash(uv add *), Bash(uv run *)
---

项目初始化与 CLAUDE.md 管理规范套件，手动进入（`/cc-agent-setup`）后按用户来意分流。本 skill 文件夹内的路径均相对本文件夹解析（`templates/`、`references/`）。

## 角色定位

本 skill 负责为几类常见任务（如软件开发、agent skill 工作区等）确定规范骨架，生成并维护 `CLAUDE.md`。具体流程执行交给各专业流程型 skill，但本 skill 不列举具体 skill 名称。本 skill 只负责规范文件本身。

## 功能分流（触发后第一步）

| 情形 | 走向 |
|---|---|
| 空目录 + 用户要初始化新项目 | 主功能 A（下节） |
| 目录已有 CLAUDE.md + 用户要引入/整合规范 | 主功能 B —— 先读 `references/integration.md` |
| 用户要生成/定制 CLAUDE.md（临时或可复用模板） | 子功能 —— 先读 `references/claude-md-guide.md` |
| 只要「描述现有代码库」的文档式 CLAUDE.md | 不启动本 skill：说明区别，建议内置 `/init` |

来意不明时先问一句再分流，不猜。

## 主功能 A：初始化新项目（空目录）

> **按需生成 / 奥卡姆剃刀**：只生成项目当前确实需要的文件/目录；不预建空目录；`.env.example`、`.gitignore` 按项目实际类型与需求生成；`.gitignore` 以最小必需集开始，技术栈/运行环境确定后再追加对应条目；纯文档或无密钥项目不生成 `.env.example`。

1. **前置检查**：确认当前目录为空（或仅含无关紧要的杂项）；有代码先向用户确认是否继续。
2. **选模板**：按项目类型查「模板索引」表；software / skill 工作区直取对应模板；**无匹配类型 → 征得用户同意后先走子功能生成该类型模板，生成后回到本步**（主子闭环）。
3. **复制模板**：读本 skill 文件夹 `templates/` 下对应文件，完整复制为当前目录的 `CLAUDE.md`（`CLAUDE-software.md` 等带类型后缀的需改名）。模板缺失则停止并告知用户，**不得凭记忆重构模板内容**。
4. **初始化微调**：执行【一次性】询问时：
   - 软件类模板必须询问/确认技术栈；
   - skill 工作区等非软件类模板**不强制**询问技术栈，需要时再补充。
   - 顺势确认模板默认值（依赖分级、目录结构等）是否照用，按用户答案微调 `CLAUDE.md`。
5. **执行【一次性】**：逐步执行；模板要求的确认流程（如安装 `uv` 前的声明确认、删除/安装/联网先确认）照常执行。安装包保存路径**不在本阶段确定**。
6. **收尾**：删除 `CLAUDE.md` 中的【一次性】章节、填写「项目产物说明」、向用户总结生成了哪些文件与目录。

> **技术栈后续变更**：当 Agent 后续发现项目技术栈发生变化（如改用 `pnpm`、新增 Rust 工具链），应自动读取并更新 `CLAUDE.md` 的相关章节，无需单独触发本 skill。

## 主功能 B：整合已有 CLAUDE.md

三原则：用户已有内容一字不动；只对齐/补充固定骨架章节；整合报告经用户逐项确认后才写盘。具体算法（特例分流 + 三趟解析/对齐/合并）见 `references/integration.md`，**先读再动手**。

## 子功能：生成个性化 CLAUDE.md

1. **先问用途**（`AskUserQuestion` 二选一）：
   - **临时**：为特定项目定制，生成后写到目标项目根目录 `CLAUDE.md`；已存在则先经用户确认，必要时转主功能 B 整合。
   - **可复用**：沉淀为模板——剥离项目专属信息（真实项目名、路径、密钥线索等，换回占位符）→ 存本 skill 文件夹 `templates/CLAUDE-<类型>.md` → 在「模板索引」表追加一行。
2. **按 `references/claude-md-guide.md` 五步工作流执行**（识别类型 → 讲解 → 选择 → 生成 → 交付自检），实践要点为硬性要求：
   - 待拍板项超过 4 个时分轮提问，每轮凑满 4 题，减少来回。
   - 用户选项外的自定义答案**原样落实**（用其原始表述），禁止套用相近选项替代。
   - 讲解时可引用 `templates/` 中类型最接近的成品模板作对照案例。
   - 生成后行数验证（≤150 行）+ 自检表逐项报告所选维度落实情况；**生成的 CLAUDE.md 必须包含「交付与部署」章节，且任何交付/部署操作前必须向用户确认目标、步骤与回滚/验证方案**。
   - 可复用路径的自检表额外加一条「占位检查」：确认无项目专属信息残留。

## 模板索引

| 文件（`templates/` 下） | 适用类型 | 特点摘要 |
|---|---|---|
| `CLAUDE-software.md` | 软件开发 | src/tests 目录落位法则、uv/npm 项目级依赖、Prettier/Ruff、feat/fix 分支流 |
| `CLAUDE-skill.md` | agent skill 工作区 | skills/ 目录规范、渐进披露（正文 ≤500 行）、质量验收两关、条件式 validate 脚本、按需部署 |

（新类型模板经子功能「可复用」路径生成后在此追加一行）

## 占位符与初始化检查清单

- **占位符统一格式**：`<!-- TODO: 初始化时填写 -->`（HTML 注释，不渲染）。旧式 `（初始化时填写）` 逐步替换。
- **复制模板后必须执行「初始化检查清单」**，逐项勾选：
  1. 项目名称、一句话目标已填入「项目简介」。
  2. 技术栈已按需确认并填入（软件类必填；非软件类未确定时保留占位符）。
  3. 所有 `<!-- TODO: 初始化时填写 -->` 占位符已处理或已确认保留。
  4. 【一次性】章节已执行并删除。
  5. 「项目产物说明」已填写。
- 未处理完的占位符禁止删除标记。
