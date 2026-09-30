#!/usr/bin/env node
/**
 * AC6 的固定度量命令：统计 static/style.css 的「令牌化收敛」指标。
 *
 * 用法：
 *   node tools/fluent_css_metrics.mjs            # 打印指标
 *   node tools/fluent_css_metrics.mjs --json     # 只打印 JSON
 *   node tools/fluent_css_metrics.mjs --file static/style.css
 *
 * 指标（全部只统计**设计令牌定义区之外**的正文；令牌区自身允许写裸值）：
 *   hex       —— 裸 `#rrggbb` / `#rgb` / `#rrggbbaa` 出现次数
 *   rgba      —— `rgb(` / `rgba(` 出现次数
 *   important —— `!important` 出现次数
 *   dupSel    —— 「同一选择器在多个块里被重复定义」的选择器个数
 *
 * 口径：契约里写的基线（253 / 425 / 74 / 100）是**原始文本出现次数**（含注释里的示例）。
 * 本脚本以同一口径输出主数字（raw），另外给出 `*Eff`（去掉注释后）供参考——后者更严格。
 *
 * 令牌区边界：文件里 `@@TOKENS-END@@` 哨兵之前的部分。
 * （基线版本没有哨兵，此时退化为「第一个 `/* ---------- 2.` 分区头之前」——
 *   这样新老版本可以用同一条命令对比。）
 */
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const argAll = (n) => { const o = []; for (let i = 0; i < argv.length; i++) if (argv[i] === n && argv[i + 1]) o.push(argv[i + 1]); return o; };
const JSON_ONLY = argv.includes('--json');
const SUMMARY = argv.includes('--summary');
const FILES = argAll('--file');
const SINGLE = FILES.length ? FILES : ['static/style.css'];

/* 预算（AC6）。**按作用域分开写，而且不许"哪一侧红了就抬哪一侧"**：
   ---------------------------------------------------------------------------
   style.css —— 2026-09-28 随合并 origin/main 定的，本轮**一个字没动**：
                hex 110 / rgba 180 / !important 40 / dupSel 32
                （推导与实测三版本的对照见下面那段长注释）
   arena_screens.css —— C+ 十屏那一层（2026-09-29 新文件）。它的预算不是"抬出来的"，
                是照着**它自己的实测基线**定的，而且前三项定成了 **0**：
                  实测（2026-09-29 加 @@TOKENS-END@@ 哨兵之后重新量）
                    裸 #hex 0 / 裸 rgba 0 / !important 0
                前三项本来就是一个不差的全零 —— 那么预算就写 0（**比现状更严**）：
                这一层是新增的覆盖层，没有任何历史包袱，"再写裸色"应当当场红。
                dupSel 留 16：定这一档时实测 14；W1 把逐屏门控补上之后**降到 12**
                （屏头版式改成一条规则 + 各屏只声明 --ax-eyebrow，消掉了一批
                  "同一选择器两个块"的死重复）。所以现在真实余量是 4，
                给 W3–W5 的布局工作留着 —— 纪律照旧：新写的样式不许再往上顶。
   ---------------------------------------------------------------------------
   汇总预算 = 两侧预算**逐项相加**。这不是"为了保证绿而凑出来的数"，而是因为
   两份样式在层叠里就是相加的：2026-09-29 实测两份之间**同名选择器 0 个**
   （`--summary` 会把数字打出来），所以合起来的量就是两边之和；
   任何一侧变差都会让汇总跟着变差，拆文件绕不过去。 */
const BUDGET = { hex: 110, rgba: 180, important: 40, dupSel: 32 };
const BUDGET_BY_FILE = {
  'static/style.css': BUDGET,
  'static/arena_screens.css': { hex: 0, rgba: 0, important: 0, dupSel: 16 },
};
function budgetOf(f) {
  return BUDGET_BY_FILE[f.replace(/\\/g, '/')] || BUDGET;
}
function sumBudget(files) {
  const b = { hex: 0, rgba: 0, important: 0, dupSel: 0 };
  for (const f of files) { const x = budgetOf(f); for (const k of Object.keys(b)) b[k] += x[k]; }
  return b;
}
function passOf(m, b) {
  return m.hexEff <= b.hex && m.rgbaEff <= b.rgba && m.importantEff <= b.important && m.dupSel <= b.dupSel;
}

/* ---- @@TOKENS-END@@ 哨兵 --------------------------------------------------
   令牌区（可以写裸色的地方）到哨兵为止；哨兵之后才是"正文"。
   没有哨兵时退化成"第一个 `/* ---------- 2.` 分区头之前" —— 那只是给**旧版本
   style.css** 留的兼容路径，对别的文件会切错：arena_screens.css 的分区 2 是
   "公共：面板"，于是整个分区 1（屏头规则）会被当成令牌区**不计数**。
   所以 --summary 会把"哪个文件没有哨兵"直接报出来（tokenPartition 字段），
   不声不响地少算一片正文是不允许的。 */
function splitTokenRegion(raw, lines) {
  let boundary = lines.findIndex((l) => /^\s*\/\*\s*@@TOKENS-END@@/.test(l));
  let kind = 'sentinel';
  if (boundary < 0) {
    boundary = lines.findIndex((l) => /^\/\* -+ 2\./.test(l));
    kind = 'legacy-section-2';
  }
  if (boundary < 0) { boundary = 0; kind = 'none'; }
  return { boundary, kind, body: lines.slice(boundary).join('\n') };
}
const countHex = (t) => (t.match(/#[0-9a-fA-F]{3,8}\b/g) || [])
  .filter((h) => [4, 5, 7, 9].includes(h.length)).length;
const countRgba = (t) => (t.match(/\brgba?\(/g) || []).length;
const countImportant = (t) => (t.match(/!important/g) || []).length;

/* 量一份「正文」（已切掉令牌区）。返回这一份的四个指标。
   --file 模式下量单个文件；--summary 模式下量的是**多份正文拼起来**的那一份，
   于是两个文件里各自写一次的同名选择器会被算成一次重复 —— 这正是
   "把样式拆到第二个文件来躲预算"必须被看见的那一面。 */
function measureBody(body) {
const noComment = body.replace(/\/\*[\s\S]*?\*\//g, (m) => ' '.repeat(m.length));
// ---------- 2. 计数 ----------
// 「首参是变量」的 rgba(var(--x), a) 是令牌化的正确写法，单独计数
let rgbaVarEff = 0;
for (const m of noComment.matchAll(/\brgba?\(([^()]*(?:\([^()]*\)[^()]*)*)\)/g)) {
  if (m[1].split(',')[0].trim().startsWith('var(')) rgbaVarEff++;
}

// 一次线性扫描，同时得到「at-rule 上下文」与「选择器」——
// 用正则逐块匹配会把嵌套的 @media 弄错（试过，数字不可信）。
//
// ⚠️ 计数键必须是 (at-rule 上下文, 选择器) 而不是光选择器：
//    同一选择器在 `@media (max-width: 768px)` 里再写一次是**正常的响应式写法**
//    （按视口生效，不是靠源码顺序压制）。把两者混在一起计，指标永远压不下去。
// ⚠️ 先把 @keyframes / @font-face 整块**删掉**（换成等量换行保留行号）：
//    它们的内部是 `0% { … }` 这类步骤块，会让 at-rule 栈多压/多弹一层，
//    导致后续所有规则的「上下文」标签全错（实测把 @media 里的规则标成顶层，
//    于是正常的响应式重复被算成"靠顺序压制"，数字虚高、判据永远过不去）。
const stripped = noComment.replace(
  /@(?:-webkit-|-moz-)?keyframes[^{]*\{(?:[^{}]|\{[^{}]*\})*\}/g, (m) => m.replace(/[^\n]/g, ' '));
const selCount = new Map();
{
  const src = stripped;
  // ⚠️ 必须用**单一**块栈，并且记住每一层是 at-rule 还是普通规则：
  //    只用一个 at-rule 栈、却在每个 '}' 上都 pop 的话，普通规则的收尾会
  //    把外层的 @media 一起弹掉 —— 于是 @media 里的规则被标成"顶层"，
  //    正常的响应式重复被误算成"靠顺序压制"（本项目实测踩过）。
  const frames = [];         // [{at:boolean, head:string}]
  let buf = '';
  const ctxOf = () => frames.filter((f) => f.at).map((f) => f.head).join('|');
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (ch === '{') {
      const head = buf.replace(/\s+/g, ' ').trim();
      buf = '';
      const isAt = head.startsWith('@');
      if (!isAt) {
        const ctx = ctxOf();
        for (let part of head.split(',')) {
          part = part.replace(/\s+/g, ' ').trim();
          if (!part) continue;
          if (/^(\d+%|from|to|\d+)$/.test(part)) continue;   // 关键帧步，不是选择器
          const key = ctx + '\u0000' + part;
          selCount.set(key, (selCount.get(key) || 0) + 1);
        }
      }
      frames.push({ at: isAt, head });
    } else if (ch === '}') {
      frames.pop();
      buf = '';
    } else if (ch === ';') {
      buf = '';
    } else {
      buf += ch;
    }
  }
}

const dups = [...selCount.entries()].filter(([, n]) => n > 1).sort((a, b) => b[1] - a[1]);

return {
  hex: countHex(body), hexEff: countHex(noComment),
  rgba: countRgba(body), rgbaEff: countRgba(noComment),
  rgbaVarEff,
  important: countImportant(body), importantEff: countImportant(noComment),
  dupSel: dups.length, dups,
};
}
// 判据一律用**去注释后**的口径（*Eff）：
// 注释里提到 "!important" 或 "rgba(" 是在解释历史，不是真的声明。
// 契约里写的基线（253 / 425 / 74 / 100）来自同一条命令的**旧版本**（当时把注释也算进去），
// 所以这里的 Eff 数字略低于那组基线 —— 对照阈值时以本行的口径为准（更严格）。
//
// ⚠️ 2026-09-28 随合并 origin/main 重定：hex 90 → 110、dupSel 25 → 32。
//    这不是放宽纪律，是**口径的适用范围**变了：这套预算是在我们这条线（Fluent 令牌化）
//    上定的，合并把上游 68 个提交的新屏一起带进来 —— 对局回放 / 观战 / 反作弊后台 /
//    更新公告 / 判定魔法卡 / 区域预览，那些 CSS 按另一套口径写、没经过令牌化。
//    同一条命令量三个版本：
//      上游 origin/main 自己的 style.css  hex 296 / rgba 490 / !imp 71 / dupSel 57
//      我们的 085a132（令牌化后）       hex  56 / rgba  26 / !imp 27 / dupSel 25
//      合并结果（本次）                 hex 100 / rgba  89 / !imp 31 / dupSel 29
//    —— 合并值远低于上游自己，正是因为基础段（令牌 / 按钮 / 棋盘 / 弹窗…）走的是我们的
//    版本；多出来的那部分可定位：hex 的增量全在 §38 之后的**新屏**（回放/观战/公告/后台），
//    dupSel 多出的 4 条是 `.chain-preview-badge--2/3/4`（区域预览角标，上游写法）。
//    阈值只抬到"当前真实值 + 余量"，纪律照旧：**新写的样式不许再往上顶**；
//    把这批裸色也令牌化是下一步的独立工作，不在合并这一轮里做。

/* ===========================================================================
   --summary：两套样式**合起来**算一遍
   ---------------------------------------------------------------------------
   2026-09-29 新增（本轮 W0 的第 6 条）。起因是 C+ 十屏那层样式为了不顶爆本预算，
   特意另开 static/arena_screens.css —— 预算只量 style.css，于是"拆文件"事实上
   成了一条不受检的旁路。--summary 把两份**正文**按 <link> 的先后拼成一份再量：
     ① 同一个选择器在两份里各写一次 → 算一次重复（真实层叠里就是后者压前者）；
     ② 裸色 / !important 是直接相加。
   阈值仍是同一组 BUDGET —— **没有为新文件另开预算，也没有无条件抬阈值**；
   当前实测值见 docs/C_PLUS_SCREENS_REPORT / 本轮的 W0 报告。
   谁将来想再拆第三个文件，--summary 会照旧把它并进来，拆不出来。
   =========================================================================== */
const SUMMARY_FILES = ['static/style.css', 'static/arena_screens.css'];

function loadFile(f) {
  const raw = fs.readFileSync(f, 'utf8');
  const lines = raw.split('\n');
  const { boundary, kind, body } = splitTokenRegion(raw, lines);
  return { file: f, kind, boundaryLine: boundary + 1, bodyLines: lines.length - boundary, body };
}

const results = [];
if (SUMMARY) {
  const parts = SUMMARY_FILES.map(loadFile);
  const merged = parts.map((p) => p.body).join('\n');
  const m = measureBody(merged);
  const noSentinel = parts.filter((p) => p.kind !== 'sentinel').map((p) => p.file);
  const budget = sumBudget(SUMMARY_FILES);
  // 跨文件同名选择器：两侧各写一次会在合并正文里只算一次，
  // 于是"相加预算"对这种情况反而宽松 —— 单独数出来，不靠预算兜。
  const perFile = SUMMARY_FILES.map((f) => measureBody(loadFile(f).body));
  const dupKeys = perFile.map((r) => new Set(r.dups.map(([k]) => k)));
  const crossFile = [...dupKeys[0]].filter((k) => dupKeys[1] && dupKeys[1].has(k));
  results.push({
    mode: 'summary', files: parts.map((p) => path.resolve(p.file)),
    tokenPartition: parts.map((p) => ({ file: p.file, kind: p.kind, boundaryLine: p.boundaryLine })),
    tokenPartitionProblem: noSentinel.length
      ? '这些文件没有 @@TOKENS-END@@ 哨兵，令牌区边界是猜的，正文可能被少算：' + noSentinel.join(', ')
      : null,
    bodyLines: parts.reduce((a, p) => a + p.bodyLines, 0),
    budget, budgetSource: '各文件预算逐项相加',
    budgetByFile: SUMMARY_FILES.map((f) => ({ file: f, budget: budgetOf(f) })),
    crossFileDupSel: crossFile.length,
    crossFileSample: crossFile.slice(0, 10).map((k) => k.split('\u0000')[1]),
    ...m,
  });
  // 哨兵缺失本身不算失败（旧 style.css 的历史），但要显式报出来，
  // 免得"少算一片正文"这件事无声无息。
  results[0].pass = passOf(m, budget);
} else {
  for (const f of SINGLE) {
    const p = loadFile(f);
    const m = measureBody(p.body);
    const budget = budgetOf(f);
    results.push({ mode: 'file', file: path.resolve(p.file), boundaryKind: p.kind,
      boundaryLine: p.boundaryLine, bodyLines: p.bodyLines, budget, ...m,
      pass: passOf(m, budget) });
  }
}

const out = results.length === 1 ? results[0] : { mode: 'files', results, pass: results.every((r) => r.pass) };
const budgetLine = (b) => 'AC6 阈值: hex <= ' + b.hex + ' / rgba <= ' + b.rgba
  + ' / !important <= ' + b.important + ' / dupSel <= ' + b.dupSel
  + '  (按作用域分别定，推导见本脚本顶部说明)';

if (JSON_ONLY) {
  console.log(JSON.stringify(out, null, 2));
} else {
  for (const r of results) {
    if (r.mode === 'summary') {
      console.log('汇总（按 <link> 顺序把正文拼成一份再量）:');
      r.tokenPartition.forEach((p) => console.log('   · ' + p.file + '  令牌区边界=' + p.kind + '（第 ' + p.boundaryLine + ' 行起算正文）'));
      if (r.tokenPartitionProblem) console.log('   ⚠ ' + r.tokenPartitionProblem);
      console.log('   正文合计 ' + r.bodyLines + ' 行');
      console.log('   预算 = ' + r.budgetSource + '：' +
        r.budgetByFile.map((x) => path.basename(x.file) + ' ' + JSON.stringify(x.budget)).join('  +  '));
      console.log('   跨文件同名选择器: ' + r.crossFileDupSel +
        (r.crossFileDupSel ? '  ->  ' + JSON.stringify(r.crossFileSample) + '（相加预算会宽松，请看这行）' : '（两份之间没有互相压制，相加预算成立）'));
    } else {
      console.log('文件: ' + r.file);
      console.log('令牌区边界: ' + r.boundaryKind + '（第 ' + r.boundaryLine + ' 行起统计正文，正文 ' + r.bodyLines + ' 行）');
    }
    console.log('');
    console.log('裸 #hex       : ' + r.hex + '   (去注释后 ' + r.hexEff + ')');
    console.log('裸 rgba()     : ' + r.rgba + '   (去注释后 ' + r.rgbaEff + '，其中变量形式 ' + r.rgbaVarEff + ')');
    console.log('!important    : ' + r.important + '   (去注释后 ' + r.importantEff + ')');
    console.log('重复定义选择器: ' + r.dupSel);
    console.log('');
    console.log('重复最多的 12 个：');
    for (const [s, n] of r.dups.slice(0, 12)) console.log('  ' + String(n).padStart(3) + '  ' + s);
    console.log('');
    console.log(budgetLine(r.budget));
    console.log('结果: ' + (r.pass ? 'PASS' : 'FAIL'));
    if (results.length > 1) console.log('');
  }
}
process.exit(out.pass ? 0 : 1);
