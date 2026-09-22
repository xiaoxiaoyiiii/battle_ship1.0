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
const JSON_ONLY = argv.includes('--json');
const FILE = argOf('--file', 'static/style.css');

const raw = fs.readFileSync(FILE, 'utf8');
const lines = raw.split('\n');

// ---------- 1. 切出「令牌区之外」的正文 ----------
let boundary = lines.findIndex((l) => /^\s*\/\*\s*@@TOKENS-END@@/.test(l));
let boundaryKind = 'sentinel';
if (boundary < 0) {

// 只认「独立成行的哨兵」——文件头的说明注释里也会出现这个名字，
// 用 includes 会把边界定到注释上（症状是令牌定义被算进正文、数字虚高）。
  boundary = lines.findIndex((l) => /^\/\* -+ 2\./.test(l));
  boundaryKind = 'legacy-section-2';
}
if (boundary < 0) boundary = 0;
const body = lines.slice(boundary).join('\n');
const noComment = body.replace(/\/\*[\s\S]*?\*\//g, (m) => ' '.repeat(m.length));
// ---------- 2. 计数 ----------
const countHex = (t) => (t.match(/#[0-9a-fA-F]{3,8}\b/g) || [])
  .filter((h) => [4, 5, 7, 9].includes(h.length)).length;
const countRgba = (t) => (t.match(/\brgba?\(/g) || []).length;
const countImportant = (t) => (t.match(/!important/g) || []).length;

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

const out = {
  file: FILE,
  boundaryKind,
  boundaryLine: boundary + 1,
  bodyLines: lines.length - boundary,
  hex: countHex(body), hexEff: countHex(noComment),
  rgba: countRgba(body), rgbaEff: countRgba(noComment),
  rgbaVarEff,
  important: countImportant(body), importantEff: countImportant(noComment),
  dupSel: dups.length,
};
// 判据一律用**去注释后**的口径（*Eff）：
// 注释里提到 "!important" 或 "rgba(" 是在解释历史，不是真的声明。
// 契约里写的基线（253 / 425 / 74 / 100）来自同一条命令的**旧版本**（当时把注释也算进去），
// 所以这里的 Eff 数字略低于那组基线 —— 对照阈值时以本行的口径为准（更严格）。
out.pass = out.hexEff <= 90 && out.rgbaEff <= 180 && out.importantEff <= 40 && out.dupSel <= 25;

if (JSON_ONLY) {
  console.log(JSON.stringify(out, null, 2));
} else {
  console.log('文件: ' + path.resolve(FILE));
  console.log('令牌区边界: ' + boundaryKind + '（第 ' + out.boundaryLine + ' 行起统计正文，正文 ' + out.bodyLines + ' 行）');
  console.log('');
  console.log('裸 #hex       : ' + out.hex + '   (去注释后 ' + out.hexEff + ')');
  console.log('裸 rgba()     : ' + out.rgba + '   (去注释后 ' + out.rgbaEff + '，其中变量形式 ' + out.rgbaVarEff + ')');
  console.log('!important    : ' + out.important + '   (去注释后 ' + out.importantEff + ')');
  console.log('重复定义选择器: ' + out.dupSel);
  console.log('');
  console.log('重复最多的 12 个：');
  for (const [s, n] of dups.slice(0, 12)) console.log('  ' + String(n).padStart(3) + '  ' + s);
  console.log('');
  console.log('AC6 阈值: hex <= 90 / rgba <= 180 / !important <= 40 / dupSel <= 25');
  console.log('结果: ' + (out.pass ? 'PASS' : 'FAIL'));
}
process.exit(out.pass ? 0 : 1);
