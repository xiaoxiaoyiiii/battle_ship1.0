#!/usr/bin/env node
/**
 * 顶部「当前生效的场地魔法」横条回归检查（三区档 / arena 宽屏 + 紧凑档）。
 *
 * 覆盖用户提出的四类要求：
 *   1. 有生效场地魔法 → 高屏展示卡面、卡名与效果；矮屏收为紧凑信息条
 *   2. 没有生效场地魔法 → 桌面顶部保留较矮的占位栏
 *   3. 桌面宽屏横向展示；窄屏/紧凑档不产生横向滚动、不遮挡棋盘/手牌
 *   4. 悬停轻量预览 + 点击完整详情（复用既有 showCardTooltip / showCardDetail）
 *
 * 用法：
 *   node tools/field_magic_bar_check.mjs --url http://127.0.0.1:5075/
 *   node tools/field_magic_bar_check.mjs --only 1280x720,1440x900
 *   node tools/field_magic_bar_check.mjs --only 664x336 --skip-wide
 *   node tools/field_magic_bar_check.mjs --shots
 *
 * 退出码：0 = 全通过；1 = 有失败；0 且打印 skip = 环境不可用（没装 Edge/Chrome、连不上页面）。
 * 依赖：一个已跑起来的服务端（CDP 端口 9455，profile 在本仓库 .tmp）。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const has = (n) => argv.includes(n);
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOTS = has('--shots');
const SHOT_DIR = path.resolve('.tmp/field_magic_bar_shots');
const PORT = 9455;
const PROFILE = path.resolve('.tmp/field_magic_bar_profile');

const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
if (!EDGE) { console.log('skip: 没找到 Edge/Chrome'); process.exit(0); }

// 宽屏三区档：cell 尺寸是**未改动前的实测基线**（必须逐档完全一致）
const WIDE = [
  { vp: [1280, 720], board: 300, cell: 42 },
  { vp: [1440, 900], board: 351, cell: 51 },
  { vp: [1600, 1000], board: 370, cell: 54 },
  { vp: [1920, 1080], board: 430, cell: 64 },
];
// 紧凑档：只验证「没有被改坏」（横条不参与三区网格，维持原有矮 chip）
const COMPACT = [[664, 336], [768, 1024]];

const parseVp = (s) => {
  if (!s) return null;
  return s.split(',').map((x) => x.trim().split('x').map(Number))
    .filter((v) => v.length === 2 && v.every(Number.isFinite));
};
const only = parseVp(argOf('--only', ''));
const match = (w, h) => !only || only.some((v) => v[0] === w && v[1] === h);
const wideList = has('--skip-wide') ? [] : WIDE.filter((w) => match(w.vp[0], w.vp[1]));
const compactList = has('--skip-compact') ? [] : COMPACT.filter((v) => match(v[0], v[1]));

let pass = 0; let fail = 0;
const failures = [];
const ok = (tag, cond, detail) => {
  if (cond) { pass++; console.log(`PASS  ${tag}  ->  ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`); }
  else { fail++; failures.push(tag); console.log(`FAIL  ${tag}  ->  ${JSON.stringify(detail)}`); }
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) { /* 首次运行不存在 */ }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--window-size=1600,1000', '--remote-debugging-port=' + PORT, '--user-data-dir=' + PROFILE, APP], { stdio: 'ignore' });
await sleep(3500);

let list = [];
try { list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); } catch (e) { /* 下面统一判空 */ }
// ⚠️ 不能只按 type==='page' 取第一条：headless Edge 会把 edge://sync-confirmation-dialog 稳定排第一
const page = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || ''));
if (!page) { browser.kill(); console.log('skip: 没有可用的页面（服务端没起来？）'); process.exit(0); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let seq = 0; const pend = new Map();
ws.onmessage = (m) => {
  const x = JSON.parse(m.data);
  if (x.id && pend.has(x.id)) {
    const { res, rej } = pend.get(x.id); pend.delete(x.id);
    x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result);
  }
};
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq; pend.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method, params }));
  setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
});
const ev = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 400) };
  return r.result && r.result.value;
};
const shot = async (name) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const r = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
};

await send('Runtime.enable');
await send('Page.enable');
for (let i = 0; i < 60; i++) { if (await ev('typeof window.gameState==="object"')) break; await sleep(250); }

const CARD = { name: '伊甸园', speed: 1, type: '场地', description: '这张牌作为场地魔法卡使用。接下来双方的攻击次数都变为（6-n），n为自己的战舰数目。' };

const SETUP = `(function(){
  try { if (typeof applyThemePreset === 'function') applyThemePreset('arena'); } catch(e){}
  document.documentElement.dataset.themePreset = 'arena';
  document.documentElement.classList.add('theme-dark');
  document.body.className = 'layout-ingame';
  var gs = document.getElementById('game-screen');
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  gs.classList.add('active');
  gameState.ships = [{positions:[{x:0,y:0}],hits:[],frozen:false,invincible:false,shield:0}];
  gameState.opponentShips = [{positions:[{x:0,y:0}],hits:[],frozen:false,invincible:false,shield:0}];
  gameState.opponentAttacks = []; gameState.revealedCells = [];
  if (typeof initGameBoards === 'function') initGameBoards();
  gameState.hand = [{name:'伊甸园',speed:1,type:'普通',description:'x'}];
  gameState.selectedCardIndex = -1; gameState.selectedCardKey = null;
  var ms = document.getElementById('magic-system'); if (ms) ms.classList.remove('hand-empty');
  if (typeof updateHandUI === 'function') updateHandUI();
  if (window.AdaptiveLayout && typeof AdaptiveLayout.apply === 'function') AdaptiveLayout.apply();
  return true;
})()`;

// 定住过渡动画：横条/预览都有 transition，不停表会量到中间态
const FREEZE = `(function(){
  if (document.getElementById('fm-noanim')) return 1;
  var s = document.createElement('style'); s.id = 'fm-noanim';
  s.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}';
  document.head.appendChild(s); return 1; })()`;

const SET_HAS = `(function(){ if (typeof updateFieldMagicUI === 'function')
  updateFieldMagicUI('me', ${JSON.stringify(CARD)}); return true; })()`;
const SET_NONE = `(function(){ if (typeof updateFieldMagicUI === 'function')
  updateFieldMagicUI('me', null); return true; })()`;

const MEASURE = `(function(){
  function R(el){ if(!el) return null; var r=el.getBoundingClientRect();
    return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),
            right:Math.round(r.right),bottom:Math.round(r.bottom)}; }
  var bar = document.querySelector('.field-magic-area');
  var cfm = document.getElementById('current-field-magic');
  var bc = document.querySelector('.boards-container');
  var gc = document.querySelector('.game-container');
  var gcCS = getComputedStyle(gc);
  var barCS = bar ? getComputedStyle(bar) : null;
  var boards = Array.prototype.slice.call(document.querySelectorAll('.boards-container .board'));
  // 棋盘遮挡采样：每块棋盘取四角内缩 + 中心 5 点，命中元素必须仍属于这块棋盘。
  // 只统计**落在视口内**的采样点：合成的紧凑档里页面本身可能比视口高，
  // 视口外的点 elementFromPoint 恒返回 null，会被误算成"被遮挡"。
  var occ = boards.map(function(b){
    var r = b.getBoundingClientRect(); var hit = 0, sampled = 0;
    if (r.width < 1 || r.height < 1) return {hit: 0, sampled: 0, zero: true};
    [[0.15,0.15],[0.85,0.15],[0.5,0.5],[0.15,0.85],[0.85,0.85]].forEach(function(p){
      var x = r.x + r.width*p[0], y = r.y + r.height*p[1];
      if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return;
      sampled++;
      var el = document.elementFromPoint(x, y);
      if (!el || !b.contains(el)) hit++;
    });
    return {hit: hit, sampled: sampled};
  });
  var cell = document.querySelector('.boards-container .board .cell');
  var rows = gcCS.gridTemplateRows.split(' ').filter(function(v){ return parseFloat(v) > 0.01; })
    .map(function(v){ return Math.round(parseFloat(v)); });
  return {
    vp: [window.innerWidth, window.innerHeight],
    body: document.body.className,
    barRect: R(bar), barGridRow: barCS ? barCS.gridRow : null,
    barOverflow: barCS ? barCS.overflow : null,
    barScrollW: bar ? bar.scrollWidth : null, barClientW: bar ? bar.clientWidth : null,
    cfmText: cfm ? cfm.textContent.replace(/\\s+/g, ' ').trim() : null,
    cfmHasNoMagic: !!(cfm && cfm.querySelector('.no-magic')),
    fmArt: R(cfm && cfm.querySelector('.fm-art')),
    fmNameFont: cfm && cfm.querySelector('.fm-name') ? parseFloat(getComputedStyle(cfm.querySelector('.fm-name')).fontSize) : null,
    fmDetails: R(cfm && cfm.querySelector('.fm-details')),
    boardRow: R(bc),
    boardGridRow: bc ? getComputedStyle(bc).gridRow : null,
    boardRects: boards.map(R), boardOccluded: occ,
    cellSize: cell ? Math.round(cell.getBoundingClientRect().width) : null,
    gridRows: rows, gridRowCount: gcCS.gridTemplateRows.split(' ').length,
    turnIndicator: R(document.getElementById('turn-indicator')),
    magicSystem: R(document.getElementById('magic-system')),
    fleet: R(document.querySelector('.players-info > .player-info:nth-child(1)')),
    discard: R(document.querySelector('.discard-pile-btn-row')),
    chainSlot: R(document.getElementById('arena-chain-slot')),
    oppInfo: R(document.querySelector('.players-info > .player-info:nth-child(2)')),
    handCards: document.querySelectorAll('#magic-hand .magic-card').length,
    handClickable: Array.prototype.filter.call(
      document.querySelectorAll('#magic-hand .magic-card'), function(c){
        var r = c.getBoundingClientRect();
        var el = document.elementFromPoint(r.x + r.width/2, r.y + r.height/2);
        return el && (c === el || c.contains(el)); }).length,
    fmExtraShown: ['.fm-meta', '.fm-desc', '.fm-duration'].map(function(sel){
      var e = document.querySelector('.field-magic-area ' + sel);
      return e ? getComputedStyle(e).display !== 'none' : null; }),
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
    docScrollH: document.documentElement.scrollHeight,
  };
})()`;

const PREVIEW_ON = `(function(){
  var el = document.getElementById('current-field-magic');
  el.dispatchEvent(new MouseEvent('mouseenter', {bubbles:false}));
  var t = document.querySelector('.card-tooltip');
  return { tooltip: !!t,
    text: t ? t.textContent.replace(/\\s+/g,' ').trim() : null }; })()`;
const PREVIEW_OFF = `(function(){
  var el = document.getElementById('current-field-magic');
  el.dispatchEvent(new MouseEvent('mouseleave', {bubbles:false}));
  return { tooltip: !!document.querySelector('.card-tooltip') }; })()`;
const DETAIL_OPEN = `(function(){
  document.getElementById('current-field-magic').click();
  var o = document.getElementById('card-detail-overlay');
  return { overlay: !!o, text: o ? o.textContent.replace(/\\s+/g,' ').trim() : null,
    hasClose: !!(o && o.querySelector('.card-detail-close')) }; })()`;
const DETAIL_ESC = `(function(){
  document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
  return { overlay: !!document.getElementById('card-detail-overlay') }; })()`;
// 无场地时点击**不应该**弹任何详情（占位条不是可点控件）
const DETAIL_NONE = `(function(){
  document.getElementById('current-field-magic').click();
  return { overlay: !!document.getElementById('card-detail-overlay') }; })()`;

const barTextHasAll = (txt) => txt && ['伊甸园', '场地', '速阶 1', '攻击次数', '持续生效'].every((k) => txt.indexOf(k) >= 0);

console.log(`# 场地魔法横条检查  url=${APP}  宽屏档=${wideList.length}  紧凑档=${compactList.length}\n`);

for (const spec of wideList) {
  const [vw, vh] = spec.vp;
  const tag = `${vw}x${vh}`;
  console.log(`--- ${tag}  三区档（arena 宽屏）`);
  await send('Emulation.setDeviceMetricsOverride', { width: vw, height: vh, deviceScaleFactor: 1, mobile: false });
  await ev(SETUP); await ev(FREEZE); await sleep(200);

  await ev(SET_NONE); await sleep(120);
  const none = await ev(MEASURE);
  await shot(`${tag}-none`);
  await ev(SET_HAS); await sleep(120);
  const some = await ev(MEASURE);
  await shot(`${tag}-has`);

  if (none.__exc || some.__exc) { ok(`${tag} 探针可求值`, false, none.__exc || some.__exc); continue; }

  // --- 位置：横条必须夹在对手条之下、两块棋盘之上 ---
  // ⚠️ 行号在 2026-10-03 整体 +1：新增了行 3「长久效果胶囊条」，横条从行 3 挪到行 4，
  //    棋盘从行 4 挪到行 5。断言跟着走，仍然钉着「横条在对手条之下、棋盘之上」这个关系。
  ok(`${tag} 横条格子是行 4（对手条之下、棋盘之上）`,
    some.barGridRow === '4 / 5' && some.boardGridRow === '5 / 6',
    { barGridRow: some.barGridRow, boardGridRow: some.boardGridRow });
  ok(`${tag} 横条底边不超过棋盘区顶边`,
    some.barRect.bottom <= some.boardRow.y + 1,
    { barBottom: some.barRect.bottom, boardsTop: some.boardRow.y });
  ok(`${tag} 横条顶边在对手条之下`,
    some.barRect.y >= some.oppInfo.bottom - 1,
    { barTop: some.barRect.y, oppBottom: some.oppInfo.bottom });

  // 空场地保留矮栏；生效后展示概念图中的卡面横幅。两态的高度差是用户指定的行为。
  ok(`${tag} 空场地是矮占位栏`,
    none.barRect.h >= 28 && none.barRect.h <= 38, none.barRect.h);
  ok(`${tag} 生效场地扩展成卡面横幅`,
    some.barRect.h >= (vh <= 760 ? 42 : 100) && some.barRect.h >= none.barRect.h + (vh <= 760 ? 8 : 30),
    { none: none.barRect.h, has: some.barRect.h });
  ok(`${tag} 高屏显示卡面图案，所有宽屏均有详情入口和醒目卡名`,
    (vh <= 760 || some.fmArt?.w >= 50) && some.fmDetails?.w >= 70 && some.fmNameFont >= 17,
    { art: some.fmArt, details: some.fmDetails, titleFont: some.fmNameFont });

  // --- 棋盘不能被改坏 ---
  ok(`${tag} 棋盘尺寸与基线一致`, some.boardRects.every((r) => r.w === spec.board && r.h === spec.board),
    { got: some.boardRects.map((r) => [r.w, r.h]), want: spec.board });
  ok(`${tag} 棋盘格子宽度与基线一致`, some.cellSize === spec.cell,
    { got: some.cellSize, want: spec.cell });
  // ⚠️ 从 6 行改到 7 行是本次「长久效果胶囊条」任务的有意改动：新行 3 专供效果胶囊，
  //    无效果时 auto 轨道塌成 0 高。这里钉的是「除新加的那一行外没有别的新行」。
  ok(`${tag} 格子行数仍为 7 行（只多了效果胶囊那一行）`,
    some.gridRowCount === 7, { rows: some.gridRows, count: some.gridRowCount });
  ok(`${tag} 棋盘零遮挡（两态每块棋盘 5 点全命中棋盘）`,
    some.boardOccluded.every((o) => o.hit === 0 && o.sampled === 5)
    && none.boardOccluded.every((o) => o.hit === 0 && o.sampled === 5),
    { has: some.boardOccluded, none: none.boardOccluded });

  // --- 横向不滚动、不与其它区叠压 ---
  ok(`${tag} 页面无横向滚动`, some.docScrollW === some.docClientW, { sw: some.docScrollW, cw: some.docClientW });
  ok(`${tag} 横条完整落在视口内`,
    some.barRect.x >= -1 && some.barRect.right <= some.vp[0] + 1,
    { x: some.barRect.x, right: some.barRect.right, vw: some.vp[0] });
  ok(`${tag} 横条自身文字没有溢出（nowrap 兜住了）`,
    some.barOverflow === 'hidden' && some.barScrollW <= some.barClientW + 1,
    { overflow: some.barOverflow, sw: some.barScrollW, cw: some.barClientW });
  const overlaps = [
    ['操作列', some.turnIndicator], ['手牌', some.magicSystem],
    ['舰队', some.fleet], ['弃牌堆', some.discard], ['连锁槽', some.chainSlot],
  ].filter(([, r]) => r && !(some.barRect.bottom <= r.y + 0.5 || some.barRect.y >= r.bottom - 0.5));
  ok(`${tag} 横条不与操作列/手牌/舰队/弃牌堆/连锁槽叠压`, overlaps.length === 0,
    overlaps.map(([n]) => n));
  ok(`${tag} 手牌仍然全部可见可点`,
    some.handCards > 0 && some.handClickable === some.handCards,
    { cards: some.handCards, clickable: some.handClickable });

  // --- 内容：全部来自真实数据 ---
  ok(`${tag} 无场地时是占位态（?.no-magic 在，文案含"暂无"）`,
    none.cfmHasNoMagic && /暂无/.test(none.cfmText || ''), none.cfmText);
  ok(`${tag} 无场地时占位栏仍存在且不是 display:none`,
    none.barRect.w > 0 && none.barRect.h > 0, none.barRect);
  ok(`${tag} 有场地时横条含 卡名/类型/速阶/效果摘要/持续说明`,
    barTextHasAll(some.cfmText), some.cfmText);
  ok(`${tag} 有场地时不再渲染 .no-magic`, some.cfmHasNoMagic === false, some.cfmText);
  ok(`${tag} 三区档展开了类型/速阶/摘要/持续说明`,
    vh <= 760 ? (some.fmExtraShown[1] === true && some.fmExtraShown[2] === false)
      : some.fmExtraShown.every((v) => v === true), some.fmExtraShown);

  // --- 预览：悬停轻量浮层 + 点击完整详情 ---
  const tip = await ev(PREVIEW_ON); await sleep(80);
  ok(`${tag} 悬停出轻量预览浮层 .card-tooltip`,
    tip.tooltip === true, tip.tooltip ? tip.text.slice(0, 80) : '没有浮层');
  ok(`${tag} 浮层内容含卡名与效果描述`,
    !!tip.text && tip.text.indexOf('伊甸园') >= 0 && tip.text.indexOf('攻击次数') >= 0,
    tip.text ? tip.text.slice(0, 120) : null);
  const tipOff = await ev(PREVIEW_OFF); await sleep(60);
  ok(`${tag} 移开鼠标后浮层消失`, tipOff.tooltip === false, tipOff.tooltip);

  const det = await ev(DETAIL_OPEN); await sleep(80);
  ok(`${tag} 点击弹完整详情 #card-detail-overlay`, det.overlay === true, det.overlay);
  ok(`${tag} 详情内容含卡名/速阶/类型/效果描述`,
    !!det.text && ['伊甸园', '速阶：1', '类型：场地', '攻击次数'].every((k) => det.text.indexOf(k) >= 0),
    det.text ? det.text.slice(0, 140) : null);
  ok(`${tag} 详情有关闭按钮`, det.hasClose === true, det.hasClose);
  const esc = await ev(DETAIL_ESC); await sleep(60);
  ok(`${tag} ESC 能关掉详情`, esc.overlay === false, esc.overlay);

  // 无场地时点击不应弹任何东西
  await ev(SET_NONE); await sleep(100);
  const detNone = await ev(DETAIL_NONE);
  ok(`${tag} 占位态点击不弹详情`, detNone.overlay === false, detNone.overlay);
  console.log('');
}

for (const [vw, vh] of compactList) {
  const tag = `${vw}x${vh}`;
  console.log(`--- ${tag}  紧凑档（横条不参与三区网格，只验证没被改坏）`);
  await send('Emulation.setDeviceMetricsOverride', { width: vw, height: vh, deviceScaleFactor: 1, mobile: false });
  await ev(SETUP); await ev(FREEZE); await sleep(300);
  await ev(`(function(){ if (window.AdaptiveLayout) AdaptiveLayout.apply(); return 1; })()`);
  await sleep(200);
  await ev(SET_NONE); await sleep(120);
  const none = await ev(MEASURE);
  await ev(SET_HAS); await sleep(120);
  const some = await ev(MEASURE);
  await shot(`${tag}-has`);

  if (none.__exc || some.__exc) { ok(`${tag} 探针可求值`, false, none.__exc || some.__exc); continue; }

  // 紧凑档的契约与三区档不同：这里没有「顶部横条」，场地魔法是一条内联胶囊，
  // 且**项目既有决定**是无场地时整条隐藏（`#game-screen[data-field-magic="none"] .field-magic-area{display:none}`）。
  // 因此紧凑档**不**要求两态零跳动 —— 消掉这个位移需要常驻占位胶囊，会永久吃掉一行，
  // 而 664×336 的纵向预算刚好用满。
  // 紧凑档这里只要求：横条不撑出视口 / 不外露长文本 / 有场地时仍显示卡名 / 不遮挡棋盘。
  ok(`${tag} 确实落在紧凑档`, /layout-compact/.test(some.body), some.body);
  ok(`${tag} 两态都无横向滚动`,
    none.docScrollW === none.docClientW && some.docScrollW === some.docClientW,
    { none: [none.docScrollW, none.docClientW], has: [some.docScrollW, some.docClientW] });
  ok(`${tag} 横条右边界不越出视口`,
    some.barRect.right <= some.vp[0] + 1, { right: some.barRect.right, vw: some.vp[0] });
  ok(`${tag} 紧凑档不外露长文本（.fm-meta/.fm-desc/.fm-duration 全隐藏）`,
    some.fmExtraShown.every((v) => v === false || v === null), some.fmExtraShown);
  ok(`${tag} 横条文字不溢出`,
    some.barScrollW == null || some.barScrollW <= some.barClientW + 1,
    { sw: some.barScrollW, cw: some.barClientW });
  ok(`${tag} 有场地时仍含卡名`, /伊甸园/.test(some.cfmText || ''), some.cfmText);
  ok(`${tag} 无场地时保持项目既有的隐藏行为（不新增长驻占位）`,
    none.barRect.w === 0 && none.barRect.h === 0 && none.cfmHasNoMagic === true,
    { barRect: none.barRect, noMagic: none.cfmHasNoMagic });
  ok(`${tag} 有场地时横条不遮挡棋盘`,
    some.boardOccluded.filter((o) => o.sampled > 0).every((o) => o.hit === 0),
    some.boardOccluded);
  console.log('');
}

console.log(`\n断言 ${pass + fail} 条：PASS ${pass} / FAIL ${fail}`);
if (fail) { console.log('失败项：'); failures.forEach((f) => console.log('  - ' + f)); }
else console.log('结果: 全部通过');

ws.close(); browser.kill();
process.exit(fail ? 1 : 0);
