import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const skillDir = path.resolve(__dirname, "..");

const issues = [];

function read(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walk(full);
    } else if (entry.isFile() && entry.name.endsWith(".md")) {
      yield full;
    }
  }
}

function rel(filePath) {
  return path.relative(skillDir, filePath).replace(/\\/g, "/");
}

// 1. SKILL.md 头字段检查
const skillMdPath = path.join(skillDir, "SKILL.md");
const skillMd = read(skillMdPath);
const fmMatch = skillMd.match(/^---\n([\s\S]*?)\n---/);
if (!fmMatch) {
  issues.push("SKILL.md 缺少 YAML 头字段");
} else {
  const fm = fmMatch[1];
  const nameMatch = fm.match(/^name:\s*(.+)$/m);
  const name = nameMatch ? nameMatch[1].trim() : "";
  if (name !== "cc-agent-setup") {
    issues.push(`SKILL.md name 为 "${name}"，应为 "cc-agent-setup"`);
  }

  const descMatch = fm.match(/^description:\s*(.+)$/m);
  const desc = descMatch ? descMatch[1].trim() : "";
  if (desc.length === 0) {
    issues.push("SKILL.md description 为空");
  } else if (desc.length > 1024) {
    issues.push(`SKILL.md description 长度 ${desc.length}，超过 1024 字符`);
  }

  if (!fm.includes("disable-model-invocation: true")) {
    issues.push("SKILL.md 未设置 disable-model-invocation: true");
  }
}

// 2. 模板索引与实际文件一致性
const templateDir = path.join(skillDir, "templates");
const indexMatches = [...skillMd.matchAll(/\|\s*`?(CLAUDE-[^`|\s]+\.md)`?\s*\|/g)];
const indexedTemplates = indexMatches.map((m) => m[1].trim()).sort();
const actualTemplates = fs
  .readdirSync(templateDir)
  .filter((f) => f.startsWith("CLAUDE-") && f.endsWith(".md"))
  .sort();

if (JSON.stringify(indexedTemplates) !== JSON.stringify(actualTemplates)) {
  issues.push(
    `模板索引与实际文件不一致：索引 [${indexedTemplates.join(", ")}]，实际 [${actualTemplates.join(", ")}]`
  );
}

// 3. 残留旧硬编码路径与旧名称
const badStrings = [
  "C:\\Users\\Administrator\\",
  "d:\\tools\\installers\\",
  "/new-project",
];

for (const filePath of walk(skillDir)) {
  const content = read(filePath);
  for (const bad of badStrings) {
    if (content.includes(bad)) {
      issues.push(`${rel(filePath)} 包含残留字符串：${bad}`);
    }
  }
}

// 4. 模板占位符格式
for (const tmpl of actualTemplates) {
  const filePath = path.join(templateDir, tmpl);
  const content = read(filePath);
  if (content.includes("（初始化时填写）")) {
    issues.push(`templates/${tmpl} 包含旧式占位符 "（初始化时填写）"，请改用 "<!-- TODO: ... -->"`);
  }
}

// 5. 「按需生成 / 奥卡姆剃刀」静态检查
function extractOneTimeSection(content) {
  const match = content.match(/## 【一次性】新项目初始化指令\s*\n\n([\s\S]*?)\n## /);
  return match ? match[1] : "";
}

function hasConditionalMarker(text) {
  return /(?:若|如果|除非|按需|需要|待|出现|确定|条件|按技术栈|按项目类型|按实际|否则跳过|再生成|时再|有.*需求|有.*需要|需要时)/.test(text);
}

function lintConditionalCreationSteps(section, templateName) {
  // 拆分一次性章节里的每个编号步骤（支持步骤内换行）
  const steps = [...section.matchAll(/\d+\.\s+(.*?)(?=\n\d+\.|\n## |$)/gs)];
  for (const [, stepText] of steps) {
    const isCreationStep =
      /创建目录|mkdir/.test(stepText) ||
      /生成\s+`\.env\.example`|生成\s+\.env\.example/.test(stepText) ||
      /生成\s+`\.gitignore`|生成\s+\.gitignore/.test(stepText);
    if (!isCreationStep) continue;
    if (!hasConditionalMarker(stepText)) {
      issues.push(
        `${templateName} 一次性章节存在未条件化的生成步骤：${stepText.split("\n")[0].trim()}`
      );
    }
  }
}

function lintGitignoreScope(section, templateName) {
  const match = section.match(/生成\s+`?\.gitignore`?.*?\n```\n([\s\S]*?)```/);
  if (!match) return;
  const gitignore = match[1];
  const broadEntries = ["__pycache__/", "build/", ".cache/", "Thumbs.db", "desktop.ini"];
  const found = broadEntries.filter((entry) => gitignore.includes(entry));
  if (found.length > 0) {
    issues.push(
      `${templateName} .gitignore 初始代码块包含过宽条目：${found.join(
        ", "
      )}；应仅在确定对应技术栈/环境时以追加规则列出`
    );
  }
}

function lintOnDemandPrinciple(content, templateName) {
  if (
    content.includes("目录按需生长，不预建空目录") ||
    content.includes("目录按需创建、不预建空目录")
  ) {
    return;
  }
  issues.push(`${templateName} 正文章节缺少「目录按需生长，不预建空目录」原则声明`);
}

for (const tmpl of actualTemplates) {
  const filePath = path.join(templateDir, tmpl);
  const content = read(filePath);
  const section = extractOneTimeSection(content);
  if (!section) {
    issues.push(`templates/${tmpl} 缺少【一次性】新项目初始化指令章节`);
    continue;
  }
  lintConditionalCreationSteps(section, `templates/${tmpl}`);
  lintGitignoreScope(section, `templates/${tmpl}`);
  lintOnDemandPrinciple(content, `templates/${tmpl}`);
}

// 输出
if (issues.length > 0) {
  console.error("validate-templates: 检查未通过");
  for (const issue of issues) {
    console.error(`  - ${issue}`);
  }
  process.exit(1);
} else {
  console.log("validate-templates: 全部通过");
}
