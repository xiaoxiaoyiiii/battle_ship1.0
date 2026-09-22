#!/usr/bin/env node
/**
 * 观战棋盘**方向**的逐格契约检查（第 6 批）—— 不用浏览器、不用服务端，几秒钟。
 *
 * ## 为什么必须有它（作者实报的死角 A）
 *
 * 观战棋盘只有**一处**"座位方向 → 棋盘方向"的转置：
 * `spectateRebuildBoardAttacks()`（`board_attacks[p1] = attacks[p2]`）。
 * 服务端有**两条**路径把棋盘数据送到前端：
 *
 *   A. 进席快照 `spectate_sync.sides[label].attacks`（`applySpectateSnapshot`）
 *   B. 实时帧   `spectate_board.sides[label].attacks`（`applySpectateBoardFrame`）
 *
 * 两条路径都把服务端的 `sides[label].attacks` 存进 `sp.attacks[label]`，
 * 再由那**同一个**转置翻一次方向。所以**服务端两条路径必须同向** ——
 * 第 5 批的帧发的是**棋盘方向**（`_spectate_board_frame` 里把方向翻了一次），
 * 前端又翻一次 ⇒ 翻两次 ⇒ **两块棋盘恰好对调**，而且不抛异常、不报错，
 * 只表现为"观战屏上两块棋盘和服务端不一样"（CLAUDE.md 教训 #7）。
 *
 * 这个检查专门造**两组无交集的格**（p1 打 {(0,0),(1,1)}、p2 打 {(4,4),(5,5)}）——
 * 双方打同一批格时"方向写反"与"方向写对"结果**完全一样**，测不出来
 * （上一批漏掉它的原因）。然后：
 *
 *   ① 跑**真的** `static/game.js`（vm 里，带最小 DOM 桩），读它真的画进
 *      `#spectate-board-1` / `#spectate-board-2` 的格子（`(x,y)+hit/sunk`）；
 *   ② 与服务端 payload 里每个座位的 `attacks` **逐格比对**；
 *   ③ 顺带把"帧之后再开一炮"也跑一遍（错的朝向会被后续每一炮继承）。
 *
 * ## 判据（严格相等，0 容差）
 *
 * 第 1 块棋盘上的格 == 服务端 `sides.p2.attacks`（= 落在 p1 那块棋盘上的格）；
 * 第 2 块棋盘上的格 == 服务端 `sides.p1.attacks`。
 * **p1 那块棋盘上一个 p1 自己打的格都不许出现**（那条判据专门抓"方向写反"）。
 *
 * ## 用法
 *
 * `DSH_SPEC_PAYLOAD` 环境变量给一份 JSON：
 *   `{ "snapshot": <服务端 _build_spectate_snapshot 的输出>,
 *      "frame":    <服务端 _build_spectate_board_frame 的输出>,
 *      "extra_shot": {"attacker": "<原始 seat key>", "x": 2, "y": 3, "hit": true} }`
 *
 * 用**环境变量**而不是命令行参数：payload 里有中文昵称，命令行在 Windows 上
 * 要过一层代码页转换（GBK），容易把中文名弄坏（CLAUDE.md 反复踩过）。
 *
 * 退出码：0 = 全绿；1 = 有失败项（逐条打印 FAIL）；2 = 加载/输入失败。
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
// 最小 DOM 桩：只实现 game.js 在**加载期**与观战渲染路径上真正用到的那点东西。
// ⚠️ 不加 `Proxy` 之类的"全都当成功"的兜底 —— 那会让"页面上其实没有这个元素"
//    变成静默通过（正是 dom_contract_check.mjs 要抓的那一类）。
// ---------------------------------------------------------------------------
function makeEl(id) {
  // ⚠️ 真实 DOM 里 `el.className` 与 `el.classList` 是**同一份数据**。
  //    桩里拆成两个独立字段的话，`el.className = 'cell'`（game.js 就是这么写的）
  //    不会进 `classList` → `querySelectorAll('.cell')` 恒为 0 →
  //    工具自己制造 6 项假红（本工具第一版就踩了这个，实测）。
  const classes = new Set();
  const el = {
    id, children: [], dataset: {}, _text: '', _html: '', _cls: '',
    classList: {
      add(...c) { c.forEach((x) => classes.add(x)); el._syncClassName(); },
      remove(...c) { c.forEach((x) => classes.delete(x)); el._syncClassName(); },
      toggle(c) { classes.has(c) ? classes.delete(c) : classes.add(c); el._syncClassName(); },
      contains(c) { return classes.has(c); },
    },
    _syncClassName() { el._cls = Array.from(classes).join(' '); },
    style: { setProperty() {}, removeProperty() {}, getPropertyValue() { return ''; } },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { return c; },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    addEventListener() {}, removeEventListener() {}, remove() {},
    querySelector() { return null; },
    // 与真实 DOM 一致：`.cell.hit` 是**同一元素上两个类都要有**（AND），
    // 逗号分隔的多组是 OR。⚠️ 曾经写成"任一类命中"，于是本工具的
    // `querySelectorAll('.cell')` 恒返回 0 —— 12 项里 6 项假红（工具自己的 bug）。
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

const sandbox = {
  console,
  document: documentStub,
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
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;
sandbox.addEventListener = () => {};
sandbox.removeEventListener = () => {};
sandbox.dispatchEvent = () => true;

if (!fs.existsSync(GAME_JS)) { console.error('找不到 static/game.js'); process.exit(2); }
const SRC = fs.readFileSync(GAME_JS, 'utf8');

const raw = process.env.DSH_SPEC_PAYLOAD;
if (!raw) { console.error('缺少环境变量 DSH_SPEC_PAYLOAD'); process.exit(2); }
let payload;
try {
  payload = JSON.parse(raw);
} catch (e) {
  console.error('DSH_SPEC_PAYLOAD 不是合法 JSON: ' + (e && e.message));
  process.exit(2);
}

const ctx = vm.createContext(sandbox);
try {
  vm.runInContext(SRC, ctx, { filename: 'game.js' });
} catch (e) {
  console.error('game.js 加载失败: ' + (e && e.stack));
  process.exit(2);
}

// 在 vm 里读"两块棋盘上到底画了什么格"（只有 hit/miss 的格会被记录）。
const READ = `(function () {
  function read(board) {
    var out = [];
    if (!board) return out;
    var cells = board.querySelectorAll('.cell');
    for (var i = 0; i < cells.length; i++) {
      var c = cells[i];
      if (!(c.classList.contains('hit') || c.classList.contains('miss'))) continue;
      out.push(c.dataset.x + ',' + c.dataset.y + ','
        + (c.classList.contains('sunk') ? 'S' : (c.classList.contains('hit') ? 'H' : 'M')));
    }
    return out.sort();
  }
  return function () {
    return { b1: read(spectateBoards[0].board), b2: read(spectateBoards[1].board),
             cells: spectateBoards.map(function (s) { return s.board ? s.board.children.length : -1; }) };
  };
})()`;
const readBoards = vm.runInContext(READ, ctx, { filename: 'read.js' });

// ⚠️ DOM 里 `dataset.x` 是**字符串**（真实浏览器也是）——本工具的桩也一样，
//    所以两边的 key 一律用字符串拼，避免 "0" 与 0 混用导致假红/假绿。
const asSet = (list) => JSON.stringify((list || []).slice().sort());
const cellSet = (list) => JSON.stringify((list || []).map(
  (c) => c.x + ',' + c.y + ',' + (c.ship_sunk ? 'S' : (c.hit ? 'H' : 'M'))).sort());

const snap = payload.snapshot;
const frame = payload.frame;
if (!snap || !snap.sides) { console.error('payload.snapshot 形状不对'); process.exit(2); }
if (!frame || !frame.sides) { console.error('payload.frame 形状不对'); process.exit(2); }

// ---------------------------------------------------------------------------
// 0. 前置：这份 payload 必须是"双方格集无交集"的局面，否则方向测不出来
// ---------------------------------------------------------------------------
const p1Own = cellSet(snap.sides.p1 && snap.sides.p1.attacks);
const p2Own = cellSet(snap.sides.p2 && snap.sides.p2.attacks);
check(p1Own !== p2Own && p1Own !== '[]' && p2Own !== '[]',
  '（前置）双方打出的格**不同且都非空**（对称局面测不出方向写反）',
  { p1: JSON.parse(p1Own), p2: JSON.parse(p2Own) });
check(JSON.parse(p1Own).every((c) => !JSON.parse(p2Own).includes(c)),
  '（前置）两组格**无交集**（有交集的话"对调"会被交集掩盖）', { p1: p1Own, p2: p2Own });

// 期望：第 i 块棋盘上画的是**对方**打出去的格
const wantB1 = cellSet(snap.sides.p2.attacks);
const wantB2 = cellSet(snap.sides.p1.attacks);

// ---------------------------------------------------------------------------
// A. 快照路径
// ---------------------------------------------------------------------------
vm.runInContext('applySpectateSnapshot(' + JSON.stringify(snap) + ');', ctx, { filename: 'snap.js' });
if (process.env.DSH_SPEC_DEBUG) {
  const d = vm.runInContext(`(function(){
    var b = spectateBoards[0].board;
    return { ba: JSON.stringify(gameState.spectate.snapshot.board_attacks),
             att: JSON.stringify(gameState.spectate.attacks),
             n: b.children.length,
             first: b.children[0] ? { cls: b.children[0].className,
               hit: b.children[0].classList.contains('hit'),
               x: b.children[0].dataset.x, txt: b.children[0].textContent } : null,
             q: b.querySelectorAll('.cell').length,
             marks: b.querySelectorAll('.cell.hit, .cell.miss').length };
  })()`, ctx, { filename: 'debug.js' });
  console.error('DEBUG ' + JSON.stringify(d, null, 1));
}
let dom = readBoards();
check(asSet(dom.b1) === wantB1, '★ 快照：第 1 块棋盘 == 服务端 sides.p2.attacks', { dom: dom.b1, want: JSON.parse(wantB1) });
check(asSet(dom.b2) === wantB2, '★ 快照：第 2 块棋盘 == 服务端 sides.p1.attacks', { dom: dom.b2, want: JSON.parse(wantB2) });
check(dom.cells[0] === 36 && dom.cells[1] === 36, '（前置）两块棋盘都是 6×6=36 格', dom.cells);

// ---------------------------------------------------------------------------
// B. 实时帧路径（快照之后收到一个 spectate_board）
// ---------------------------------------------------------------------------
const snapBefore = JSON.stringify(dom);
console.log('--- 收到 spectate_board 帧 ---');
vm.runInContext('applySpectateBoardFrame(' + JSON.stringify(frame) + ');', ctx, { filename: 'frame.js' });
const domAfter = readBoards();
check(asSet(domAfter.b1) === wantB1,
  '★★ 帧之后：第 1 块棋盘仍然 == 服务端 sides.p2.attacks（帧与快照必须同向）',
  { dom: domAfter.b1, want: JSON.parse(wantB1),
    '帧里的 p2.attacks': JSON.parse(cellSet(frame.sides.p2 && frame.sides.p2.attacks)),
    '帧里的 p1.attacks': JSON.parse(cellSet(frame.sides.p1 && frame.sides.p1.attacks)) });
check(asSet(domAfter.b2) === wantB2,
  '★★ 帧之后：第 2 块棋盘仍然 == 服务端 sides.p1.attacks',
  { dom: domAfter.b2, want: JSON.parse(wantB2) });
// ★ 这一条是"方向写反"的**点名判据**：p1 那块棋盘上不许出现 p1 自己打的格。
//   ⚠️ 判据必须**同时**要求"该出现的一个不少" —— 只写"不该出现的没出现"的话，
//      棋盘空了（或渲染整条坏掉）也会通过（实测：本工具第一版就是这种空转绿）。
{
  const b1 = JSON.parse(asSet(domAfter.b1));
  const p1Own = JSON.parse(wantB2);      // p1 自己打出去的格
  check(b1.length > 0 && b1.every((c) => !p1Own.includes(c)) && asSet(domAfter.b1) === wantB1,
    '★★ 第 1 块棋盘上既**画对了**、又**没有**一个 p1 自己打出去的格（方向写反 = 两块棋盘对调）',
    { b1: domAfter.b1, 该画: JSON.parse(wantB1), p1打出的: p1Own });
}
check(snapBefore === JSON.stringify({ b1: domAfter.b1, b2: domAfter.b2, cells: domAfter.cells }),
  '★ 帧没有改动画面（服务端数据与快照一致时，重画结果必须逐格相同）',
  { 快照后: JSON.parse(snapBefore), 帧后: domAfter });

// ---------------------------------------------------------------------------
// C. 帧之后再开一炮：错的朝向会被后续每一炮继承
// ---------------------------------------------------------------------------
const shot = payload.extra_shot;
if (shot) {
  const shooterLabel = (snap.seat_labels || {})[shot.attacker];
  check(shooterLabel === 'p1' || shooterLabel === 'p2',
    '（前置）extra_shot.attacker 能在 seat_labels 里查到座位标签', { attacker: shot.attacker, shooterLabel });
  const targetBoard = shooterLabel === 'p1' ? 'b2' : 'b1';   // 打的人是自己 → 落在对方棋盘
  const beforeShot = readBoards();
  vm.runInContext('spectateOnAttackResult(' + JSON.stringify({
    attacker: shot.attacker, x: shot.x, y: shot.y, hit: !!shot.hit, ship_sunk: !!shot.ship_sunk,
    attacker_remaining_ships: 6, defender_remaining_ships: 6, remaining_attacks: 4,
  }) + ');', ctx, { filename: 'shot.js' });
  const afterShot = readBoards();
  const key = shot.x + ',' + shot.y + ',' + (shot.hit ? 'H' : 'M');
  const otherBoard = targetBoard === 'b1' ? 'b2' : 'b1';
  check(afterShot[targetBoard].includes(key) && !afterShot[otherBoard].includes(key),
    '★ 帧之后的新一炮**只**画在打的人对面那块棋盘上（' + targetBoard + '）',
    { targetBoard, otherBoard, key, after: afterShot[targetBoard], other: afterShot[otherBoard] });
  check(afterShot.b1.length === beforeShot.b1.length + (targetBoard === 'b1' ? 1 : 0)
    && afterShot.b2.length === beforeShot.b2.length + (targetBoard === 'b2' ? 1 : 0),
    '★ 这一炮只让**一块**棋盘多一格（另一块一格不动）',
    { before: { b1: beforeShot.b1.length, b2: beforeShot.b2.length },
      after: { b1: afterShot.b1.length, b2: afterShot.b2.length } });
} else {
  console.log('SKIP  没有 extra_shot（只验方向，不验后续开炮继承）');
}

console.log('');
console.log(problems.length
  ? ('FAILED  ' + problems.length + '/' + checks + ' 项')
  : ('OK  ' + checks + ' 项全绿'));
process.exit(problems.length ? 1 : 0);
