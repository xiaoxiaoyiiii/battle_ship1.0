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
 * ## 八组判据
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
 *   F. **主动牺牲的船格 = 红叉**（作者实报第三条：牺牲的船"直接消失"）：
 *      牺牲之后那一格必须**还在**时间线里、画成 `ship sunk hit` + `✕`；
 *      同一侧没被牺牲的船照旧是 `⛴`。**四条反向腿**同时钉住"别的成因不许变成沉没"：
 *      滥竽充数收回（那一格必须**空掉**）、换位、复活（红叉必须消失、船重新画出来）。
 *      ⚠️ 这一组必须**逐格断言字形** —— 上一批的教训是"格子数量相等"抓不住问题。
 *   G. **`神威！`的两支**：致死那一格 = 红叉 + "不会再回来"的无障碍文案（且**不**再叠洞的
 *      斜纹）；"暂时除外"那一支 = 洞里没有船、一格沉没标记都不许有。
 *   H. **沉没判据只有一份说法**（2026-09-24 收口批）：同一格不许有"活船"与"显式沉没登记"
 *      两份说法并存（口径：**显式事实优先**，由 `replay._ship_cells` 保证最多一条）；
 *      前端 `replayCellOf` **不许**长出第二份仲裁实现（源码级判据 + 一条自检反向腿）。
 *   I. **卡牌类伤害的格子在回放里必须画得出来**（2026-09-24 第 7 处修复批）：
 *      `轰炸` / `硫磺火焰` / `溅射` / `雷达子弹` / `探测雷达` 逐格写 `Player.attacks`
 *      并逐格 `emit('attack_result')`，但**一条 `type='attack'` 的游戏日志都不写** ——
 *      改动前回放的标记是**从 attack 步反推**的 ⇒ 那一整行/列的格子在回放里
 *      **一个标记都没有**（作者实报："看着是没挨过炮的海面"）。
 *      本批把标记收敛到 `payload.attacks` 这条**稀疏 + 增量**时间线（数据源 =
 *      `Player.attacks`，与观战棋盘帧**同一份权威记录**）。
 *      这一组喂的是**后端真产出的形状**（`tests/test_replay_bomb_marks.py` 逐字段断言了
 *      后端那一侧）：那一行/列 6 格逐格断言字形（✕ / ○），并与真值表逐格一致。
 *   J. **「剩余战舰 N」必须读权威计数**（2026-09-24 审计批）：
 *      这一项原来是从**船位时间线数格子**出来的，而实战/观战/重连快照读的都是
 *      `Player.remaining_ships` —— **同一件事两份实现**（教训 #1）。两者实测会不等
 *      （真对局 seed 4242：`remaining_ships=1` 而船格里有 3 个 `alive`）。
 *      本批新增 `payload.remaining`（稀疏 + 增量，值就是 `remaining_ships`），
 *      前端 `replayAliveShips` 读它。J 组喂一份"两者故意不等"的 payload 逐项断言；
 *      K 组是**老 blob 的兜底腿**（没有 `remaining` ⇒ 退回数船格，不是显示 0）。
 *
 * ## I 组覆盖了哪一件、以及它**不**覆盖哪一件
 *
 * I 组是"**改前必红**"的那一组：它喂 `轰炸` / `硫磺火焰` 那种"**没有 attack 步、
 * 只有 attacks 时间线**"的 payload（形状由 `tests/test_replay_bomb_marks.py` 从
 * 真卡实现里取出来）。改动前 `replayComputeFrame` 从 attack 步反推标记 ⇒ 这些格
 * 一格都画不出来 ⇒ I 组全红；改后逐格有字形。
 *
 * ⚠️ 它**仍然**证明不了"线上那一局真的产出了这样的 payload" —— 那由 pytest
 *    （真调 `apply_magic_effect`）与 `tools/replay_check.mjs`（真浏览器 E2E）分工覆盖。
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

/** 形状与服务端 `replay.py` 的 `build()` 输出一致的最小 payload 构造器。
 *
 *  ★ `attacks` 时间线（本批新增的标记数据源）**默认按 `steps` 里的 attack 步推出来** ——
 *  这不是"前端替后端算一份"，而是因为后端**普通炮击**那一炮确实会产出这两样东西
 *  （`handle_attack` 既 append `caster.attacks` 又写一条 `type='attack'` 的日志）。
 *  于是既有那些"只有 attack 步"的夹具（A~H 组）在改后仍然表达同一份真实对局数据，
 *  不必逐条重写。要测"**没有 attack 步、只有 attacks 时间线**"的那一类卡（轰炸 /
 *  硫磺火焰 / 溅射 / 雷达子弹 / 探测雷达）就显式传 `attacks` —— 见 I 组。
 *
 *  ⚠️ 推导口径与后端逐个对应：`hit` / `sunk` **为假时整个键不出现**
 *     （`replay._record_snapshot` 就是这么写的，别在这里多写 `hit:false`，
 *      否则夹具比真实 payload 胖、还测不出"缺省即未命中"这条口径）。
 */
function attacksFromSteps(steps) {
  const rows = [];
  for (const s of (steps || [])) {
    if (!s || s.kind !== 'attack') continue;
    const d = s.detail || {};
    const t = d.target || {};
    const attacker = d.attacker;
    if (attacker !== 'p1' && attacker !== 'p2') continue;
    const board = attacker === 'p1' ? 'p2' : 'p1';
    const cell = { x: t.x, y: t.y };
    if (d.hit === true) cell.hit = true;
    if (d.ship_sunk === true) cell.sunk = true;
    let row = rows.find((r) => r.step === s.i);
    if (!row) { row = { step: s.i }; rows.push(row); }
    if (!Array.isArray(row[board])) row[board] = [];
    row[board].push(cell);
  }
  return rows;
}

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
    attacks: o.attacks || attacksFromSteps(o.steps || []),
    effects: o.effects || [],
    remaining: o.remaining || [],
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

// ===========================================================================
// F. 主动牺牲的船格 = 红色叉叉（作者实报第三条：牺牲的船"直接消失"）
// ===========================================================================
// 判据的核心（本批的验收核心）：牺牲之后那一格**还在时间线里**、
// 画成 `ship sunk hit` + `✕`；而**另外三种**"某格不再有船"（滥竽充数收回 /
// 换位 / 除外）**一格都不许**长成沉没 —— 改错了就是制造幻影沉船。
//
// ⚠️ 判据必须**逐格断言字形**（上一批的经验："格子数量相等"这类判据抓不住问题）。
console.log('--- F. 主动牺牲的船格 = 红色叉叉（改前会凭空消失）---');
{
  // 后端 `_do_demon_contract_sacrifice` 现在会让时间线长成这个样子：
  //   step 1（牺牲那一步）p1 侧出现 `{x:2,y:2,alive:false,sunk:true}`，
  //   而没被牺牲的那艘船 **(3,3)** 仍在。
  // 改前：这一格**根本不在**时间线里（`player.ships.remove` 之后就没了）。
  const sacPayload = mkPayload({
    steps: [
      atk(0, 'p2', 0, 0, true, false),
      { i: 1, kind: 'magic', actor: '甲', text: '第3回合 · 甲 因恶魔契约牺牲一艘战舰',
        detail: { player: 'p1', reason: 'demon_contract', positions: [{ x: 2, y: 2 }] } },
    ],
    // 稀疏 + 增量：step 0 记两侧，step 1 **只带 p1**（牺牲那一侧）
    ships: [
      { step: 0, p1: [{ x: 2, y: 2, alive: true }, { x: 3, y: 3, alive: true }],
        p2: [{ x: 0, y: 0, alive: true }] },
      { step: 1, p1: [{ x: 3, y: 3, alive: true },
                      { x: 2, y: 2, alive: false, sunk: true }] },
    ],
  });

  const f1 = frameAt(sacPayload, 1);
  const wreck = cellAt(f1.boards[0], 2, 2);
  check(!!wreck, '★★ 牺牲的那一格**必须还在棋盘上**（改前它整格消失）',
    wreck && { text: wreck.text, cls: wreck.cls });
  check(!!wreck && wreck.text === '✕',
    '★★ 牺牲格画成 ✕（红叉，不是消失、也不是"船"）', wreck && wreck.text);
  check(!!wreck && wreck.sunk === true,
    '★★ 牺牲格的类名带 `sunk`（前端 `replayCellOf` 判沉的唯一出口）',
    wreck && wreck.cls);
  check(!!wreck && wreck.ship && wreck.hit,
    '★ 牺牲格同时是 `ship` + `hit`（与"打沉的格"同一种视觉）', wreck && wreck.cls);
  check(!!wreck && wreck.title.indexOf('击沉') >= 0,
    '★ 牺牲格的 title 写明"击沉"（读屏/悬停拿到的是同一条）', wreck && wreck.title);
  // 没被牺牲的那艘船不受影响
  const survivor = cellAt(f1.boards[0], 3, 3);
  check(!!survivor && survivor.text === '⛴' && !survivor.sunk,
    '★ 同一侧**没被牺牲**的船照旧画成 ⛴（不许被一起标成沉没）',
    survivor && { text: survivor.text, cls: survivor.cls });
  // 另一侧一格都不许受影响
  const otherSide = cellAt(f1.boards[1], 0, 0);
  check(!!otherSide && otherSide.text === '⛴' && !otherSide.sunk,
    '★ 牺牲只影响自己那一侧：对手棋盘上的船照旧', otherSide && { text: otherSide.text, cls: otherSide.cls });

  // 反向腿①：牺牲**之前**那一帧（k=0）它必须是活着的船（否则就是"一开始就是沉船"的假绿）
  const f0 = frameAt(sacPayload, 0);
  const before = cellAt(f0.boards[0], 2, 2);
  check(!!before && before.text === '⛴' && !before.sunk,
    '★★ 反向腿：牺牲**之前**那一帧它是活着的 ⛴（不是"从头到尾都是沉船"的假绿）',
    before && { text: before.text, cls: before.cls });
}
{
  // 反向腿②（★ 最重要的一条）：**滥竽充数**的临时船被收回 —— 那一格必须**消失**，
  // 一格都不许变成沉没（卡面与 `_recall_lanyu_ships` 的注释明写"不会显示沉没"）。
  // ⚠️ 后端那边那几格**根本不会进时间线**（收回路径不调 `note_ship_lost`），
  //    所以这条同时也是"朴素修法（凡是曾有船就永远留成沉没）会红"的那一条。
  const lanyuPayload = mkPayload({
    steps: [
      atk(0, 'p2', 5, 5, false, false),
      { i: 1, kind: 'magic', actor: '甲',
        text: '第3回合 · 甲 的【滥竽充数】临时战舰已收回(1艘)',
        detail: { player: 'p1', card: '滥竽充数', count: 1 } },
    ],
    ships: [
      { step: 0, p1: [{ x: 1, y: 1, alive: true }] },      // 临时船登场
      { step: 1, p1: [] },                                  // 被收回 ⇒ 这一侧**空了**
    ],
  });
  const l0 = frameAt(lanyuPayload, 0);
  const temp = cellAt(l0.boards[0], 1, 1);
  check(!!temp && temp.text === '⛴' && !temp.sunk,
    '★ 反向腿②：临时船在回合内是活着的 ⛴', temp && { text: temp.text, cls: temp.cls });
  const l1 = frameAt(lanyuPayload, 1);
  const gone = cellAt(l1.boards[0], 1, 1);
  check(!!gone && gone.text === '' && !gone.sunk && !gone.ship,
    '★★ 反向腿②：临时船被收回后那一格必须**空掉**（卡面：不会显示沉没）',
    gone && { text: gone.text, cls: gone.cls });
  check(!!gone && gone.text !== '✕',
    '★★ 反向腿②：收回**绝不是**牺牲 —— 不许画成红叉（改错 = 幻影沉船）',
    gone && gone.text);
}
{
  // 反向腿③（换位）：时间线的后一条把那一侧**整体替换**成新位置 ⇒ 旧格不留假红叉。
  const movePayload = mkPayload({
    steps: [
      atk(0, 'p2', 5, 5, false, false),
      { i: 1, kind: 'place_ships', actor: '甲', text: '复活战舰已部署到 (4,4)', detail: {} },
    ],
    ships: [
      { step: 0, p1: [{ x: 2, y: 2, alive: true }] },
      { step: 1, p1: [{ x: 4, y: 4, alive: true }] },       // 换位：旧格不再出现
    ],
  });
  const m1 = frameAt(movePayload, 1);
  const oldCell = cellAt(m1.boards[0], 2, 2);
  const newCell = cellAt(m1.boards[0], 4, 4);
  check(!!oldCell && oldCell.text === '' && !oldCell.sunk,
    '★★ 反向腿③：换位之后旧格是**空海**（不许留下假红叉）',
    oldCell && { text: oldCell.text, cls: oldCell.cls });
  check(!!newCell && newCell.text === '⛴',
    '★★ 反向腿③：换位之后新格重新画成 ⛴', newCell && { text: newCell.text, cls: newCell.cls });
}
{
  // 反向腿④（复活）：牺牲 → 复活。红叉必须**消失**、船重新画出来。
  const revivePayload = mkPayload({
    steps: [
      { i: 0, kind: 'magic', actor: '甲', text: '甲 因恶魔契约牺牲一艘战舰', detail: {} },
      { i: 1, kind: 'place_ships', actor: '甲', text: '复活战舰已部署到 (4,4)', detail: {} },
    ],
    ships: [
      { step: 0, p1: [{ x: 2, y: 2, alive: false, sunk: true }] },
      { step: 1, p1: [{ x: 4, y: 4, alive: true }] },
    ],
  });
  const r0 = frameAt(revivePayload, 0);
  const wreck0 = cellAt(r0.boards[0], 2, 2);
  check(!!wreck0 && wreck0.text === '✕' && wreck0.sunk,
    '★ 反向腿④：复活之前那一格是红叉', wreck0 && { text: wreck0.text, cls: wreck0.cls });
  const r1 = frameAt(revivePayload, 1);
  const wreck1 = cellAt(r1.boards[0], 2, 2);
  const back = cellAt(r1.boards[0], 4, 4);
  check(!!wreck1 && wreck1.text === '' && !wreck1.sunk,
    '★★ 反向腿④：复活之后旧格的红叉**必须消失**',
    wreck1 && { text: wreck1.text, cls: wreck1.cls });
  check(!!back && back.text === '⛴' && !back.sunk,
    '★★ 反向腿④：复活之后的船重新画出来（⛴）', back && { text: back.text, cls: back.cls });
}

// ===========================================================================
// G. `神威！`的两支：致死那一格 = 红叉；"暂时除外"那一支 = 洞、不是沉没
// ===========================================================================
// 作者拍板的口径（2026-09-24 批）：
//   · **致死**（作用于对方棋盘、区域内恰好 1 艘 ⇒ 船被就地打沉）：那一格画成**红叉**，
//     "这格被挖掉 / 暂时打不到"这条信息**放进 title / 无障碍文案**里，
//     **不**在同一格上再叠一个洞的视觉标记（斜纹底会盖掉红色沉没底）；
//   · **暂时除外**（区域内 2 艘以上 ⇒ 下个大回合原样归还）：那一格**消失**、
//     一格都不许长成沉没；而整片 3×3 的**区域高亮照旧**（作者要的是"格子按沉没画"，
//     不是要拆掉区域效果）。
//
// ⚠️ 这两份 payload 的形状是**后端 `replay.build()` 真产出的样子**（同批的
//    `tests/test_replay_shenwei_replay.py` 逐字段断言了后端那一侧；这里断言前端那一侧）。
console.log('--- G. `神威！`：致死格 = 红叉（带"扣掉"文案）+ 除外格 = 消失（洞照旧）---');
{
  const SHENWEI_AREA = { x1: 0, y1: 0, x2: 2, y2: 2 };
  const withHole = (base) => Object.assign({}, NO_EFFECT, { shenwei_holes: [SHENWEI_AREA] });

  // —— 致死：p2 的 (1,1) 是区域内唯一一艘，(5,5) 在区域外活着 ——
  const killPayload = mkPayload({
    steps: [
      atk(0, 'p1', 3, 3, false, false),
      { i: 1, kind: 'magic', actor: '甲', text: '甲 使用了【神威！】，目标区域内1艘战舰被击沉',
        detail: { caster: 'p1', card: '神威！' } },
    ],
    ships: [
      { step: 0, p1: [{ x: 4, y: 4, alive: true }],
        p2: [{ x: 1, y: 1, alive: true }, { x: 5, y: 5, alive: true }] },
      // 稀疏 + 增量：step 1 **只带 p2**（吃牌那一侧）
      { step: 1, p2: [{ x: 5, y: 5, alive: true },
                      { x: 1, y: 1, alive: false, sunk: true }] },
    ],
    effects: [
      { step: 0, p1: NO_EFFECT },
      { step: 1, p2: withHole() },
    ],
  });

  const g0 = frameAt(killPayload, 0);
  const pre = cellAt(g0.boards[1], 1, 1);
  check(!!pre && pre.text === '⛴' && !pre.sunk,
    '★★ 反向腿：神威**打之前**那一帧 (1,1) 是活着的 ⛴（不是"从头到尾都是沉船"的假绿）',
    pre && { text: pre.text, cls: pre.cls });

  const g1 = frameAt(killPayload, 1);
  const dead = cellAt(g1.boards[1], 1, 1);
  check(!!dead && dead.text === '✕',
    '★★ 神威致死那一格画成 ✕（改前：整格凭空消失 —— 它被 `del ships[i]` 摘掉了）',
    dead && { text: dead.text, cls: dead.cls });
  check(!!dead && dead.sunk === true,
    '★★ 致死格带 `sunk` 类（`replayCellOf` 判沉的唯一出口）', dead && dead.cls);
  check(!!dead && dead.ship && dead.hit,
    '★ 致死格同时是 `ship` + `hit`（与"打沉的格"同一种视觉）', dead && dead.cls);
  check(!!dead && dead.hole === false,
    '★★ 致死格**不**再叠洞的斜纹（`.cell.shenwei-hole` 的 !important 底色会盖掉红叉）',
    dead && { cls: dead.cls, hole: dead.hole });
  check(!!dead && dead.aria.indexOf('扣掉了，这一格的战舰不会再回来') >= 0,
    '★★ "这格被挖掉 / 暂时打不到"这条信息在**无障碍文案**里（作者口径：不放视觉标记）；'
    + '文案必须点名"不会再回来"，否则它与"区里其它洞"是同一句、判据分不开',
    dead && { aria: dead.aria, title: dead.title });
  check(!!dead && dead.title.indexOf('击沉') >= 0,
    '★ 致死格的 title 里仍然写明"击沉"（读屏/悬停拿到的是同一条）', dead && dead.title);

  // 区域高亮照旧：同一片 3×3 里**其它格**仍然是洞
  const otherHole = cellAt(g1.boards[1], 0, 0);
  check(!!otherHole && otherHole.hole === true,
    '★★ 同一片区域的**其它格**照旧画成洞（作者要的是格子按沉没画，不是拆掉区域效果）',
    otherHole && { text: otherHole.text, cls: otherHole.cls });
  // ★ 反向腿：那片区域里"没沉船"的洞**不许**带"战舰不会再回来"那句（它是致死格独有的）
  check(!!otherHole && otherHole.aria.indexOf('这一格的战舰不会再回来') < 0,
    '★★ 反向腿：区里**其它洞**不许带致死格那句文案（否则判据分不开、等于没判据）',
    otherHole && otherHole.aria);
  // 区域外的活船不受影响
  const survivor = cellAt(g1.boards[1], 5, 5);
  check(!!survivor && survivor.text === '⛴' && !survivor.sunk,
    '★ 区域外没被碰到的船照旧画成 ⛴（不许被一起标成沉没）',
    survivor && { text: survivor.text, cls: survivor.cls });
  // 另一侧一格都不许受影响
  const caster = cellAt(g1.boards[0], 4, 4);
  check(!!caster && caster.text === '⛴' && !caster.sunk,
    '★ 神威只影响被选中的那块棋盘：施法者那一侧照旧',
    caster && { text: caster.text, cls: caster.cls });
}
{
  // —— 暂时除外：区域内 2 艘被摘掉（下一大回合原样归还）⇒ 那一格必须消失 ——
  const excludePayload = mkPayload({
    steps: [
      atk(0, 'p1', 3, 3, false, false),
      { i: 1, kind: 'magic', actor: '甲',
        text: '甲 使用了【神威！】，目标区域内2艘战舰被暂时除外',
        detail: { caster: 'p1', card: '神威！' } },
    ],
    ships: [
      { step: 0, p1: [{ x: 4, y: 4, alive: true }],
        p2: [{ x: 0, y: 0, alive: true }, { x: 2, y: 2, alive: true },
             { x: 5, y: 5, alive: true }] },
      { step: 1, p2: [{ x: 5, y: 5, alive: true }] },     // 除外的两艘**不在**时间线里
    ],
    effects: [
      { step: 0, p1: NO_EFFECT },
      { step: 1, p2: Object.assign({}, NO_EFFECT, {
        shenwei_holes: [{ x1: 0, y1: 0, x2: 2, y2: 2 }] }) },
    ],
  });

  const e1 = frameAt(excludePayload, 1);
  const goneA = cellAt(e1.boards[1], 0, 0);
  const goneB = cellAt(e1.boards[1], 2, 2);
  check(!!goneA && goneA.text === '' && goneA.sunk === false && goneA.ship === false,
    '★★ 反向腿：暂时除外的船**必须消失**（卡面：下个大回合原样归还 ⇒ 不是沉没）',
    goneA && { text: goneA.text, cls: goneA.cls });
  check(!!goneB && goneB.text === '' && goneB.sunk === false && goneB.ship === false,
    '★★ 反向腿：第二艘同样不许长出沉没标记（改错 = 幻影沉船）',
    goneB && { text: goneB.text, cls: goneB.cls });
  check(!!goneA && goneA.hole === true && !!goneB && goneB.hole === true,
    '★★ 但整片 3×3 的**区域高亮照旧**（洞还在，只是格子里的船没了）',
    { a: goneA && goneA.cls, b: goneB && goneB.cls });
  const outside = cellAt(e1.boards[1], 5, 5);
  check(!!outside && outside.text === '⛴' && outside.sunk === false,
    '★ 区域外的船照旧活着（除外只影响区域内）',
    outside && { text: outside.text, cls: outside.cls });
  // 反向腿：换成"朴素修法"的前端等价物（把这两格也塞成 sunk）就必须红
  const naive = JSON.parse(JSON.stringify(excludePayload));
  naive.ships[1].p2 = [{ x: 5, y: 5, alive: true },
                       { x: 0, y: 0, alive: false, sunk: true },
                       { x: 2, y: 2, alive: false, sunk: true }];
  const n1 = frameAt(naive, 1);
  const naiveCell = cellAt(n1.boards[1], 0, 0);
  check(!(naiveCell && naiveCell.text === '' && naiveCell.sunk === false),
    '★★ 判据自检：把除外格当成沉没（朴素修法）时，上面那条判据**真的会红**（不是恒绿）',
    naiveCell && { text: naiveCell.text, cls: naiveCell.cls });
}


// ===========================================================================
// H. 「这一格沉了没」只有**一份说法**（2026-09-24 收口批）
// ===========================================================================
// 背景：沉没判据有**两份数据源** —— 活船列表（"这艘船不在 ships 里 ⇒ 沉了"，**推断**）
// 与 `lost` 显式登记表（"这艘船因恶魔契约被献祭了"，**事实**）。上一批把后者做出来时，
// **同一格同时出现在两处取哪一条没有任何用例守着**。
//
// 本批定的口径：**`lost`（事实）优先**，并且**排除掉"两份说法并存"这个状态本身** ——
// `replay._ship_cells` 保证同一格最多只出一条。于是前端**不需要**自己去仲裁，
// 它那条"取第一条命中"的 `for…break` 与"取最后一条"结果相同。
//
// 这一组钉住的就是**前端那一侧不许长出第二份仲裁实现**（教训 #1）：谁在
// `replayCellOf` 里按 `src` / `alive` 之类去"挑一条"，就等于把服务端的口径复制一份，
// 两处迟早漂移。**判据是源码级的**（这类"沉默的第二实现"只有源码能钉住）。
console.log('--- H. 沉没判据单一来源：前端不许自己仲裁两份说法 ---');
{
  // ① `replayCellOf` 里那段"找这一格的船格"必须仍然只是"第一条命中"，
  //    而且**不许**读 `src` / 按 alive 之类做取舍。
  const fnStart = SRC.indexOf('function replayCellOf(');
  check(fnStart >= 0, '★ 找得到 `replayCellOf`（判据的前置）', fnStart);
  const fnEnd = SRC.indexOf('\nfunction replayAliveShips(', fnStart);
  check(fnEnd > fnStart, '★ 找得到 `replayCellOf` 的结尾（判据的前置）', fnEnd);
  const body = (fnStart >= 0 && fnEnd > fnStart) ? SRC.slice(fnStart, fnEnd) : '';
  const pickLoop = body.match(/for \(var i = 0; i < ships\.length; i\+\+\) \{[\s\S]*?\n    \}/);
  check(!!pickLoop, '★★ `replayCellOf` 里仍然只有"扫一遍、第一条命中就 break"这一段',
    pickLoop ? pickLoop[0].replace(/\s+/g, ' ').slice(0, 90) : null);
  check(!!pickLoop && /\)\s*\{\s*shipCell = c;\s*break;\s*\}/.test(pickLoop[0]),
    '★★ 那一段必须是"取**第一条**命中"（改成筛一份候选集就是第二份仲裁实现）',
    pickLoop ? pickLoop[0].replace(/\s+/g, ' ') : null);
  check(body.indexOf('.src') < 0 && body.indexOf('src:') < 0 && body.indexOf('src ') < 0,
    '★★ `replayCellOf` **不许**读格子上的 `src`（它只配给守卫看，不配进渲染判据）',
    { hasSrc: body.indexOf('src') });

  // ② 整个 game.js 里不许有第二处"两份说法取哪一条"的痕迹：
  //    `replayCellOf` 之外不许再有人按 `src` 挑格子。
  //    ⚠️ **注释不算**（`//` / `*` 开头的行是契约说明，不是代码）—— 本批实测：
  //       第一版没排除注释，把 `replayCellOf` 上方那段讲解 `src` 的注释判成了"代码"，
  //       一条假红。所以判据取"去掉注释后的那一行里还有没有 `src`"。
  const deComment = (line) => {
    const t = line.trim();
    if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return '';
    const i = line.indexOf('//');
    return i >= 0 ? line.slice(0, i) : line;
  };
  const srcHits = [];
  const re = /\bsrc\b/g;
  let m;
  while ((m = re.exec(SRC)) !== null) {
    const start = SRC.lastIndexOf('\n', m.index) + 1;
    const end = SRC.indexOf('\n', m.index) < 0 ? SRC.length : SRC.indexOf('\n', m.index);
    const code = deComment(SRC.slice(start, end));
    if (code.indexOf('src') < 0) continue;          // 只在注释里出现 ⇒ 不算
    if (code.indexOf('replay') >= 0 || code.indexOf("'lost'") >= 0
        || code.indexOf('"lost"') >= 0) {
      srcHits.push(code.trim().slice(0, 90));
    }
  }
  check(srcHits.length === 0,
    '★★ game.js 里没有任何"按 `src` / `lost` 挑格子"的代码（前端只渲染服务端的结论）',
    srcHits);

  // ③ 反向腿：这份 payload 里同一格给了**两条**说法（后端保证不会出现），
  //    前端按"第一条"渲染 ⇒ 这一条证明"前端确实没有仲裁能力"，
  //    也就证明"口径必须由服务端保证"这件事**不是空话**。
  //    ⚠️ 故意把 `lost` 那条放在**后面**：前端取第一条 ⇒ 画成活船。
  const twoTalk = mkPayload({
    steps: [{ i: 0, kind: 'magic', actor: '甲', text: '甲 因恶魔契约牺牲一艘战舰',
              detail: {} }],
    ships: [
      { step: 0, p1: [{ x: 2, y: 2, alive: true, src: 'ships' },
                      { x: 2, y: 2, alive: false, sunk: true, src: 'lost' }] },
    ],
  });
  const t0 = frameAt(twoTalk, 0);
  const dup = cellAt(t0.boards[0], 2, 2);
  check(!!dup && dup.sunk === false && dup.text === '⛴',
    '★★ 反向腿：同一格两份说法时，前端按**第一条**渲染（它没有仲裁能力 ⇒ '
    + '口径必须由 `replay._ship_cells` 保证"最多一条"）',
    dup && { text: dup.text, cls: dup.cls });
}


// ===========================================================================
// I. 卡牌类伤害的格子必须在回放里画得出来（2026-09-24 第 7 处修复批）
// ===========================================================================
// ## 缺陷（作者实报："那一整行看着是没挨过炮的海面"）
//
// `轰炸` / `硫磺火焰`（以及第 8 处那三张：【溅射】【雷达子弹】【探测雷达】）
// **逐格**写 `caster.attacks` + 逐格 `emit('attack_result')`，实战前端就靠它画叉；
// 但它们**一条 `type='attack'` 的游戏日志都不写**。而改动前回放的标记是
// **从 attack 步反推**的（`step.kind === 'attack'`）⇒ 这一整行/列的格子在回放里
// **一个标记都没有**（那 6 格画成"没挨过炮的海面"）。
//
// ## 本批的口径（★ 判据就是这一条）
//
// 回放的棋盘标记收敛到 `payload.attacks` 这条**稀疏 + 增量**时间线，数据源是
// `Player.attacks` —— 与**观战**棋盘帧（`_spectate_player_cells`）**同一份权威记录**。
// 于是"轰过的格"在全项目只有一份真值表（教训 #1）。
//
// ⚠️ 下面这些 payload 的形状是**后端真产出的样子**：`tests/test_replay_bomb_marks.py`
//    真调 `apply_magic_effect` 把 `replay.build(room)['attacks']` 取出来逐字段断言了
//    后端那一侧；这里断言前端那一侧（真 `replayComputeFrame` + 真 `renderReplayBoard`）。
console.log('--- I. 卡牌类伤害的格子（轰炸 / 硫磺火焰）：必须逐格画得出来 ---');
{
  // —— 情形 1：【轰炸】第 1 行（p2 的船都在 y=1；6 格全挨过炮）——
  // `caster.attacks` 真值表（后端实测的输出顺序）：
  //   ['0,1(沉)','2,1(沉)','4,1(沉)','1,1','3,1','5,1']
  // ⇒ 命中的 3 格是"击沉"（那 3 艘都是单格船），另外 3 格是落空。
  const bombSteps = [
    atk(0, 'p1', 3, 3, false, false),                   // 前面随便一炮（另一块棋盘）
    { i: 1, kind: 'magic', actor: '甲', text: '第3回合 · 甲 使用了【轰炸】',
      detail: { caster: 'p1', card: '轰炸' } },
  ];
  const bombPayload = mkPayload({
    steps: bombSteps,
    // ⚠️ **不**给 p1 的 attack 步：轰炸那一行 6 格只有 attacks 时间线这一份数据源
    attacks: [
      { step: 1, p2: [{ x: 0, y: 1, hit: true, sunk: true },
                      { x: 2, y: 1, hit: true, sunk: true },
                      { x: 4, y: 1, hit: true, sunk: true },
                      { x: 1, y: 1 }, { x: 3, y: 1 }, { x: 5, y: 1 }] },
    ],
    ships: [
      { step: 0,
        p1: [{ x: 3, y: 3, alive: true }],
        // p2 的三艘单格船都在 y=1；被炸沉的按沉没记（与 `ships` 时间线一致）
        p2: [{ x: 0, y: 1, alive: true }, { x: 2, y: 1, alive: true },
             { x: 4, y: 1, alive: true }] },
      { step: 1, p2: [{ x: 0, y: 1, alive: false, sunk: true },
                      { x: 2, y: 1, alive: false, sunk: true },
                      { x: 4, y: 1, alive: false, sunk: true }] },
    ],
  });

  const b1 = frameAt(bombPayload, 1);
  // ★★ 第 1 条（本批验收核心）：那一行 **6 格一格不少**，且逐格字形/状态与真值表一致。
  check(markedSet(b1.boards[1]) === JSON.stringify(
    ['0,1,S', '1,1,M', '2,1,S', '3,1,M', '4,1,S', '5,1,M'].sort()),
    '★★ 改前必红：轰炸那一行 6 格**全部**有标记（3 个击沉 ✕ + 3 个落空 ○）',
    { dom: markedSet(b1.boards[1]),
      want: ['0,1,S', '1,1,M', '2,1,S', '3,1,M', '4,1,S', '5,1,M'] });
  check(markedSet(b1.boards[0]) === JSON.stringify([]),
    '★ 轰炸只打在对手那块棋盘上：自己那块棋盘一格标记都不许有',
    { dom: markedSet(b1.boards[0]) });
  // 逐格字形（不是只数格子数 —— 上一批的教训）
  const sunkCell = cellAt(b1.boards[1], 0, 1);
  const missCell = cellAt(b1.boards[1], 1, 1);
  const waterCell = cellAt(b1.boards[1], 5, 5);
  check(!!sunkCell && sunkCell.text === '✕' && sunkCell.sunk && sunkCell.hit,
    '★★ DOM：被炸沉的那一格画成 ✕（`ship sunk hit`）',
    sunkCell && { text: sunkCell.text, cls: sunkCell.cls });
  check(!!missCell && missCell.text === '○' && missCell.miss && !missCell.sunk,
    '★★ DOM：没命中但挨过炮的那一格画成 ○（这正是改前完全看不到的格子）',
    missCell && { text: missCell.text, cls: missCell.cls });
  check(!!waterCell && waterCell.text === '' && !waterCell.hit && !waterCell.miss,
    '★ DOM：同一块棋盘上没挨过炮的格仍然是空海（标记不许糊成一片）',
    waterCell && { text: waterCell.text, cls: waterCell.cls });
  // 反向腿①（**步进语义**）：第 k 帧只看得到 `step ≤ k` 的格。
  const b0 = frameAt(bombPayload, 0);
  check(markedSet(b0.boards[1]) === JSON.stringify([]),
    '★★ 反向腿：第 0 帧（轰炸那一步之前）那 6 格**一格都不许出现** —— '
    + '判据不是"永远画着"，必须跟着 step 走',
    { dom: markedSet(b0.boards[1]) });
  check(markedSet(b0.boards[0]) === JSON.stringify([]),
    '★ 第 0 帧对手那块棋盘还没有任何标记（那一炮在 step 0，落在 p2 那块）',
    { dom: markedSet(b0.boards[0]) });
}

{
  // —— 情形 2：【硫磺火焰】第 1 列（p2 的船都在 x=1）——
  // `caster.attacks`（后端实测）：['1,0(沉)','1,2(沉)','1,4(沉)','1,1','1,3','1,5']
  const sulfurPayload = mkPayload({
    steps: [
      { i: 0, kind: 'magic', actor: '甲', text: '第3回合 · 甲 使用了【硫磺火焰】',
        detail: { caster: 'p1', card: '硫磺火焰' } },
    ],
    attacks: [
      { step: 0, p2: [{ x: 1, y: 0, hit: true, sunk: true },
                      { x: 1, y: 2, hit: true, sunk: true },
                      { x: 1, y: 4, hit: true, sunk: true },
                      { x: 1, y: 1 }, { x: 1, y: 3 }, { x: 1, y: 5 }] },
    ],
    ships: [
      { step: 0, p1: [{ x: 0, y: 0, alive: true }],
        p2: [{ x: 1, y: 0, alive: false, sunk: true },
             { x: 1, y: 2, alive: false, sunk: true },
             { x: 1, y: 4, alive: false, sunk: true }] },
    ],
  });
  const s0 = frameAt(sulfurPayload, 0);
  check(markedSet(s0.boards[1]) === JSON.stringify(
    ['1,0,S', '1,1,M', '1,2,S', '1,3,M', '1,4,S', '1,5,M'].sort()),
    '★★ 改前必红：硫磺火焰那一列 6 格**全部**有标记（同上，一格不少）',
    { dom: markedSet(s0.boards[1]),
      want: ['1,0,S', '1,1,M', '1,2,S', '1,3,M', '1,4,S', '1,5,M'] });
  check(markedSet(s0.boards[0]) === JSON.stringify([]),
    '★ 硫磺火焰只打对手那块棋盘', { dom: markedSet(s0.boards[0]) });
}

{
  // —— 情形 3：**重置语义**（`board_resets` 仍要能擦掉标记）——
  // 轰炸一行（step 1）→ 对手那块棋盘被重置（step 2，灵气复苏/败者食尘/回光返照）
  // → 之后再轰另一行（step 3）。**只有 step 3 那一行该看得见**。
  // 情形 3 的 ships 时间线**故意**留空：这一组只判"标记"，船位由 `ships` 时间线那边
  // （C/F/G 组）判；两者混在一起会让"这一格是 ✕ 还是 ○"取决于船在不在，
  // 判据就说不清是哪一条在起作用了。
  const resetPayload = mkPayload({
    steps: [
      { i: 0, kind: 'magic', actor: '甲', text: '第3回合 · 甲 使用了【轰炸】',
        detail: { caster: 'p1', card: '轰炸' } },
      { i: 1, kind: 'magic', actor: '甲', text: '甲 使用了【灵气复苏】',
        detail: { caster: 'p1', card: '灵气复苏' } },
      { i: 2, kind: 'magic', actor: '甲', text: '第5回合 · 甲 使用了【轰炸】',
        detail: { caster: 'p1', card: '轰炸' } },
    ],
    attacks: [
      { step: 0, p2: [{ x: 0, y: 1 }, { x: 1, y: 1 }] },
      { step: 2, p2: [{ x: 0, y: 4 }, { x: 1, y: 4 }] },
    ],
    ships: [],
    board_resets: [{ step: 1, side: 'p2' }],
  });
  const beforeReset = frameAt(resetPayload, 0);
  check(markedSet(beforeReset.boards[1]) === JSON.stringify(['0,1,M', '1,1,M'].sort()),
    '★ 重置**之前**：第 1 行的两格看得见',
    { dom: markedSet(beforeReset.boards[1]) });
  const afterReset = frameAt(resetPayload, 2);
  check(markedSet(afterReset.boards[1]) === JSON.stringify(['0,4,M', '1,4,M'].sort()),
    '★★ 重置**之后**：重置前的两格必须消失、重置后的两格必须还在（两向都判）',
    { dom: markedSet(afterReset.boards[1]),
      不该出现: ['0,1', '1,1'] });
}

{
  // —— 情形 5：同一格被写两次（先沉后落空）—— **后写的赢** ——
  // 真对局里约 3/10 局会出现一处：普通炮击把某格打沉之后，【轰炸】会给同一格补一条
  // `hit=False`（服务端卡里那句过滤只按"这次真的摘掉了哪些船"）。实战前端逐条覆盖
  // 同一个键 ⇒ 玩家看到的是后写的那条；回放必须画成**落空 ○**而不是命中 ✕。
  const dupPayload = mkPayload({
    steps: [
      atk(0, 'p1', 2, 1, true, true),                    // 先打沉 (2,1)
      { i: 1, kind: 'magic', actor: '甲', text: '第3回合 · 甲 使用了【轰炸】',
        detail: { caster: 'p1', card: '轰炸' } },
    ],
    // 时间线：step 0 说"沉"，step 1 对**同一格**改口说"落空"
    attacks: [
      { step: 0, p2: [{ x: 2, y: 1, hit: true, sunk: true }] },
      { step: 1, p2: [{ x: 2, y: 1 }, { x: 3, y: 1 }] },
    ],
    ships: [
      { step: 0, p2: [{ x: 2, y: 1, alive: true }] },
      { step: 1, p2: [{ x: 2, y: 1, alive: false, sunk: true }] },
    ],
  });
  const d = frameAt(dupPayload, 1);
  const dupCell = cellAt(d.boards[1], 2, 1);
  // ⚠️ 判据读**帧里的标记表**：DOM 的类名在这一格上会被"沉没"那条分支覆盖
  //    （那一格同时是沉没的船 ⇒ 必定画 ✕），所以 DOM 分不出"标记说的是中还是没中"。
  check(JSON.stringify(d.marks.p2['2,1']) === JSON.stringify({ hit: false, sunk: false }),
    '★★ 同一格被写两次时**后写的赢**（实战前端逐条覆盖同一个键 ⇒ 回放必须一致）',
    { marks2_1: d.marks.p2['2,1'] });
  check(!!dupCell && dupCell.sunk === true && dupCell.text === '✕',
    '★ 同一格的**沉没**仍按 `ships` 时间线画（两个数据源各管一件事，不许互相盖）',
    dupCell && { text: dupCell.text, cls: dupCell.cls });
  // 同样这一步里另一格是**新增**的（(3,1)）—— 证明"后写的赢"没有把新增的格一起吞掉
  check(JSON.stringify(d.marks.p2['3,1']) === JSON.stringify({ hit: false, sunk: false }),
    '★ 同一步里新增的那一格照旧出现（改写只影响被改写的那一格）',
    { marks3_1: d.marks.p2['3,1'] });
}


{
  // —— 情形 4（★ 自检反向腿）：把 `attacks` 时间线拿掉（= 改动前那条路径的输入）——
  // 同一份 steps / ships，**没有** `attacks` ⇒ 前端一格标记都画不出来。
  // 这条证明上面那几条断言**不是恒绿的**：万一有人把"从 attack 步反推"再写回来，
  // 或者把 `payload.attacks` 的读取删掉，这一条会红。
  const noTimeline = JSON.parse(JSON.stringify(mkPayload({
    steps: [{ i: 0, kind: 'magic', actor: '甲', text: '第3回合 · 甲 使用了【轰炸】',
              detail: { caster: 'p1', card: '轰炸' } }],
    ships: [{ step: 0, p2: [{ x: 0, y: 1, alive: false, sunk: true }] }],
    attacks: [],          // ★ 显式空：这条腿要的正是"没有标记数据源"
  })));
  const n0 = frameAt(noTimeline, 0);
  // ⚠️ 判据读的是**帧里的标记表**（`frame.marks`），不是 DOM 的 `hit` 类：
  //    DOM 的 `.cell.sunk` 分支**自己就会加 `hit` 类**（沉没格与命中格同一种视觉，
  //    见 `renderReplayBoard`），所以"沉没 ✕ 也算 hit"—— 拿它当"标记来源"的判据会假绿。
  check(JSON.stringify(n0.marks.p2) === JSON.stringify({}),
    '★★ 判据自检：**没有** `attacks` 时间线时帧里一格标记都没有（证明上面那些断言靠的'
    + '正是这条时间线，不是"永远画着"的假绿）',
    { marksP2: n0.marks.p2 });
  // 同一帧里那一格仍然是**沉没的船**（`ships` 时间线兜的）——
  // 这正是改动前玩家看到的残缺棋盘：只有一个红叉，其余 5 格是"没挨过炮的海面"。
  const wreck = cellAt(n0.boards[1], 0, 1);
  check(!!wreck && wreck.text === '✕' && wreck.sunk === true,
    '★ 判据自检：那一格仍是沉没 ✕（来自 `ships` 时间线，不是标记）—— '
    + '改动前"只有恰好被打沉的那一格看得见"就是这么来的',
    wreck && { text: wreck.text, cls: wreck.cls });
}


// ---------------------------------------------------------------------------
// J / K. 「剩余战舰 N」= **权威计数**（`payload.remaining`）—— 与观战/实战同一个数
// ---------------------------------------------------------------------------
// 这一项是审计批（2026-09-24）修的：改前是**数船格**出来的，而实战 / 观战 / 重连快照
// 读的都是 `Player.remaining_ships`。真对局实测两者会不等（seed 4242：`remaining=1`、
// 船格 3 个 `alive`）⇒ 同一个座位，回放屏写 3、其它屏写 1。
//
// ⚠️ 夹具**故意让两者不等**：船格有 2 格 `alive`，而权威计数说 p1=3 / p2=0。
//    判据必须能区分"读的哪一份"—— 只断言"N 画出来了"会两边都绿（恒等式型假绿）。
/** 把某一帧渲染出来，并读回「双方名字 / 剩余战舰数」这两个 DOM 文本。 */
function playersAt(payload, k) {
  return vm.runInContext(`(function () {
    replayState.payload = ${JSON.stringify(payload)};
    replayState.youAre = null;
    replayState.frame = replayComputeFrame(replayState.payload, ${k});
    renderReplayPlayers();
    return {
      n1: replayNameEls[0] ? replayNameEls[0].textContent : null,
      n2: replayNameEls[1] ? replayNameEls[1].textContent : null,
      s1: replayShipsEls[0] ? replayShipsEls[0].textContent : null,
      s2: replayShipsEls[1] ? replayShipsEls[1].textContent : null,
      alive: replayState.frame.alive,
      counted: { p1: replayAliveShips(replayState.frame, 'p1'),
                 p2: replayAliveShips(replayState.frame, 'p2') }
    };
  })()`, ctx, { filename: 'players.js' });
}

console.log('--- J. 剩余战舰数 = 权威计数（payload.remaining），不是数船格 ---');
{
  // 船格：p1 两格活着、p2 一格活着 —— 数出来是 2 / 1
  // 权威计数：p1 = 3（游戏侧记账与船格不等，正是真对局里出现过的形状）、p2 = 0（全灭）
  const remPayload = mkPayload({
    steps: [
      atk(0, 'p1', 0, 0, true, false),
      atk(1, 'p2', 5, 5, false, false),
    ],
    ships: [{ step: 0,
              p1: [{ x: 1, y: 1, alive: true }, { x: 2, y: 2, alive: true }],
              p2: [{ x: 3, y: 3, alive: true }] }],
    // ⚠️ 与 `ships` 行**故意不一致**：这一组要证明前端读的是这一条
    remaining: [{ step: 0, p1: 4, p2: 3 },
                { step: 1, p2: 0 }],
  });
  const early = playersAt(remPayload, 0);
  check(early.alive && early.alive.p1 === 4 && early.alive.p2 === 3,
    '★ 帧里叠上了 `payload.remaining`（权威计数 p1=4 / p2=3）',
    early.alive);
  check(early.s1 === '4' && early.s2 === '3',
    '★★ 画面上的「剩余战舰 N」= 权威计数（不是船格数出来的 2 / 1）',
    { p1: early.s1, p2: early.s2, counted: early.counted });
  const late = playersAt(remPayload, 1);
  check(late.s2 === '0' && late.alive.p2 === 0,
    '★★ 权威计数为 **0**（全灭）时照旧显示 0 —— 判据不许把 0 当"没有值"退回数船格',
    { p2: late.s2, alive: late.alive });
  check(late.s1 === '4',
    '★ 只带变了的座位：p2 变成 0 不影响 p1 沿用上一条（4）',
    { p1: late.s1, alive: late.alive });
}

console.log('--- K. 老 blob 的兜底腿：没有 `payload.remaining` ⇒ 退回数船格（不是显示 0）---');
{
  const oldBlob = mkPayload({
    steps: [atk(0, 'p1', 0, 0, true, false)],
    ships: [{ step: 0,
              p1: [{ x: 1, y: 1, alive: true }, { x: 2, y: 2, alive: false, sunk: true }],
              p2: [] }],
    remaining: [],          // ★ 本批之前落库的回放就是这个形状
  });
  delete oldBlob.remaining;  // 连键都没有（老 blob 的真实形状）
  const old = playersAt(oldBlob, 0);
  check(old.s1 === '1' && old.s2 === '0',
    '★★ 老 blob（没有 `remaining` 键）⇒ 退回数船格（p1=1 / p2=0），不是"0 / 0"',
    { p1: old.s1, p2: old.s2, alive: old.alive });
  check(old.alive && old.alive.p1 === null && old.alive.p2 === null,
    '★ 兜底路径的证据：`frame.alive` 两个座位都是 null（走的是退回分支）',
    old.alive);
  // 自检反向腿：把 `remaining` 加回去，同一个 payload 的数字必须**跟着变**
  const newBlob = JSON.parse(JSON.stringify(oldBlob));
  newBlob.remaining = [{ step: 0, p1: 5, p2: 2 }];
  const fixed = playersAt(newBlob, 0);
  check(fixed.s1 === '5' && fixed.s2 === '2',
    '★★ 判据自检：同一份 `ships` 只要补上 `remaining`，数字就从 1/0 变成 5/2 —— '
    + '证明 J 组那些断言靠的正是这条时间线，不是"永远画着同一个数"的假绿',
    { p1: fixed.s1, p2: fixed.s2 });
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