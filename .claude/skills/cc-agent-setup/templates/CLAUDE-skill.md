# CLAUDE.md

> **可复用项目规范模板（agent skill 工作区类）**，由 `cc-agent-setup` skill 提供：空目录触发 `/cc-agent-setup` 自动复制本文件（改名为 CLAUDE.md）并执行【一次性】初始化；亦可手动复制改名后对 Claude 说「按 CLAUDE.md 初始化项目」。初始化完成后删除【一次性】章节并填写「项目产物说明」。模板权威源位于 `cc-agent-setup` skill 的 templates/ 目录。

## 项目简介

- 项目名称：<!-- TODO: 初始化时填写 -->
- 一句话目标：<!-- TODO: 初始化时填写（示例：维护一组提升 Claude Code 效率的个人 skill） -->
- 项目类型：agent skill 工作区（多 skill 集中开发与管理）

## 语言约定

- skill 名、文件夹名、文件名、标识符：英文小写+中划线（如 `make-slides`），禁止中文路径
- SKILL.md：正文中文；description（头部触发描述）中英双语，写在 1024 字符内
- README 等对外文档：中英双语，先中文后英文
- Git 提交信息：约定式英文描述 + 中文注解，如 `feat: add make-slides skill (新增幻灯片生成技能)`；类型限 feat / fix / docs / style / refactor / test / chore

## skill 目录结构

```
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md
│       ├── references/
│       ├── scripts/
│       └── assets/
├── scripts/
└── docs/plans/
```

- 新 skill 落位 `skills/<skill-name>/`（文件夹与 SKILL.md 头部 name 同名）；根目录只放 README / TODO / CHANGELOG / .env.example 等全局文档
- 目录按需生长，不预建空目录
- **渐进披露原则**：SKILL.md 正文 ≤500 行；更长的资料移入 `references/`，正文只写「何时读哪个文件」。description 是招牌，正文是操作手册

（各目录具体用途初始化后写入「项目产物说明」）

## 依赖与脚本

- 默认零依赖：优先写纯指令 skill；确实需要脚本时按需选 Python（`uv add <包>`）或 Node（`npm install <包>`），一律装项目级，禁止 `pip install`、禁止 `npm install -g`
- skill 内脚本尽量零依赖——skill 会被复制到别处使用，依赖重了换台机器就跑不动
- 用户级安装遵循「三步流程」：装前醒目声明并确认 → 安装凭证存 `D:\BaiduSyncdisk\software`（无独立安装包则导出来源 URL/命令/版本；**只在真正保存安装包时询问是否使用默认路径**）→ 装后醒目总结

## 版本控制

- git，直接在 main 小步提交，每个提交只做一件事；提交前先格式化（引入格式化工具后，如 Prettier 装项目级）
- 禁止提交：`.env`、`node_modules/`、`.venv/`、`tmp/`、`dist/`（.gitignore 已拦截，不得绕过）

## 质量验收

- skill 的创建、修改流程与打包校验由专门的制作 skill 掌控；未收录时按下面两关自查
- **头字段自查**：文件夹名与 name 字段一致且合规（小写中划线、≤64 字符）；description 双语、写清「做什么+何时用」；正文引用的 references 文件真实存在
- **触发测试**：新开会话用 2~3 句中文自然语言实测能否触发，且无关请求不误触发
- 自动校验（可选）：已引入 Node 工具链的项目用 `npm run validate` 校验 `skills/*/SKILL.md` 头字段

## 文档与任务

- `README.md`（双语）：项目简介 + **skill 索引表**（名称 / 一句话用途 / 触发词 / 状态），新增或更新 skill 后必须同步
- `TODO.md`：三栏清单（待办 / 进行中 / 已完成）——开工前先读，完工后更新；新 skill 先登记再动手
- 复杂 skill 动手前：计划写到 `docs/plans/<skill-name>.md`
- `CHANGELOG.md`：每完成一个 skill 记一笔；版本号从 0.1.0 起——修 bug 最后一位 +1，新 skill 中间位 +1

## 敏感信息

- API 密钥、密码等只放 `.env`（已 gitignore），脚本通过环境变量读取；禁止写进 skill、文档或提交记录
- skill 会被复制、分享——部署或分享前检查内嵌内容不含任何密钥或隐私数据

## 交付与部署

任何交付或部署操作前**必须向用户确认**目标、步骤与回滚/验证方案，禁止在未确认的情况下直接发布。

skill 通过质量验收即算交付，**按需手动部署**到任一位置（复制整个 skill 文件夹，部署后新开会话生效）。部署前**必须询问用户**：本次部署到个人级全局，还是某个项目的项目级？确认目标后再复制。

- 个人级全局：`~/.claude/skills/<skill-name>/`（Windows：`C:\Users\<用户名>\.claude\skills\`），所有项目可用
- 项目级：目标项目的 `.claude/skills/<skill-name>/`，仅该项目生效
- skill 更新后重新部署时同样要先询问，**对任何项目都执行此询问**，不得默认直接复制到全局目录

## 章节维护

- 标注【一次性】的章节：执行完成后立即删除，并把结果写入「项目产物说明」，供后续开发识别使用
- 其余章节为常驻规范，默认保留；开发中若发现规范与现实矛盾，停下提示用户裁决，不得静默违背或擅自修改
- 复制进项目后即为该项目自有规范，改动不同步回模板；确有通用价值的新规范经 `cc-agent-setup` 子功能的「可复用」路径写回模板库

## 流程归属

- skill 的创建与修改：优先用专门的制作 skill 掌控流程与校验
- 项目初始化与 CLAUDE.md 生成/整合：用 `/cc-agent-setup`
- 本文件只定规范；流程与本规范冲突时，以本规范为准

---

## 【一次性】新项目初始化指令

> 本章节通常由 `cc-agent-setup` skill（`/cc-agent-setup` 触发）逐步执行；手动使用时由 Agent 按用户指令执行。全部完成后删除本章节，并填写「项目产物说明」。

1. 询问用户：项目名称、一句话目标 → 填入「项目简介」
2. `git init -b main`
3. 生成 `.gitignore`：以**最小必需集**开始，按实际生态追加。skill 工作区多为纯文档仓库，初始内容如下：

```
# 依赖与环境
node_modules/
.venv/
# 产物与临时文件
tmp/
dist/
# 敏感信息
.env
# 日志与系统文件
*.log
.DS_Store
```

追加规则（仅在确定对应技术栈/环境时使用）：
- Python 脚本/校验工具：`__pycache__/`、`build/`、`.cache/`、`*.egg-info/`
- Windows 开发机：`Thumbs.db`、`desktop.ini`
- 其他按项目实际出现的临时文件追加

4. 生成 `README.md`（双语：项目名与简介、skill 索引表、部署方法；先中文后英文）
5. 生成 `TODO.md`（三栏：待办 / 进行中 / 已完成）
6. 生成 `CHANGELOG.md`（标题 `# Changelog`，首条 `## [0.1.0] - 未发布`）
7. 若 skill 确实需要 API 密钥/环境变量，生成 `.env.example`（空模板，逐键注释用途，不留真实值）；否则跳过，不生成空壳
8. 目录按需创建、不预建空目录：`skills/`、`scripts/`、`docs/plans/` 在出现真实落位需求时再建，并登记到「项目产物说明」；若已确定要创建首个 skill/脚本/计划，可即时创建并放一个 `.gitkeep`（`tmp/`、`dist/` 已被 gitignore，需要时再建）
9. 工具链初始化（**条件式**，纯文档仓库跳过本步）：需要 Node 工具链时 `npm init -y` 且 `npm i -D prettier`，按需创建 `scripts/` 目录并编写 `scripts/validate-skills.mjs`（遍历 `skills/*/SKILL.md` 校验：YAML 头含 `name` 与 `description`；name 为小写字母数字中划线、≤64 字符、与所在文件夹同名；description ≤1024 字符；发现问题逐条列出并以非零码退出），并在 `package.json` 的 `scripts` 中加入 `"validate": "node scripts/validate-skills.mjs"` 与 `"format": "prettier --write ."`
10. 首次提交：`chore: init project (初始化项目)`
11. 删除本章节，填写「项目产物说明」：列出已生成的全部文件与目录及各自用途
12. 执行初始化检查清单：确认项目名称/目标已填、所有 `<!-- TODO: -->` 占位符已处理、本章节已删除、项目产物说明已填写

## 项目产物说明

（尚未初始化——初始化完成后由 Agent 填写：生成了哪些文件/目录、各自用途）
