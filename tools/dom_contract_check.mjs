#!/usr/bin/env node
/**
 * DOM 契约对账：找出「代码引用了，但页面上根本不存在」的 id。
 *
 * 为什么需要它：这个项目已经两次栽在同一个形状上 ——
 *   代码引用了一个不存在的 id → `getElementById` 返回 null → 被 `if (el)` 兜底吞掉
 *   → **不报错**，表现只是「点了没反应」（`#show-opponent-stats` 那次就是这个，
 *   排查花了很久）。多人/多轮改动时，id 还会各自漂移。
 *
 * 脚本做三件事：
 *   A. 计划/契约文档里冻结的 id（`docs/PROFILE_CARD_*_PLAN.md`，可选）必须真的存在
 *   B. `static/*.js` 里 getElementById / querySelector('#x') 引用的 id 必须存在 ——
 *      但会区分「运行期由 JS 自己创建」与「哪都没创建」两类，后者才是静默失效
 *   C. 一份「不许删」的旧 id 抽查清单
 *
 * 用法：node tools/dom_contract_check.mjs
 */
import fs from 'node:fs';
import path from 'node:path';

// 向上找到仓库根（含 templates/index.html 的那一层），脚本放哪都能跑
function findRoot(start) {
  let dir = start;
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(dir, 'templates', 'index.html'))) return dir;
    dir = path.resolve(dir, '..');
  }
  throw new Error('找不到仓库根（templates/index.html）');
}
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const ROOT = findRoot(HERE);

const HTML = path.join(ROOT, 'templates', 'index.html');
const JS_FILES = ['static/game.js', 'static/adaptive_layout.js', 'static/wallpaper.js',
  'static/music_player.js', 'static/sfx.js', 'static/magic_cards.js', 'static/test_magic.js'];
// 契约文档：默认取 docs/ 下最新的 *_PLAN.md（历史计划文档里的 id 早就不作数了），
// 也可以用 `--plan <文件名>` 指定
const DOCS = path.join(ROOT, 'docs');
const planArgIdx = process.argv.indexOf('--plan');
const PLAN = !fs.existsSync(DOCS) ? []
  : planArgIdx >= 0 && process.argv[planArgIdx + 1]
    ? [path.join(DOCS, process.argv[planArgIdx + 1])]
    : fs.readdirSync(DOCS).filter((f) => /_PLAN\.md$/.test(f))
      .map((f) => path.join(DOCS, f))
      .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)
      .slice(0, 1);

// 确实由 JS 在运行期创建、因此不该出现在 index.html 里的 id（B 段的兜底白名单）
const DYNAMIC = new Set(['chain-display', 'aux-dock', 'dock-tab-bar', 'effect-indicators']);

// 已核实的「悬空但无害」引用：留着当 WARN 打印（不隐藏），但不算失败，
// 免得一个已知的死引用把「新引入的悬空引用」这个信号淹掉。
const KNOWN_DEAD = new Map([
  ['custom-player-name', 'game.js:656 只赋值从不使用（自定义房昵称输入框早已移除），死代码'],
  ['test-magic-system', 'game.js:253 同上；test_magic.js 已从页面移除'],
  ['music-status', 'music_player.js:62 有 if 守卫，页面没这个状态位等于可选增强'],
]);

// C 段：这些 id 被 game.js 直接绑定，删掉就是静默失效
const MUST_KEEP = ['profile-form', 'profile-avatar', 'profile-username', 'profile-signature',
  'profile-save-msg', 'avatar-input', 'profile-modal-close', 'settings-modal-close',
  'primary-color-picker', 'music-volume', 'volume-display', 'music-loop-mode', 'music-toggle-play',
  'music-next', 'music-previous', 'music-muted', 'sfx-muted', 'current-track',
  'wp-section', 'wp-now-playing', 'wp-opacity', 'wp-opacity-display', 'wp-dim', 'wp-dim-display',
  'wp-blur', 'wp-blur-display', 'wp-fit', 'wp-scan', 'wp-toggle-play', 'wp-clear', 'wp-list',
  'wp-path', 'wp-path-import', 'wp-url', 'wp-url-import', 'wp-status', 'settings-save-btn',
  'change-password-form', 'old-password', 'new-password', 'change-password-msg',
  // 查看面 / 编辑面 / 它们的所有入口：这四个入口共用同一份渲染，删一个就是静默失效
  'opponent-stats-modal', 'opponent-stats-title', 'opponent-stats-content', 'opponent-stats-modal-close',
  'show-profile', 'show-opponent-stats', 'profile-modal', 'settings-modal',
  'match-detail-modal', 'match-detail-content', 'leaderboard-table'];

const read = (p) => fs.readFileSync(p, 'utf8');
const problems = [];
const warn = [];
const check = (ok, label, detail) => {
  if (!ok) problems.push(label + (detail ? '  ->  ' + JSON.stringify(detail) : ''));
};

const html = read(HTML);
const htmlIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));

// 收集静态 JS 里所有 id 引用（含引用位置，方便直接跳过去看）
const refs = new Map();
for (const rel of JS_FILES) {
  const p = path.join(ROOT, rel);
  if (!fs.existsSync(p)) continue;
  read(p).split(/\r?\n/).forEach((line, i) => {
    for (const re of [/getElementById\(\s*['"]([\w-]+)['"]/g,
      /querySelector(?:All)?\(\s*['"]#([\w-]+)/g]) {
      for (const m of line.matchAll(re)) {
        const id = m[1];
        if (!refs.has(id)) refs.set(id, []);
        refs.get(id).push(`${rel}:${i + 1}`);
      }
    }
  });
}

// 这个 id 有没有被 JS/模板自己创建出来？（`el.id = 'x'`、模板串里的 id="x"）
function createdAtRuntime(id) {
  const patterns = [`id="${id}"`, `id='${id}'`, `id = "${id}"`, `id = '${id}'`,
    `.id = '${id}'`, `.id = "${id}"`, `setAttribute('id', '${id}')`, `setAttribute("id", "${id}")`];
  for (const rel of JS_FILES.concat(['templates/index.html'])) {
    const p = path.join(ROOT, rel);
    if (!fs.existsSync(p)) continue;
    const src = read(p);
    if (patterns.some((pat) => src.includes(pat))) return true;
  }
  return false;
}

// ---------- A. 契约文档冻结的 id ----------
let planIdCount = 0;
let planRuntime = [];
if (PLAN.length === 0) {
  console.log('（未找到 docs/*_PLAN.md，跳过 A 段）');
} else {
  const planIds = new Set();
  const owners = new Map();      // id -> 出现在哪些契约文件里（报告里带出来，便于判断该不该现在就该有）
  for (const f of PLAN) {
    for (const m of read(f).matchAll(/#([A-Za-z][\w-]{2,})/g)) {
      planIds.add(m[1]);
      if (!owners.has(m[1])) owners.set(m[1], []);
      const base = path.basename(f);
      if (!owners.get(m[1]).includes(base)) owners.get(m[1]).push(base);
    }
  }
  planIdCount = planIds.size;
  // 契约里的 id 允许两种落地方式：写在 index.html 里，或由 JS 在运行期渲染出来
  // （名片卡片就是后者：`#profile-view*` 由 game.js 生成进 #opponent-stats-content）。
  // 两种都不算缺失；真正要抓的是「哪都没有」——那才是点了没反应。
  const absent = [...planIds].filter((id) => !htmlIds.has(id) && !DYNAMIC.has(id) && !createdAtRuntime(id));
  planRuntime = [...planIds].filter((id) => !htmlIds.has(id) && createdAtRuntime(id));
  // ⚠️ 报告里带出「这个 id 属于哪份契约文件」：多批计划并存时，未开工批次的 id 一定会被算进来，
  // 只有标出出处，看的人才知道「这是下一批的，不是本批漏了」。
  check(absent.length === 0,
    `A. 契约文档里的 id 都已经落地（index.html 或 JS 运行期渲染；缺 ${absent.length} 个）`,
    absent.map((id) => `${id} ← 来自 ${(owners.get(id) || ['?']).join(', ')}`));
}

// ---------- B. 代码引用的 id ----------
const missingRefs = [...refs.keys()].filter((id) => !htmlIds.has(id) && !DYNAMIC.has(id));
const runtimeMade = missingRefs.filter((id) => createdAtRuntime(id));
const danglingAll = missingRefs.filter((id) => !createdAtRuntime(id));
const dangling = danglingAll.filter((id) => !KNOWN_DEAD.has(id));
for (const id of danglingAll) {
  if (KNOWN_DEAD.has(id)) warn.push(`悬空但已核实无害：${id}（${KNOWN_DEAD.get(id)}）`);
}
check(dangling.length === 0, `B. 没有「哪都没创建」的悬空 id（${dangling.length} 个）`,
  dangling.map((id) => `${id} ← ${refs.get(id).join(', ')}`));

// ---------- C. 关键旧 id 抽查 ----------
const lost = MUST_KEEP.filter((id) => !htmlIds.has(id));
check(lost.length === 0, `C. 不许删的旧 id 一个都没丢（丢 ${lost.length} 个）`, lost);

// ---------- 输出 ----------
console.log(`index.html 里的 id 共 ${htmlIds.size} 个；静态 JS 引用 ${refs.size} 个` +
  (planIdCount ? `；契约文档冻结 ${planIdCount} 个` : ''));
if (runtimeMade.length) console.log(`（运行期动态创建、不算问题：${runtimeMade.length} 个）`);
if (planRuntime.length) console.log(`（契约里由 JS 运行期渲染的 id：${planRuntime.length} 个 —— 由 game.js 生成，不在 index.html 里）`);
for (const w of warn) console.log('WARN  ' + w);
if (problems.length) {
  console.log(`\n✗ ${problems.length} 项未通过：`);
  problems.forEach((p) => console.log('   · ' + p));
  process.exit(1);
}
console.log('\n✓ DOM 契约对账全部通过');
