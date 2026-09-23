#!/usr/bin/env node
/**
 * 回放棋盘的**逐格**契约检查 —— 不用浏览器、不用服务端，几秒钟。
 *
 * ## 为什么必须有它（本批的验收核心）
 *
 * 作者实报两条"某一格画错了"的问题，第 6 批的观战批已经证明
 * **只有逐格断言能抓**（"格子数量相等"永远抓不到方向/字形/标记丢失）：
 *
 *   ① 船格画成了 `✕`：`renderReplayBoard` 里写成
 *      `(cell.hasShip || cell.hit) ? '✕' : …` ⇒ **任何有船的格子都是叉**（那是"命中"的字形）。
 *   ② 双方已打过的格子**一个都画不出来**：`replayComputeFrame` 第 ③ 段的
 *      `var after = false; for (…) if (resetAt[side][m] <= i) { after = true; break; }`
 *      `if (!after) continue;` —— "**必须存在**一个 ≤ i 的重置才画这一炮"。
 *      而绝大多数局的 `board_resets` 是**空的** ⇒ `after` 恒 false ⇒ 每一炮都被丢掉。
 *      这是"方向写反"型 bug（CLAUDE.md 教训 #7）：旧的 E2E 验的是"拖拽 seek 与连点
 *      下一步自洽"（系统性丢标记也自洽）+ "船格 6/6 与后端相等"（船 ≠ 攻击标记），
 *      **没有任何一条断言要求攻击标记真的出现过**。本工具的第 1 组就是补这个缺口。
 *
 * ## 五组判据
 *
 *   A. **攻击标记必须真的出现过**（缺陷 ② 的正面判据，0 容差）：
 *      无重置的对局里，第 k 帧某块棋盘的标记集合 == "step ≤ k 且打向该棋盘的攻击步
 *      的 (x,y) 去重集合"。两块棋盘**各自非空且不相等**（都空 = 系统性丢标记）。
 *   B. **重置语义双向**：重置**之前**的标记必须消失、**之后**的必须还在
 *      （上一批**完全没测过**非空 `board_resets`）。含 `step == 重置点` 的边界两腿。
 *   C. **字形**：未挨炮的船格 = `⛴`（绝不是 `✕`）；命中/击沉 = `✕`；落空 = `○`。
 *   D. **效果格**：`effects` 时间线非空时那些格子必须带上正确的类名与文案，
 *      且 `step > k` 的效果**一格都不许出现**（时间线必须随时间走）；
 *      增量时间线里后来的行不许抹掉另一侧。
 *   E. **槽位 / 座位对齐 + `（你）`**（缺陷 ④）：槽位 i 的显示名必须等于
 *      座位 `replaySeatOf(i)` 的名字，`（你）` 与 `replay-board-mine` 跟着 `you_are` 走。
 *
 * ## 索引口径（**重要**）
 *
 * 后端 `replay._append` 是**顺序追加**的，所以 `steps[i].i === i` 恒成立，
 * 而帧解算读的是**数组下标**。本工具的夹具一律按这个口径造
 * （`atk(i, …)` 的第一个参数既是数组下标也是 `i`），别造"跳号"的 step。
 *
 * ## 用法
 *
 * `node tools/dom_replay_frame_check.mjs`
 *
 * 退出码：0 = 全绿；1 = 有失败项（逐条打印 FAIL）；2 = 加载失败。
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const ROOT = path.join(HERE, '..');
const GAME_JS = path.join(ROOT, 'static', 'game.js');

const problems = [];
let checks = 0;
function check(ok, label, detail) {
  checks++;
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label
    + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// ---------------------------------------------------------------------------
// 最小 DOM 桩（与 `dom_spectate_frame_check.mjs` 同一形状）：
// ⚠️ 不加 Proxy 之类的"全都当成功"的兜底 —— 那会把"画错了"变成静默通过。
// ⚠️ `el.className` 与 `el.classList` 必须是**同一份数据**（真实 DOM 就是这样），
//    拆成两个字段会让 `querySelectorAll('.cell')` 恒为 0（上批踩过，6 项假红）。
// ---------------------------------------------------------------------------
function makeEl(id) {
  const classes = new Set();
  const el = {
    id, children: [], dataset: {}, _text: '', _html: '', _cls: '', _attrs: {},
    classList: {
      add(...c) { c.forEach((x) => classes.add(x)); el._syncClassName(); },
      remove(...c) { c.forEach((x) => classes.delete(x)); el._syncClassName(); },
      toggle(c, on) {
        const want = (on === undefined) ? !classes.has(c) : !!on;
        want ? classes.add(c) : classes.delete(c);
        el._syncClassName();
      },
      contains(c) { return classes.has(c); },
    },
    _syncClassName() { el._cls = Array.from(classes).join(' '); },
    style: { setProperty() {}, removeProperty() {}, getPropertyValue() { return ''; } },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { return c; },
    setAttribute(k, v) { el._attrs[k] = v; }, getAttribute(k) { return el._attrs[k] ?? null; },
    removeAttribute(k) { delete el._attrs[k]; },
    addEventListener() {}, removeEventListener() {}, remove() {},
    querySelector() { return null; },
    querySelectorAll(sel) {
      const groups = String(sel).split(',').map((s) => s.trim()).filter(Boolean)
        .map((s) => s.split('.').filter(Boolean));
      return this.children.filter(
        (c) => groups.some((gs) => gs.every((g) => c.classList.contains(g))));
    },
    getContext() { return null; },
    focus() {}, blur() {}, click() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
    closest() { return null; }, contains() { return false; },
    get firstChild() { return this.children[0] || null; },
  };
  Object.defineProperty(el, 'textContent', {
    get() { return el._text; }, set(v) { el._text = v; el.children = []; },
  });
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html; }, set(v) { el._html = v; if (v === '') el.children = []; },
  });
  Object.defineProperty(el, 'className', {
    get() { return el._cls; },
    set(v) {
      classes.clear();
      String(v).split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
      el._syncClassName();
    },
  });
  return el;
}

/** 造一个**独立**的 sandbox（`--dump-before` 要在第二个 vm 里跑改回缺陷的源码，
    ⚠️ 复用同一个 sandbox 对象会 `SyntaxError: Identifier 'x' has already been declared`
    —— agent 全局对象被前后两份源码共享，`const` 只声明一次）。 */
function makeSandbox() {
  const getEl2 = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
  const s = {
    console,
    document: Object.assign({}, documentStub, { getElementById: getEl2 }),
    navigator: { userAgent: 'node' },
    location: { href: 'http://127.0.0.1/', origin: 'http://127.0.0.1', search: '', hash: '' },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    sessionStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    requestAnimationFrame: () => 0, cancelAnimationFrame: () => {},
    setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    io: () => ({ on: () => {}, emit: () => {}, connected: true, id: 'x' }),
    alert: () => {},
    Audio: function () { return { play: () => {}, pause: () => {}, cloneNode() { return this; } }; },
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    innerWidth: 1600, innerHeight: 1000, devicePixelRatio: 1,
    Image: function () { return {}; },
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    WebSocket: function () {}, Notification: function () {},
  };
  s.window = s;
  s.globalThis = s;
  s.self = s;
  s.addEventListener = () => {};
  s.removeEventListener = () => {};
  s.dispatchEvent = () => true;
  return s;
}

const els = new Map();
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };

const documentStub = {
  getElementById: getEl,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: (t) => makeEl('<' + t + '>'),
  addEventListener: () => {}, removeEventListener: () => {},
  body: makeEl('body'), documentElement: makeEl('html'), head: makeEl('head'),
  readyState: 'complete', cookie: '', hidden: false,
};

const sandbox = makeSandbox();

if (!fs.existsSync(GAME_JS)) { console.error('找不到 static/game.js'); process.exit(2); }
const SRC = fs.readFileSync(GAME_JS, 'utf8');
const ctx = vm.createContext(sandbox);
try {
  vm.runInContext(SRC, ctx, { filename: 'game.js' });
} catch (e) {
  console.error('game.js 加载失败: ' + (e && e.stack));
  process.exit(2);
}

// ---------------------------------------------------------------------------
// 在 vm 里驱动**真的** `replayComputeFrame` / `renderReplayBoard`
// ---------------------------------------------------------------------------
/** 把一份 payload 与帧号交给真的帧解算 + 真的渲染，再读回两块棋盘上每一格的样子。 */
function frameAt(payload, k) {
  const script = `(function () {
    replayState.payload = ${JSON.stringify(payload)};
    replayState.youAre = null;
    var frame = replayComputeFrame(replayState.payload, ${k});
    replayState.frame = frame;
    for (var index = 0; index < replayBoardEls.length; index++) {
      if (replayBoardEls[index]) replayBoardEls[index].innerHTML = '';
    }
    renderReplayBoards();
    var out = [];
    for (var s = 0; s < replayBoardEls.length; s++) {
      var el = replayBoardEls[s];
      var cells = el ? el.querySelectorAll('.cell') : [];
      var rows = [];
      for (var i = 0; i < cells.length; i++) {
        var c = cells[i];
        rows.push({
          x: c.dataset.x, y: c.dataset.y,
          text: c.textContent || '',
          title: c.title || '',
          aria: c.getAttribute('aria-label') || '',
          cls: c.className,
          ship: c.classList.contains('ship'),
          hit: c.classList.contains('hit'),
          miss: c.classList.contains('miss'),
          sunk: c.classList.contains('sunk'),
          shielded: c.classList.contains('shielded'),
          hole: c.classList.contains('shenwei-hole'),
          frozen: c.classList.contains('frozen-area'),
          laststand: c.classList.contains('last-stand-candidate')
        });
      }
      out.push(rows);
    }
    return { boards: out, marks: frame.marks, resetAt: frame.resetAt };
  })()`;
  return vm.runInContext(script, ctx, { filename: 'frame.js' });
}

/** 用**当前 ctx**（= 真正那一份 game.js）把某份 payload 的第 K 帧渲染出来并读回每格。 */
function readRendered(payload, K) {
  return vm.runInContext(`(function () {
    replayState.payload = ${JSON.stringify(payload)};
    replayState.frame = replayComputeFrame(replayState.payload, ${K});
    for (var b = 0; b < replayBoardEls.length; b++) {
      if (replayBoardEls[b]) replayBoardEls[b].innerHTML = '';
    }
    renderReplayBoards();
    var out = [];
    for (var s = 0; s < replayBoardEls.length; s++) {
      var rows = [];
      var cells = replayBoardEls[s] ? replayBoardEls[s].querySelectorAll('.cell') : [];
      for (var c = 0; c < cells.length; c++) {
        rows.push({ cls: cells[c].className, text: cells[c].textContent || '',
                    title: cells[c].title || '' });
      }
      out.push(rows);
    }
    return out;
  })()`, ctx, { filename: 'read_rendered.js' });
}

const cellAt = (rows, x, y) => rows.find((c) => c.x === String(x) && c.y === String(y));

/** 棋盘上"带攻击标记"的格集合（`hit` 或 `miss`）—— 与后端推出来的集合比对。 */
const markedSet = (rows) => JSON.stringify(rows
  .filter((c) => c.hit || c.miss)
  .map((c) => c.x + ',' + c.y + ',' + (c.sunk ? 'S' : (c.hit ? 'H' : 'M'))).sort());

/** 形状与服务端 `replay.py` 的 `build()` 输出一致的最小 payload 构造器。 */
function mkPayload(opts) {
  const o = opts || {};
  return {
    version: 1,
    p1_name: o.p1_name || '甲',
    p2_name: o.p2_name || '乙',
    seats: o.seats || {},
    started_at: 0,
    steps: o.steps || [],
    ships: o.ships || [],
    hands: o.hands || [],
    effects: o.effects || [],
    board_resets: o.board_resets || [],
    nodes: [],
    truncated: null,
  };
}

/**
 * 造一个 attack 步。`i` **必须等于它在 `steps` 数组里的下标**（后端顺序追加，
 * 帧解算也按下标取）。
 */
function atk(i, attacker, x, y, hit, sunk) {
  return {
    i, kind: 'attack', actor: attacker === 'p1' ? '甲' : '乙', text: '第 ' + i + ' 步',
    detail: { attacker, target: { x, y }, hit: !!hit, ship_sunk: !!sunk },
  };
}

// 效果行的参考形状（与后端 `_EFFECT_FIELDS` 同形状；每条都要带全部字段 —— 替换语义）。
const NO_EFFECT = { shield: [], shenwei_holes: [], frozen_area: null,
                    last_stand_cells: [], last_stand_owner: null };

// ★ D 组用的那份"有效果"的 payload 提到**模块作用域**：`--dump` 也要用它。
//   ⚠️ 第一版把它留在 D 组的块作用域里，`--dump` 直接 `ReferenceError: effPayload is not defined`
//      —— 这正是 CLAUDE.md 教训 #6（模块级函数不许引用函数/块作用域里的东西）。
const effPayload = mkPayload({
  steps: [
    atk(0, 'p1', 0, 0, true, false),
    atk(1, 'p2', 5, 5, true, false),
    atk(2, 'p1', 1, 0, false, false),
  ],
  ships: [{ step: 0,
            p1: [{ x: 1, y: 1, alive: true }],
            p2: [{ x: 0, y: 4, alive: true }, { x: 5, y: 5, alive: true }] }],
  effects: [
    { step: 0, p1: Object.assign({}, NO_EFFECT, { shield: [[1, 1]] }) },
    { step: 2, p2: Object.assign({}, NO_EFFECT, {
      shenwei_holes: [{ x1: 0, y1: 4, x2: 2, y2: 5 }],
      frozen_area: { x1: 3, y1: 0, x2: 5, y2: 2, owner: 'p2', frozen: 1 },
      last_stand_cells: [[5, 3]], last_stand_owner: 'p2' }) },
  ],
});

// ===========================================================================
// A. 攻击标记必须真的出现过（缺陷 ② 的正面判据）
// ===========================================================================
// 一局**没有重置**的对局：p1 打 {(0,0) 命中, (1,1) 落空}，p2 打 {(4,4) 命中}。
// ⚠️ 双方打不同格：打同一批格时"画到哪块棋盘"与"两块都对调"结果相同，测不出来。
// ⚠️ p1/p2 的格集**互不相交**，且都非空 —— 这是第 6 批定下的前置。
// ⚠️ 船位时间线只在 step 0 记一条（这才是后端的真实形状），所以断言取 k ≥ 1
//    （与 R4 那条"第 0 帧手牌本来就是空的"同族）。
const noReset = mkPayload({
  steps: [
    atk(0, 'p1', 0, 0, true, false),
    atk(1, 'p2', 4, 4, true, false),
    atk(2, 'p1', 1, 1, false, false),
  ],
  ships: [
    { step: 0,
      p1: [{ x: 4, y: 4, alive: true }, { x: 2, y: 2, alive: true }],
      p2: [{ x: 0, y: 0, alive: true }, { x: 2, y: 3, alive: true }] },
  ],
  board_resets: [],
});

console.log('--- A. 无重置对局：攻击标记必须出现（缺陷 ② 的正面判据）---');
{
  const k1 = frameAt(noReset, 1);
  check(markedSet(k1.boards[0]) === JSON.stringify(['4,4,H']),
    '★ k=1：第 1 块棋盘（p1 那块）有 p2 打的那一格',
    { dom: markedSet(k1.boards[0]), want: ['4,4,H'] });
  check(markedSet(k1.boards[1]) === JSON.stringify(['0,0,H']),
    '★ k=1：第 2 块棋盘（p2 那块）有 p1 打的那一格',
    { dom: markedSet(k1.boards[1]), want: ['0,0,H'] });
}
{
  const k2 = frameAt(noReset, 2);
  check(markedSet(k2.boards[1]) === JSON.stringify(['0,0,H', '1,1,M'].sort()),
    '★★ k=2：p2 那块棋盘上 == p1 打出的**全部**格（去重集合逐格相等）',
    { dom: markedSet(k2.boards[1]), want: ['0,0,H', '1,1,M'] });
  check(markedSet(k2.boards[0]) === JSON.stringify(['4,4,H']),
    '★★ k=2：p1 那块棋盘上 == p2 打出的格（一格不多、一格不少）',
    { dom: markedSet(k2.boards[0]), want: ['4,4,H'] });
  // ★★ 这条是"方向写反"的**点名判据**：两块棋盘上的标记集合必须**各自非空且不同**
  //    （系统性丢标记 = 两边都空；两块对调 = 集合互换，都会在这里红）。
  const b1 = JSON.parse(markedSet(k2.boards[0]));
  const b2 = JSON.parse(markedSet(k2.boards[1]));
  check(b1.length > 0 && b2.length > 0 && JSON.stringify(b1) !== JSON.stringify(b2),
    '★★ 两块棋盘的标记**各自非空且不相等**（系统性丢标记 = 两边都空，会在这里红）',
    { b1, b2 });
}

// ===========================================================================
// B. 重置语义双向（上一批**完全没测过**非空 board_resets）
// ===========================================================================
console.log('--- B. 棋盘重置：之前的标记必须消失、之后的必须还在 ---');
{
  // step 0/1 p1 打 p2 那块；step 2 时 p2 那块被重置（灵气复苏/败者食尘）；
  // step 3 p1 再打 (2,2)，step 4 p2 打 p1 那块。
  const resetPayload = mkPayload({
    steps: [
      atk(0, 'p1', 0, 0, true, false),
      atk(1, 'p1', 1, 1, false, false),
      atk(2, 'p2', 5, 5, true, false),
      atk(3, 'p1', 2, 2, true, false),
      atk(4, 'p2', 4, 4, true, false),
    ],
    ships: [{ step: 0, p1: [{ x: 0, y: 0, alive: true }], p2: [{ x: 5, y: 5, alive: true }] }],
    // `side` = **哪一块棋盘被重置**（不是发起方）
    board_resets: [{ step: 2, side: 'p2' }],
  });
  const before = frameAt(resetPayload, 1);
  check(markedSet(before.boards[1]) === JSON.stringify(['0,0,H', '1,1,M'].sort()),
    '★ 重置**之前**（k=1）：p2 那块棋盘上该有 p1 打过的格',
    { dom: markedSet(before.boards[1]), want: ['0,0,H', '1,1,M'] });
  const after = frameAt(resetPayload, 4);
  const got = JSON.parse(markedSet(after.boards[1]));
  check(got.indexOf('2,2,H') >= 0,
    '★★ 重置**之后**的炮必须还在（k=4 有 (2,2)）', { dom: got });
  check(got.indexOf('0,0,H') < 0 && got.indexOf('1,1,M') < 0,
    '★★ 重置**之前**的标记必须消失（重置把那一块擦干净了）',
    { dom: got, 不该出现: ['0,0,H', '1,1,M'] });
  const other = JSON.parse(markedSet(after.boards[0]));
  check(other.length === 2 && other.indexOf('5,5,H') >= 0 && other.indexOf('4,4,H') >= 0,
    '★ 重置只清**被重置那一侧**：另一块棋盘上的两炮都不许跟着消失', { dom: other });
}
{
  // 边界两腿：`i <= lastReset` 用 ≤，不是 <
  //   ① step **早于**重置点的那一炮必须被擦掉；
  //   ② step **晚于**重置点的那一炮必须活下来（避免把边界写成"重置后全丢"）。
  //   ⚠️ 第一版夹具把"重置点那一炮"造成**防守方**打的（p2 打 p2 那块），
  //      于是它本来就不该出现在这块棋盘上 —— 判据假红（工具自己的 bug）。
  //      重置必须夹在两炮**中间**才测得出边界。
  const edge = mkPayload({
    steps: [
      atk(0, 'p1', 3, 3, true, false),      // 重置之前
      atk(1, 'p2', 5, 5, true, false),      // 重置这一步（棋盘被擦）
      atk(2, 'p1', 3, 4, false, false),     // 重置之后
    ],
    board_resets: [{ step: 1, side: 'p2' }],
  });
  const e2 = frameAt(edge, 2);
  check(markedSet(e2.boards[1]) === JSON.stringify(['3,4,M']),
    '★★ 边界：重置**之前**的炮被擦掉、**之后**的炮活下来（用 ≤，不是 <）',
    { dom: markedSet(e2.boards[1]), want: ['3,4,M'],
      不该出现: '3,3,H（step 0 < 重置点 1 ⇒ 属于重置之前）' });
  check(markedSet(e2.boards[0]) === JSON.stringify(['5,5,H']),
    '★ 边界：另一块棋盘上的 (5,5) 不受这次重置影响（重置只作用于 `side`）',
    { dom: markedSet(e2.boards[0]) });
  // 反向腿：把重置点挪到**这一帧之后**，两炮就必须都在
  // （证明上面那条不是"永远不画那块棋盘"的假绿）
  const edge2 = mkPayload({
    steps: [
      atk(0, 'p1', 3, 3, true, false),
      atk(1, 'p2', 5, 5, true, false),
      atk(2, 'p1', 3, 4, false, false),
    ],
    board_resets: [{ step: 3, side: 'p2' }],
  });
  check(markedSet(frameAt(edge2, 2).boards[1]) === JSON.stringify(['3,3,H', '3,4,M'].sort()),
    '★★ 边界反向腿：重置点在 k 之后 ⇒ 两炮都必须还在',
    { dom: markedSet(frameAt(edge2, 2).boards[1]) });
}
{
  // ★ 同一块棋盘**被重置两次**：只保留"最后那次重置之后的炮"。
  //   这条是给"取最大值"那句代码定向的 —— 取最小（= 最早那次）会让
  //   第二次重置之后、（按最早重置算）也算"之后"的炮**多画出来**，
  //   而只有 ≥2 次重置的夹具才抓得到它（单次重置时 max == min，测不出来）。
  const twice = mkPayload({
    steps: [
      atk(0, 'p1', 0, 5, true, false),      // 第 1 次重置之前
      atk(1, 'p2', 1, 1, false, false),     // 第 1 次重置这一步
      atk(2, 'p1', 2, 5, true, false),      // 两次重置之间 ← 必须被第 2 次重置擦掉
      atk(3, 'p2', 1, 2, false, false),     // 第 2 次重置这一步
      atk(4, 'p1', 4, 5, false, false),     // 最后一次重置之后 ← 必须还在
    ],
    board_resets: [{ step: 1, side: 'p2' }, { step: 3, side: 'p2' }],
  });
  const afterTwice = frameAt(twice, 4);
  check(markedSet(afterTwice.boards[1]) === JSON.stringify(['4,5,M']),
    '★★ 一块棋盘被重置两次时，只保留**最后一次**重置之后的炮（取 max，不是 min）',
    { dom: markedSet(afterTwice.boards[1]), want: ['4,5,M'],
      不该出现: ['0,5,H（第 1 次重置前）', '2,5,H（两次重置之间）'] });
}

// ===========================================================================
// C. 字形：未挨炮的船格 = ⛴（绝不是 ✕）、命中 = ✕、落空 = ○
// ===========================================================================
console.log('--- C. 字形（缺陷 ①）---');
{
  const f = frameAt(noReset, 2);
  const plainShip = cellAt(f.boards[0], 2, 2);       // p1 那块：有船、没挨过炮
  const hitShip = cellAt(f.boards[0], 4, 4);         // p1 那块：有船 + 被命中
  const missCell = cellAt(f.boards[1], 1, 1);        // p2 那块：没船 + 落空
  const water = cellAt(f.boards[1], 3, 3);           // p2 那块：空海
  check(!!plainShip && plainShip.text === '⛴',
    '★★ 未挨炮的船格画成船（不是 ✕）', plainShip && { text: plainShip.text, cls: plainShip.cls });
  check(!!plainShip && plainShip.text !== '✕',
    '★★ 未挨炮的船格**绝不是** ✕（这条就是作者实报的那一格）',
    plainShip && plainShip.text);
  check(!!plainShip && plainShip.ship && !plainShip.hit,
    '★ 未挨炮的船格的类名是 `ship`（不含 `hit`）', plainShip && plainShip.cls);
  check(!!hitShip && hitShip.text === '✕',
    '★★ 命中格画成 ✕', hitShip && { text: hitShip.text, cls: hitShip.cls });
  check(!!missCell && missCell.text === '○',
    '★★ 落空格画成 ○', missCell && { text: missCell.text, cls: missCell.cls });
  check(!!water && water.text === '',
    '★ 没船也没打过的格是空的（不画字形）', water && { text: water.text, cls: water.cls });
  check(!!plainShip && plainShip.title.indexOf('战舰') >= 0
    && plainShip.title.indexOf('还没被打到') >= 0,
    '★ 未挨炮的船格的 title 写明"有船、还没被打到"', plainShip && plainShip.title);
  check(!!hitShip && hitShip.title.indexOf('命中') >= 0,
    '★ 命中格的 title 写明"命中"', hitShip && hitShip.title);
  check(!!plainShip && plainShip.aria === plainShip.title && plainShip.aria.length > 0,
    '★ aria-label 与 title 同口径（读屏用户拿到的是同一条）',
    plainShip && { title: plainShip.title, aria: plainShip.aria });

  // 击沉：船 + 命中 + sunk ⇒ 仍然是 ✕（打沉的那一炮本身就是命中）
  const sunkPayload = mkPayload({
    steps: [atk(0, 'p1', 0, 0, true, true)],
    ships: [{ step: 0, p1: [], p2: [{ x: 0, y: 0, alive: false, sunk: true }] }],
  });
  const sunkCell = cellAt(frameAt(sunkPayload, 0).boards[1], 0, 0);
  check(!!sunkCell && sunkCell.text === '✕' && sunkCell.sunk && sunkCell.hit,
    '★ 击沉格 = ✕ + `ship sunk hit`', sunkCell && { text: sunkCell.text, cls: sunkCell.cls });
  check(!!sunkCell && sunkCell.title.indexOf('击沉') >= 0,
    '★ 击沉格的 title 写明"击沉"', sunkCell && sunkCell.title);
}

// ===========================================================================
// D. 效果格（缺陷 ③）：类名 + 文案 + **随时间线变化**
// ===========================================================================
console.log('--- D. 效果格（护盾 / 神威洞 / 冻结区 / 绝处逢生）---');
{
  // effects 时间线是**稀疏 + 增量**：step 0 只带 p1（护盾），step 2 只带 p2（其余三个）。
  // （payload 本身在模块作用域，见上面 `effPayload` —— `--dump` 也要用同一份。）

  // k=1：只有护盾格（p1 侧），p2 侧的效果**一格都不许出现**
  const e1 = frameAt(effPayload, 1);
  const shieldCell = cellAt(e1.boards[0], 1, 1);
  check(!!shieldCell && shieldCell.shielded,
    '★★ k=1：护盾格带 `shielded` 类（仁王之盾/卧薪尝胆）',
    shieldCell && { cls: shieldCell.cls });
  check(!!shieldCell && shieldCell.text === '⛴',
    '★ 护盾格若同时有船，字形仍是船（效果与字形互不覆盖）',
    shieldCell && shieldCell.text);
  check(!!shieldCell && shieldCell.title.indexOf('护盾') >= 0,
    '★ 护盾格的 title 写明护盾', shieldCell && shieldCell.title);
  const holeEarly = cellAt(e1.boards[1], 0, 4);
  check(!!holeEarly && !holeEarly.hole,
    '★★ k=1：`step > k` 的神威洞**一格都不许出现**（时间线必须随时间走）',
    holeEarly && { cls: holeEarly.cls });
  const frozenEarly = cellAt(e1.boards[1], 3, 0);
  check(!!frozenEarly && !frozenEarly.frozen,
    '★★ k=1：`step > k` 的冻结区一格都不许出现', frozenEarly && { cls: frozenEarly.cls });
  const standEarly = cellAt(e1.boards[1], 5, 3);
  check(!!standEarly && !standEarly.laststand,
    '★★ k=1：`step > k` 的绝处逢生候选格一格都不许出现', standEarly && { cls: standEarly.cls });

  // k=2：p2 侧的效果出现了
  const e2 = frameAt(effPayload, 2);
  const hole = cellAt(e2.boards[1], 0, 4);
  check(!!hole && hole.hole, '★★ k=2：神威洞的格子带上 `shenwei-hole` 类', hole && { cls: hole.cls });
  check(!!hole && hole.text === '⛴',
    '★★ 神威洞里的**船**仍然看得见（洞不能把船盖掉）', hole && { text: hole.text });
  check(!!hole && hole.title.indexOf('神威') >= 0,
    '★ 神威洞的 title 写明是神威', hole && hole.title);
  const holeEdge = cellAt(e2.boards[1], 2, 5);        // 区域内
  const holeOut = cellAt(e2.boards[1], 3, 5);        // 区域外（x2=2）
  check(!!holeEdge && holeEdge.hole && !!holeOut && !holeOut.hole,
    '★★ 神威洞只覆盖它自己的矩形（(2,5) 在内、(3,5) 在外）',
    { 内: holeEdge && holeEdge.cls, 外: holeOut && holeOut.cls });
  const frozen = cellAt(e2.boards[1], 3, 0);
  const frozenOut = cellAt(e2.boards[1], 5, 4);      // y2=2 ⇒ (5,4) 在外
  check(!!frozen && frozen.frozen && !!frozenOut && !frozenOut.frozen,
    '★★ 冻结区只覆盖它自己的矩形（(3,0) 在内、(5,4) 在外）',
    { 内: frozen && frozen.cls, 外: frozenOut && frozenOut.cls });
  check(!!frozen && frozen.title.indexOf('冻结') >= 0,
    '★ 冻结区的 title 写明冻结', frozen && frozen.title);
  const stand = cellAt(e2.boards[1], 5, 3);
  check(!!stand && stand.laststand && stand.title.indexOf('绝处逢生') >= 0,
    '★★ 绝处逢生的候选格带 `last-stand-candidate` 且有文案',
    stand && { cls: stand.cls, title: stand.title });
  check(!!stand && !stand.hit && stand.text === '',
    '★ 候选格若还没被打过，不许长出攻击标记（效果 ≠ 已轰过）',
    stand && { cls: stand.cls, text: stand.text });
  // 护盾那一侧在 k=2 **仍然**在（增量：p2 那条不许把 p1 的效果抹掉）
  const shieldStill = cellAt(e2.boards[0], 1, 1);
  check(!!shieldStill && shieldStill.shielded,
    '★★ k=2：p1 的护盾格仍在（增量时间线：后来的行不许抹掉另一侧）',
    shieldStill && { cls: shieldStill.cls });
}

// ===========================================================================
// E. 座位口径：槽位 i 的显示名必须等于座位 replaySeatOf(i) 的名字
// ===========================================================================
console.log('--- E. 槽位 / 座位对齐 + `（你）`（缺陷 ④）---');
{
  // 站在**败者**的视角：`you_are = 'p2'`，而 p2 的名字是"小小弈11"（不是 p1）。
  const payload = mkPayload({
    p1_name: 'AI', p2_name: '小小弈11',
    steps: [atk(0, 'p1', 0, 0, true, false)],
    ships: [{ step: 0, p1: [{ x: 0, y: 0, alive: true }], p2: [{ x: 3, y: 3, alive: true }] }],
  });
  const renderPlayers = (youAre) => vm.runInContext(`(function () {
    replayState.payload = ${JSON.stringify(payload)};
    replayState.frame = replayComputeFrame(replayState.payload, 0);
    replayState.youAre = ${JSON.stringify(youAre)};
    renderReplayPlayers();
    return {
      names: [
        document.getElementById('replay-name-1').textContent,
        document.getElementById('replay-name-2').textContent
      ],
      b1title: document.getElementById('replay-board-title-1').textContent,
      b2title: document.getElementById('replay-board-title-2').textContent,
      mine1: document.getElementById('replay-board-1').classList.contains('replay-board-mine'),
      mine2: document.getElementById('replay-board-2').classList.contains('replay-board-mine')
    };
  })()`, ctx, { filename: 'players.js' });

  const asP2 = renderPlayers('p2');
  check(asP2.names[0].indexOf('AI') === 0 && asP2.names[0].indexOf('（你）') < 0,
    '★★ 第 1 槽位 = p1 的名字「AI」，且**不带**（你）', asP2.names[0]);
  check(asP2.names[1].indexOf('小小弈11') === 0 && asP2.names[1].indexOf('（你）') >= 0,
    '★★ 第 2 槽位 = p2 的名字「小小弈11」，且**带**（你）', asP2.names[1]);
  check(asP2.b1title.indexOf('AI') === 0 && asP2.b2title.indexOf('小小弈11') === 0,
    '★★ 槽位 i 的**显示名 == 座位 replaySeatOf(i) 的名字**（两处口径一一对齐）',
    { b1: asP2.b1title, b2: asP2.b2title });
  check(asP2.mine1 === false && asP2.mine2 === true,
    '★★ `replay-board-mine` 只挂在 p2 那一侧（作者实报：原来挂到了 AI 上）',
    { mine1: asP2.mine1, mine2: asP2.mine2 });

  // 反向腿：换成 p1 视角，两处必须**同时**翻过来（否则就是"永远标左边"的假绿）
  const asP1 = renderPlayers('p1');
  check(asP1.names[0].indexOf('（你）') >= 0 && asP1.names[1].indexOf('（你）') < 0,
    '★★ 反向腿：you_are=p1 时（你）落在第 1 槽位（不是"永远标左边"的假绿）', asP1.names);
  check(asP1.mine1 === true && asP1.mine2 === false,
    '★ 反向腿：`replay-board-mine` 跟着翻到 p1 那一侧', { mine1: asP1.mine1, mine2: asP1.mine2 });

  // 旁观者（you_are = null）：两边都不许带（你），也不许有 mine
  const asNone = renderPlayers(null);
  check(asNone.names.every((n) => n.indexOf('（你）') < 0)
    && asNone.mine1 === false && asNone.mine2 === false,
    '★★ 反向腿：you_are 为空（旁观者）时两边都不带（你）', asNone.names);
}

// ---------------------------------------------------------------------------
// 可选：把**这一份 payload 的某一帧**渲染成一张静态 HTML（人工看一眼 / 截图留证）。
// `node tools/dom_replay_frame_check.mjs --dump out.html 3` —— 不传就一个文件都不写。
// 用它截图是本批"改前/改后长什么样"最省事的证据来源（不依赖服务端与浏览器）。
// ---------------------------------------------------------------------------
/** 把一份"每格渲染结果"写成静态 HTML（`--dump` 与 `--dump-before` 共用）。 */
function writeDump(file, snap, K, caption) {
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const html = '<!doctype html><meta charset="utf-8">'
    + '<title>重放棋盘 k=' + K + '</title>'
    + '<style>body{background:#0b2135;color:#cfe3f5;font:14px/1.6 system-ui;padding:24px}'
    + 'h2{font-size:15px;font-weight:600;margin:0 0 4px}'
    + 'p{color:#8fb4d4;margin:0 0 16px}'
    + '.wrap{display:flex;flex-wrap:wrap;gap:24px}'
    + '.b{display:inline-grid;grid-template-columns:repeat(6,44px);gap:2px}'
    + '.cell{width:44px;height:44px;display:flex;align-items:center;justify-content:center;'
    + 'background:#14324f;border:1px solid #2b5a86;border-radius:4px;color:#eaf3fb;font-size:20px}'
    + '.cell.ship{background:#6b5a41;border-color:#5d4f3c}'
    + '.cell.hit{background:#7d2b2b;border-color:#a33}'
    + '.cell.miss{background:#1c3f5e;color:#9fc4e0}'
    + '.cell.replay-water{background:#0f2a42}'
    + '.cell.shielded{box-shadow:inset 0 0 0 3px #38bdf8}'
    + '.cell.shenwei-hole{background:repeating-linear-gradient(45deg,#0c0c0c 0 6px,#2a2a2a 6px 12px)}'
    + '.cell.frozen-area{box-shadow:inset 0 0 0 3px #60a5fa;background:#153a5e}'
    + '.cell.last-stand-candidate{box-shadow:inset 0 0 0 3px #ffc400}'
    + '</style>'
    + '<h2>第 ' + K + ' 帧 · 左 = p1 那块棋盘，右 = p2 那块 · ' + esc(caption) + '</h2>'
    + '<p>船 = ⛴（没挨过炮）／命中与击沉 = ✕／落空 = ○；'
    + '效果格用描边与斜纹表达（护盾、神威洞、冻结区、绝处逢生候选格）。</p><div class="wrap">'
    + snap.map(function (rows) {
      return '<div class="b">' + rows.map(function (c) {
        return '<div class="' + esc(c.cls) + '" title="' + esc(c.title) + '">'
          + esc(c.text) + '</div>';
      }).join('') + '</div>';
    }).join('') + '</div>';
  fs.writeFileSync(file, html, 'utf8');
  console.log('已写出静态快照: ' + file + '（' + caption + '）');
}

{
  const di = process.argv.indexOf('--dump');
  if (di >= 0 && process.argv[di + 1]) {
    const K = (di + 2 < process.argv.length) ? Number(process.argv[di + 2]) : 3;
    const snap = readRendered(effPayload, K);
    writeDump(process.argv[di + 1], snap, K, '修复后');
  }
}

// ---------------------------------------------------------------------------
// 可选 `--dump-before out.html K`：把**修复前**的两条逻辑在**内存里**改回去，
// 用同一份 payload 渲染一张静态快照，用来做"改前 vs 改后长什么样"的对照证据。
// ⚠️ **只改内存里的源码副本**（`vm` 里重新求值），磁盘上的 `static/game.js`
//    一个字节都不动 —— 所以它不会把工作树弄脏，也不会让"绿/红"结论失真。
//    两处改动就是缺陷 ① 与缺陷 ② 的原始写法（见本文件头部的说明）。
// ---------------------------------------------------------------------------
{
  const bi = process.argv.indexOf('--dump-before');
  if (bi >= 0 && process.argv[bi + 1]) {
    const K = (bi + 2 < process.argv.length) ? Number(process.argv[bi + 2]) : 3;
    const FIXED_GLYPH = "        if (item.cell.sunk || item.cell.hit) el.textContent = '✕';\n"
      + "        else if (item.cell.hasShip) el.textContent = '⛴';\n"
      + "        else if (item.cell.miss) el.textContent = '○';\n"
      + "        else el.textContent = '';";
    const OLD_GLYPH = "        el.textContent = (item.cell.hasShip || item.cell.hit)"
      + " ? '✕' : (item.cell.miss ? '○' : '');";
    const FIXED_MARK = '        if (i <= lastReset[boardSide]) continue;';
    const OLD_MARK = '        var after = false;\n'
      + '        var marks = frame.resetAt[boardSide];\n'
      + '        for (var m = 0; m < marks.length; m++) {\n'
      + '            if (marks[m] <= i) { after = true; break; }\n'
      + '        }\n'
      + '        if (!after) continue;';
    const nl = SRC.includes('\r\n') ? '\r\n' : '\n';
    const toHouse = (t) => t.replace(/\r?\n/g, nl);
    let old = SRC;
    let patched = 0;
    for (const [from, to] of [[FIXED_GLYPH, OLD_GLYPH], [FIXED_MARK, OLD_MARK]]) {
      const f = toHouse(from);
      if (old.includes(f)) { old = old.replace(f, toHouse(to)); patched++; }
    }
    if (patched !== 2) {
      console.error('--dump-before 只改到了 ' + patched + '/2 处（源码变了？）');
      process.exit(2);
    }
    const beforeCtx = vm.createContext(makeSandbox());
    vm.runInContext(old, beforeCtx, { filename: 'game.before.js' });
    const snap = vm.runInContext(`(function () {
      replayState.payload = ${JSON.stringify(effPayload)};
      replayState.frame = replayComputeFrame(replayState.payload, ${K});
      for (var b = 0; b < replayBoardEls.length; b++) {
        if (replayBoardEls[b]) replayBoardEls[b].innerHTML = '';
      }
      renderReplayBoards();
      var out = [];
      for (var s = 0; s < replayBoardEls.length; s++) {
        var rows = [];
        var cells = replayBoardEls[s] ? replayBoardEls[s].querySelectorAll('.cell') : [];
        for (var c = 0; c < cells.length; c++) {
          rows.push({ cls: cells[c].className, text: cells[c].textContent || '',
                      title: cells[c].title || '' });
        }
        out.push(rows);
      }
      return out;
    })()`, beforeCtx, { filename: 'dump_before.js' });
    writeDump(process.argv[bi + 1], snap, K, '修复前（内存里改回缺陷 ①② 的原写法）');
  }
}

console.log('');
console.log(problems.length
  ? ('FAILED  ' + problems.length + '/' + checks + ' 项')
  : ('OK  ' + checks + ' 项全绿'));
process.exit(problems.length ? 1 : 0);
