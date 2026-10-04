#!/usr/bin/env node
/* 对局屏底部手牌区的布局回归检查（第 37.7 节手牌改版）。
 *
 * 钉住的东西（每一条都对应一次真实回归风险）：
 *   A1 手牌不是滚动容器   —— .magic-hand 的 overflow-x 必须是 visible（改回 auto = 横滚条回来了）
 *   A2 无横向溢出         —— scrollWidth ≤ clientWidth + 旋转 bbox 余量
 *   A3 每张牌都可点       —— elementFromPoint(卡心) 必须落在这张牌里
 *   A4 每张牌的可点条 ≥44 —— 相邻左边缘的间距（重叠时即露出的那一条），末张按自身宽算
 *   A5 不出列             —— 所有卡都在 #magic-system 的网格列内（±旋转余量）
 *   A6 不压棋盘           —— 单格 ≥40px，且棋盘底边在手牌块顶边之上
 *   A7 选中牌完整可见     —— .selected 的 z-index ≥8，且整个卡面多点采样都不被邻居盖住
 *   A8 卡内三区完整       —— 说明框底 ≤ 类型条顶 ≤ 卡底（行截断没把类型条挤出去）
 *   A9 可读下限           —— 1~6 张时卡宽 ≥100px、卡高 =186px（c-arena 的大卡）
 *
 * 用法（服务端必须带 CORS_ORIGINS，否则 socket.io 静默连不上）：：
 *   PORT=5075 CORS_ORIGINS=http://127.0.0.1:5075 ENABLE_TEST_EVENTS=1 python server.py
 *   node tools/hand_layout_check.mjs --url http://127.0.0.1:5075/
 * 可选：
 *   --only 1280x720,1440x900   只跑这些视口
 *   --cards 1,3,6,7,8          只跑这些张数
 *   --shots                    每个视口第一组截图落到 .tmp/hand_layout_shots/
 *   --dump                     额外打印每组的实测几何（卡宽/卡高/可点条），排障用
 *
 * 退出码：全通过 0，有失败 1，环境不可用 0（不把「没浏览器」当红，与既有工具一致）。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const has = (n) => argv.includes(n);
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOTS = has('--shots');
const DUMP = has('--dump');
const SHOT_DIR = path.resolve('.tmp/hand_layout_shots');
const PORT = 9433;
const PROFILE = 'C:/Windows/Temp/hand_layout_check_profile';

const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
if (!EDGE) { console.log('skip: 没找到 Edge/Chrome'); process.exit(0); }

const ALL_VIEWPORTS = [[1280, 720], [1440, 900], [1600, 1000], [1920, 1080], [1366, 768], [1280, 800]];
const ALL_CARDS = [1, 2, 3, 4, 5, 6, 7, 8];
const parseList = (s) => {
  if (!s) return null;
  return s.split(',').map((x) => {
    const t = x.trim();
    const v = t.split('x').map(Number);
    return v.length === 2 && v.every(Number.isFinite) ? v : Number(t);
  }).filter((v) => (Array.isArray(v) ? v.length === 2 : Number.isFinite(v)));
};
const VIEWPORTS = parseList(argOf('--only', '')) || ALL_VIEWPORTS;
const CARDS = parseList(argOf('--cards', '')) || ALL_CARDS;

const TAP_MIN = 44;        // 与 game.js 的 HAND_TAP_MIN 同值（未选中态）
const TAP_SEL_MIN = 40;    // 与 game.js 的 HAND_TAP_SEL_MIN 同值（有牌被选中的那一帧）
const W_MIN = 100;         // 与 game.js 的 HAND_CARD_W_MIN 同值
const H_TARGET = 186;      // 与 game.js 的 HAND_CARD_H 同值
const ROT_SLACK = 32;      // 扇形旋转撑宽 bbox 的余量（132×186 转 ±4° 约 +12px）

const SAMPLE = [
  ['克苏鲁之眼', 2, '普通', '指定对方一名玩家，双方各暴露一艘未被击沉的战舰位置'],
  ['八方来财', 2, '普通', '立即从牌堆抽两张牌加入手牌'],
  ['兵粮寸断', 3, '判定', '对方准备阶段开始前掷骰，小于 3 则跳过其接下来两个准备阶段的摸牌'],
  ['无忧梦呓', 4, '判定', '对方准备阶段掷骰，点数不大于本卡速阶时该玩家本回合无法使用任何魔法卡'],
  ['神威！', 5, '普通', '选定 3×3 区域，区域内的敌方战舰全部暴露并受到一次伤害'],
  ['绝处逢生', 5, '普通', '本回合内每击沉一艘敌方战舰，立即获得一次额外的攻击机会'],
  ['仁王之盾', 4, '普通', '为自方任意两艘战舰附加护盾，护盾可抵挡一次命中'],
  ['命运骰子', 1, '判定', '掷骰决定本回合的攻击次数，点数即为攻击次数'],
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- 断言框架 ----------
const results = [];
let currentGroup = '';
function group(name) { currentGroup = name; }
function ok(cond, label, detail) {
  results.push({ group: currentGroup, label, pass: !!cond, detail });
  if (!cond) console.log(`   ✗ ${label}${detail ? '  ' + detail : ''}`);
}
function near(a, b, tol) { return Math.abs(a - b) <= tol; }

// ---------- 起浏览器 ----------
try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) { /* 残留 profile 不强求 */ }
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--window-size=1600,1000', '--remote-debugging-port=' + PORT,
  '--user-data-dir=' + PROFILE, APP], { stdio: 'ignore' });
await sleep(3500);

let list = [];
try { list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); } catch (e) { /* 下面统一处理 */ }
// ⚠️ 不能只按 type==='page' 取第一条：headless Edge 会把
//    edge://sync-confirmation-dialog 稳定排在第一位，取错就全项假红。
const page = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || ''));
if (!page) {
  browser.kill();
  console.log('skip: 没拿到页面目标（服务端没起？URL 对吗？）');
  process.exit(0);
}

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0; const pend = new Map();
ws.onmessage = (m) => {
  const x = JSON.parse(m.data);
  if (x.id && pend.has(x.id)) {
    const { res, rej } = pend.get(x.id); pend.delete(x.id);
    x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result);
  }
};
const send = (m, p = {}) => new Promise((res, rej) => {
  const id = ++seq; pend.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method: m, params: p }));
  setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + m)); } }, 20000);
});
const ev = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 500) };
  return r.result && r.result.value;
};
await send('Runtime.enable');
let booted = false;
for (let i = 0; i < 60; i++) { if (await ev('typeof window.gameState==="object"')) { booted = true; break; } await sleep(250); }
if (!booted) { browser.kill(); console.log('skip: 页面没起来（gameState 不可用）'); process.exit(0); }

// ---------- 页面内脚本 ----------
function setupExpr(n, selIndex) {
  const cards = SAMPLE.slice(0, n).map(([name, speed, type, description]) =>
    `{name:${JSON.stringify(name)},speed:${speed},type:${JSON.stringify(type)},description:${JSON.stringify(description)}}`).join(',');
  return `(function(){
  try { if (typeof applyThemePreset === 'function' && document.documentElement.dataset.themePreset !== 'arena') applyThemePreset('arena'); } catch(e){}
  // 关掉过渡/动画：.magic-card 的 transform 有 200ms 过渡，而选中牌在重叠档要从
  // scale(1.09) 过渡到 scale(1) —— 不停表的话测到的是过渡中间值，同一份代码会时红时绿。
  if (!document.getElementById('hl-noanim')) {
    var st = document.createElement('style'); st.id = 'hl-noanim';
    st.textContent = '*,*::before,*::after{transition:none !important;animation:none !important}';
    document.head.appendChild(st);
  }
  document.documentElement.dataset.themePreset = 'arena';
  document.documentElement.classList.add('theme-dark');
  document.body.className = 'layout-ingame';
  var gs = document.getElementById('game-screen');
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  gs.classList.add('active');
  gameState.ships = [{positions:[{x:0,y:0}],hits:[],frozen:false,invincible:false,shield:0}];
  gameState.opponentShips = [{positions:[{x:0,y:0}],hits:[],frozen:false,invincible:false,shield:0}];
  gameState.opponentAttacks = [];
  gameState.revealedCells = [];
  if (typeof initGameBoards === 'function') initGameBoards();
  gameState.hand = [${cards}];
  var si = ${selIndex};
  gameState.selectedCardIndex = si;
  var sc = gameState.hand[si];
  // 选中态的身份键是 name + \\u0000 + speed（game.js 的 cardSelectionKey），写错就选不中
  gameState.selectedCardKey = sc ? (sc.name + '\\u0000' + sc.speed) : null;
  var ms = document.getElementById('magic-system'); if (ms) ms.classList.remove('hand-empty');
  if (typeof updateHandUI === 'function') updateHandUI();
  return true;
})()`;
}

function measureExpr(selIndex) {
  return `(function(){
  function R(el){ if(!el) return null; var r=el.getBoundingClientRect();
    return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),
            right:Math.round(r.right),bottom:Math.round(r.bottom)}; }
  function hitAt(c, fx, fy){
    var r = c.getBoundingClientRect();
    var px = Math.round(r.x + r.width*fx), py = Math.round(r.y + r.height*fy);
    if (px < 0 || py < 0 || px >= window.innerWidth || py >= window.innerHeight) return false;
    var h = document.elementFromPoint(px, py);
    return !!(h && (h === c || c.contains(h)));
  }
  // 这张牌**实际能点到**的连续宽度（px）：沿卡面中线逐像素横扫，取最长的一段连续命中。
  // 重叠排布里每张牌右侧会被后一张压住 —— 压住的部分本来就不该算它的可点区，
  // 所以「露出来的那一条」才是真正的触摸目标，用矩形宽度去判会假红。
  // ⚠️ 必须逐像素（不是按 r.width 均匀取样）：取样点落点差 1px 就会把 44 判成 43。
  function clickRun(c){
    var r = c.getBoundingClientRect();
    var y = Math.round(r.y + r.height*0.5);
    var best = 0, run = 0;
    for (var x = Math.ceil(r.x); x <= Math.floor(r.right); x++){
      if (x < 0 || x >= window.innerWidth) { run = 0; continue; }
      var h = document.elementFromPoint(x, y);
      if (h && (h === c || c.contains(h))) { run += 1; if (run > best) best = run; }
      else run = 0;
    }
    return best;
  }
  var ms = document.getElementById('magic-system');
  var hand = document.getElementById('magic-hand');
  if (!ms || !hand) return { missing: true };
  var cards = Array.prototype.slice.call(hand.querySelectorAll('.magic-card'));
  var cs = getComputedStyle(hand);
  var sel = hand.querySelector('.magic-card.selected');
  var selIdx = cards.indexOf(sel);
  var rects = cards.map(R);
  // 可点条：相邻左边缘间距；末张按自身宽算（它没有被压住）
  var strips = rects.map(function(r, i){
    return i < rects.length - 1 ? (rects[i+1].x - r.x) : r.w;
  });
  var c0 = cards[0] ? getComputedStyle(cards[0]) : null;
  var boards = document.querySelectorAll('.boards-container .board');
  var cell = document.querySelector('.boards-container .board .cell');
  var first = cards[0];
  var desc = first ? first.querySelector('.card-desc') : null;
  var bar = first ? first.querySelector('.card-typebar') : null;
  return {
    vp: [window.innerWidth, window.innerHeight],
    body: document.body.className,
    handRect: R(hand), msRect: R(ms),
    handOverflowX: cs.overflowX,
    handScrollW: hand.scrollWidth, handClientW: hand.clientWidth,
    cardW: c0 ? parseFloat(c0.width) : null,
    cardH: c0 ? parseFloat(c0.height) : null,
    cardCount: cards.length,
    rects: rects, strips: strips,
    cardClickRuns: cards.map(clickRun),
    selFound: !!sel,
    selIndex: selIdx,
    selExpected: ${selIndex},
    selRect: R(sel),
    selZ: sel ? parseInt(getComputedStyle(sel).zIndex, 10) : null,
    // 选中牌整个卡面都要点得到它自己 —— 有任何一点被邻居盖住就说明它没「完整显示」
    selFullyVisible: sel ? [[0.1,0.5],[0.3,0.2],[0.5,0.5],[0.7,0.8],[0.9,0.5]].every(function(p){ return hitAt(sel, p[0], p[1]); }) : false,
    selClickRun: sel ? clickRun(sel) : null,
    descBottom: desc ? Math.round(desc.getBoundingClientRect().bottom) : null,
    barTop: bar ? Math.round(bar.getBoundingClientRect().top) : null,
    barBottom: bar ? Math.round(bar.getBoundingClientRect().bottom) : null,
    cardBottom: rects[0] ? rects[0].bottom : null,
    boardRect: boards[0] ? R(boards[0]) : null,
    boardCount: boards.length,
    cellSize: cell ? Math.round(cell.getBoundingClientRect().width) : null,
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
  };
})()`;
}

// ---------- 跑 ----------
if (SHOTS) fs.mkdirSync(SHOT_DIR, { recursive: true });
console.log(`hand_layout_check  url=${APP}`);
console.log(`视口 ${VIEWPORTS.map((v) => v.join('x')).join(' ')} ｜ 张数 ${CARDS.join(',')}`);

for (const [vw, vh] of VIEWPORTS) {
  await send('Emulation.setDeviceMetricsOverride', { width: vw, height: vh, deviceScaleFactor: 1, mobile: false });
  await sleep(400);
  console.log(`\n=== ${vw}x${vh} ===`);
  let shotDone = false;
  for (const n of CARDS) {
    const selIndex = n > 2 ? Math.min(2, n - 1) : 0;
    const s = await ev(setupExpr(n, selIndex));
    if (s && s.__exc) { group(`${vw}x${vh} n=${n}`); ok(false, 'setup 抛异常', s.__exc); continue; }
    await sleep(300);
    const m = await ev(measureExpr(selIndex));
    group(`${vw}x${vh} n=${n}`);
    if (!m || m.__exc || m.missing) { ok(false, '测量失败', JSON.stringify(m && m.__exc ? m.__exc : m)); continue; }

    const ms = m.msRect;
    // A1 / A2 不是滚动容器、无横向溢出
    ok(m.handOverflowX === 'visible', 'A1 手牌不是滚动容器', `overflow-x=${m.handOverflowX}`);
    ok(m.handScrollW <= m.handClientW + ROT_SLACK,
      'A2 无横向溢出', `scrollW=${m.handScrollW} clientW=${m.handClientW} (+${m.handScrollW - m.handClientW})`);
    ok(m.cardCount === n, 'A0 渲染张数正确', `rendered=${m.cardCount} expect=${n}`);
    // A3 每张牌都得有一段够宽的可点区（重叠排布里就是它露出来的那一条）。
    // 选中态的门槛是 40：选中牌要独占一份加宽预算，1280 打 8 张时邻居顶不到 44。
    const minRun = Math.min(...m.cardClickRuns);
    ok(minRun >= TAP_SEL_MIN, 'A3 每张牌可点宽度 ≥40px（选中态）', `runs=[${m.cardClickRuns.join(',')}]`);
    // A3b 选中一张牌之后，其余每一张仍要留得住 40px 可点（选中牌会盖住右邻居左侧一截）
    const others = m.cardClickRuns.filter((_, i) => i !== m.selIndex);
    ok(others.every((r) => r >= TAP_SEL_MIN), 'A3b 选中态下邻居仍可点 ≥40px', `others=[${others.join(',')}]`);
    // A4 可点条（选中态；门槛 40 的理由同 A3，未选中态由 A4u 按 44 断言）
    const minStrip = Math.min(...m.strips);
    ok(minStrip >= TAP_SEL_MIN, 'A4 最小可点条 ≥40px（选中态）', `min=${minStrip} strips=[${m.strips.join(',')}]`);
    // A5 不出列
    const left = Math.min(...m.rects.map((r) => r.x));
    const right = Math.max(...m.rects.map((r) => r.right));
    ok(left >= ms.x - ROT_SLACK && right <= ms.right + ROT_SLACK,
      'A5 全部卡在 #magic-system 列内', `cards=[${left},${right}] col=[${ms.x},${ms.right}]`);
    // A6 不压棋盘
    ok(m.cellSize >= 40, 'A6 单格 ≥40px', `cell=${m.cellSize}`);
    if (m.boardRect) {
      ok(m.boardRect.bottom <= ms.y + 1, 'A6b 棋盘不被手牌压住',
        `board.bottom=${m.boardRect.bottom} hand.top=${ms.y}`);
    }
    // A7 选中牌
    ok(m.selFound && m.selIndex === m.selExpected, 'A7 选中态渲染正确',
      `found=${m.selFound} idx=${m.selIndex} expect=${m.selExpected}`);
    ok(m.selZ !== null && m.selZ >= 8, 'A7b 选中牌 z-index ≥8', `z=${m.selZ}`);
    ok(m.selFullyVisible, 'A7c 选中牌整个卡面不被邻居盖住', '');
    // 判据用布局卡宽（132/100），不是 selRect.w —— 后者是含 1.09 放大 + 旋转的 bbox，
    // 拿它当分母会要求「可点区大于自己变形后的包围盒」，永远差几个像素。
    ok(m.selClickRun !== null && m.selClickRun >= m.cardW - 2,
      'A7e 选中牌的可点区 ≥ 卡宽（未被邻居压住）', `run=${m.selClickRun} cardW=${m.cardW} bboxW=${m.selRect && m.selRect.w}`);
    if (m.selRect) {
      ok(m.selRect.bottom <= vh && m.selRect.y >= 0, 'A7d 选中牌在视口内',
        `y=${m.selRect.y} bottom=${m.selRect.bottom} vh=${vh}`);
    }
    // A8 卡内三区
    ok(m.descBottom <= m.barTop && m.barBottom <= m.cardBottom,
      'A8 说明框/类型条都塞在卡内',
      `desc.bottom=${m.descBottom} bar.top=${m.barTop} bar.bottom=${m.barBottom} card.bottom=${m.cardBottom}`);
    // A9 可读下限
    if (n <= 6) {
      ok(m.cardW >= W_MIN, 'A9 1~6 张时卡宽 ≥100px', `w=${m.cardW}`);
      ok(near(m.cardH, H_TARGET, 1), 'A9b 卡高 =186px', `h=${m.cardH}`);
    } else {
      ok(m.cardW >= W_MIN, 'A9 7~8 张时仍保持可读卡宽 ≥100px', `w=${m.cardW}`);
    }
    // 页面本身不能出现横向滚动
    ok(m.docScrollW === m.docClientW, 'A10 页面无横向溢出', `doc ${m.docScrollW}/${m.docClientW}`);

    // ---- 未选中态：这是玩家看到手牌时的默认状态，触摸下限按 44px 要求 ----
    // （选中态下邻居要跟「选中牌那一对加宽」抢预算，1280 打 8 张时只能给到 ~42，
    //   所以 44 只在未选中态断言；选中态由 A3b 的 40px 兜底。）
    const s2 = await ev(setupExpr(n, -1));
    if (s2 && s2.__exc) { ok(false, '未选中态 setup 抛异常', s2.__exc); continue; }
    await sleep(250);
    const u = await ev(measureExpr(-1));
    if (!u || u.__exc || u.missing) { ok(false, '未选中态测量失败', JSON.stringify(u && u.__exc ? u.__exc : u)); continue; }
    ok(u.selFound === false, 'A11 未选中态确实没有 .selected', `selFound=${u.selFound}`);
    ok(u.cardCount === n, 'A11b 未选中态张数正确', `rendered=${u.cardCount} expect=${n}`);
    ok(Math.min(...u.cardClickRuns) >= TAP_MIN, 'A3u 未选中态每张牌可点 ≥44px',
      `runs=[${u.cardClickRuns.join(',')}] min=${Math.min(...u.cardClickRuns)}`);
    ok(Math.min(...u.strips) >= TAP_MIN, 'A4u 未选中态最小可点条 ≥44px', `strips=[${u.strips.join(',')}]`);
    ok(u.handScrollW <= u.handClientW + ROT_SLACK, 'A2u 未选中态无横向溢出',
      `scrollW=${u.handScrollW} clientW=${u.handClientW}`);
    ok(u.cardW >= W_MIN, 'A9u 未选中态卡宽 ≥100px', `w=${u.cardW}`);
    ok(near(u.cardH, H_TARGET, 1), 'A9bu 未选中态卡高 =186px', `h=${u.cardH}`);
    ok(u.cardW === m.cardW && u.cardH === m.cardH, 'A12 选中与否卡尺寸不变（不因选中而缩放）',
      `unsel=${u.cardW}x${u.cardH} sel=${m.cardW}x${m.cardH}`);
    ok(u.docScrollW === u.docClientW, 'A10u 未选中态页面无横向溢出', `doc ${u.docScrollW}/${u.docClientW}`);

    if (DUMP) {
      const f = (v) => Math.round(v * 10) / 10;
      console.log(`    n=${n} 卡 ${m.cardW}x${m.cardH} 条=[${m.strips.join(',')}] `
        + `选中可点=${m.selClickRun} 未选中=[${u.cardClickRuns.join(',')}] `
        + `手牌条=${f(m.handRect.w)} (容器 ${f(m.msRect.w)}, overflow=${m.handOverflowX})`);
    }

    if (SHOTS && !shotDone) {
      shotDone = true;
      try {
        const shot = await send('Page.captureScreenshot', { format: 'png' });
        fs.writeFileSync(path.join(SHOT_DIR, `${vw}x${vh}-n${n}.png`), Buffer.from(shot.data, 'base64'));
      } catch (e) { /* 截图是附属品，失败不影响结论 */ }
    }
  }
}

browser.kill();
await sleep(200);

const failed = results.filter((r) => !r.pass);
const total = results.length;
console.log(`\n断言 ${total - failed.length}/${total} 通过`);
if (failed.length) {
  console.log('\n失败明细：');
  const byGroup = new Map();
  for (const f of failed) byGroup.set(f.group, (byGroup.get(f.group) || []).concat(f));
  for (const [g, fs_] of byGroup) {
    console.log(`  ${g}`);
    for (const f of fs_) console.log(`     ✗ ${f.label}  ${f.detail || ''}`);
  }
  process.exit(1);
}
console.log('全部通过（手牌不横滚 / 每张可点 / 选中完整可见 / 棋盘未被挤压）');
process.exit(0);
