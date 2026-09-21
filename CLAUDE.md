<comet-ambient-resume>
<!-- Managed by Comet. Edits inside this block may be replaced by comet init/update. -->
<!-- Contract: comet.resume_probe.v2 -->

## Comet Ambient Resume

In this repository, before starting work that may need code changes or investigation, pass the current user request to the read-only probe when a Comet workflow may already be active: `comet resume-probe . --stdin --json`.

- If the user explicitly invokes any Comet Skill through the host (for example, `@comet`, `/comet`, `@comet-native`, or `/comet-hotfix`), that explicit invocation takes precedence over this resume protocol; do not run the resume probe, and enter the invoked Skill directly.
- Trust only the returned `workflow`, `skill`, and `entrySource`; project configuration or the no-config compatibility fallback alone selects them. Do not scan or switch to the other workflow.
- If the probe returns `auto_resume`, briefly state the selected active change and enter the permanent entry in `nextCommand`. Do not treat a state command as the resume entry or advance it blindly.
- If the probe returns `ask_user`, ask one short question and wait.
- If the current request did not explicitly invoke a Comet Skill and the probe returns `out_of_scope` or `none`, do not enter the Comet workflow.
- If configuration or state is invalid and `nextCommand` is absent, stop and report the reason; do not guess another workflow.
- Never attach unrelated work merely because an active change exists. The Native entry inspects uncommitted work; the probe does not attribute it automatically.
</comet-ambient-resume>

# CLAUDE.md

> 本规范由 `cc-agent-setup` skill 提供。在项目目录触发 `/cc-agent-setup` 可自动按本规范初始化新项目；日常开发中若规范与现实矛盾，停下提示用户裁决，不得擅自违背。

## 项目简介

- 项目名称：日常录音分析工具
- 一句话目标：本地运行的日常录音分析工具，帮助用户通过分析自己的录音发现表达问题
- 技术栈：Python 3.9+，依赖 faster-whisper、pyannote.audio、speechbrain、torch、transformers、noisereduce、silero-vad 等；使用 uv 管理依赖

## 语言约定

- 与 Claude 沟通、代码注释、TODO、计划文档：中文
- 代码标识符（变量/函数/类/包名）、文件名、目录名、Git 分支名：英文，禁止中文路径
- README 等对外文档：中英双语，先中文后英文
- Git 提交信息：约定式英文描述 + 中文注解，如 `feat: add speaker filter (新增声纹过滤)`；类型限 feat / fix / docs / style / refactor / test / chore

## 依赖与安装规范

**分级规则：**
- 项目级（默认）：项目代码用到的库，一律装进项目环境——用 `uv add <包>`；禁止用 `pip install` 安装项目库
- 用户级（例外）：① 多个项目共用且版本不敏感；② 社区公认用户级安装的工具（uv、git 等）

**用户级安装三步流程（必须完整执行）：**
1. 安装前：醒目向用户声明——装什么、为什么用户级、安装到哪，确认后执行
2. 留存凭证：安装包默认保存到 `D:\BaiduSyncdisk\software`；只在真正保存安装包时询问用户是否使用此默认路径
3. 安装后：醒目总结——所装版本、安装位置、安装包/引导的存档处

**日常命令：**
- 加依赖：`uv add <包>`
- 运行：`uv run <脚本>`
- `.venv/` 不提交不手改；`uv.lock` 必须提交

## 目录结构（新文件落位法则）

**第零问（优先）：项目所用框架/语言有惯例目录结构吗？** 有 → 跟随惯例；没有 → 走下方问法兜底。

```
├── src/              # 手写源代码
├── tests/            # 自动化测试
├── tests/fixtures/   # 测试音频/数据
├── scripts/          # 预处理/分离等辅助脚本
├── docs/             # 设计文档、教程；docs/plans/ 放功能计划
├── data/input/       # 用户待分析录音
├── data/output/      # 自动生成的报告
├── data/voiceprint/  # 注册声纹数据
├── tmp/              # 临时处理文件，随时可删
└── 根目录            # 只放配置文件与 README / TODO / CHANGELOG 等全局文档
```

新文件落位前依次问：手写产品代码？→ `src/`；验证代码？→ `tests/`；测试数据？→ `tests/fixtures/`；脚本？→ `scripts/`；文档？→ `docs/`；用户录音？→ `data/input/`；报告？→ `data/output/`；声纹？→ `data/voiceprint/`；临时文件？→ `tmp/`。

两条原则：
- 禁止把文件散落在根目录
- 目录按需生长：出现真实需求时才新建目录，并登记到「项目产物说明」

## Git 工作流

- 分支：每个功能/修复开独立分支，命名 `feat/<功能>`、`fix/<问题>`（英文小写中划线）；完成后合并回 main 并删除该分支
- 提交：小步提交，每个提交只做一件事；提交前对改动文件执行 Ruff 格式化
- 禁止提交：`.env`、`data/`、`.venv/`、`tmp/`、`__pycache__/`（.gitignore 已拦截，不得绕过）

## 测试

- 关键功能（核心计算、数据处理、关键函数）必须配自动化测试，放 `tests/`
- 改动核心逻辑后运行 `uv run pytest tests/` 并如实报告结果
- 依赖真实音频的测试先检查文件存在，不存在则 `pytest.skip`

## 代码格式化

- 使用 Ruff 作为项目开发依赖（`uv add --dev ruff`），不装全局
- 每次提交前对改动文件执行 `uv run ruff format` 与 `uv run ruff check --fix`

## 敏感信息

- API 密钥、密码等只放 `.env`（已 gitignore），代码通过环境变量读取；禁止写进代码、文档或提交记录
- `.env.example` 与 `.env` 字段保持同步（只留键名和用途注释，不留真实值）
- 声纹数据属于个人隐私，`data/voiceprint/` 已 gitignore，不得对外提交或分享

## API 模式

- `config.yaml` 中 `api.enabled` 可切换本地模型 / Model API Gateway
- API 密钥通过 `api_key_env` 指定的环境变量读取
- API 调用失败时自动回退到本地模型/占位逻辑，流水线不中断

## 任务与版本

- `TODO.md`：三栏清单（待办 / 进行中 / 已完成）——开工前先读，完工后更新
- 大功能动手前：计划写到 `docs/plans/<功能名>.md`
- 功能完成后：`CHANGELOG.md` 记一笔；版本号从 0.1.0 起——修 bug 最后一位 +1，新功能中间位 +1，破坏性大改第一位 +1

## 交付与部署

任何交付或部署操作前**必须向用户确认**：

1. **交付/部署目标**：环境（开发/测试/生产/发布渠道）、版本、预期影响范围
2. **执行步骤**：具体要运行哪些命令、上传哪些文件、修改哪些配置
3. **回滚/验证方案**：出问题如何恢复、部署后如何验证成功

用户确认后再执行；执行后如实报告结果。禁止在未确认的情况下直接部署到生产环境或对外发布。

## 章节维护

- 标注【一次性】的章节：执行完成后立即删除，并把结果写入「项目产物说明」，供后续开发识别使用
- 其余章节为常驻规范，默认保留；开发中若发现规范与现实矛盾，停下提示用户裁决，不得静默违背或擅自修改
- 确有通用价值的新规范，通过 `cc-agent-setup` skill 子功能的「可复用」路径写回模板库

---

## 【一次性】新项目初始化指令

> 本章节通常由 `cc-agent-setup` skill 逐步执行；手动使用时由 Agent 按用户指令执行。全部完成后删除本章节，并填写「项目产物说明」。

1. 确认「项目简介」已填写
2. 安装 uv（未安装时按「用户级安装三步流程」执行）
3. `uv sync` 安装依赖并生成/更新 `uv.lock`
4. 生成/更新 `.gitignore`：包含 `data/`、`.venv/`、`tmp/`、`.env`、`__pycache__/`、`*.log`
5. 若项目确实需要密钥/环境变量，生成 `.env.example`（空模板，逐键注释用途，不留真实值）；否则跳过
6. 目录按需创建、不预建空目录：`src/`、`tests/`、`docs/plans/` 在出现真实落位需求时再建
7. 首次提交：`chore: init project (初始化项目)`
8. 删除本章节，填写「项目产物说明」：列出已生成的全部文件/目录及各自用途
9. 执行初始化检查清单：确认项目名称/目标/技术栈已填、所有 `<!-- TODO: -->` 占位符已处理、本章节已删除、项目产物说明已填写

## 项目产物说明

（尚未初始化——初始化完成后由 Agent 填写：生成了哪些文件/目录、各自用途）
