#!/usr/bin/env node
/**
 * 落地验收出图（供人工逐张看）—— 走**真实对局流程**，不靠强制布局类。
 *
 * 为什么必须真流程：本项目踩过"强制加 layout-* 类"的探针给出误导数字
 * （不设 --stage-vh，量出来的格宽与真实档位对不上）。这里学 hand_play_check.mjs
 * 那套：两个标签页各当一个玩家，create_room / join_room / place_ships / rps_choice
 * 一路走真 socket，进了对局屏之后才开始出图。
 *
 * 出图清单（默认落 .tmp/acceptance/）：
 *   01-home-fluent.png      首页 · 默认预设（对照）
 *   02-home-arena.png       首页 · 竞技场预设（Phase 1）
 *   03-ingame-hand.png      对局 · 手牌扇形 + 真卡（Phase 2）
 *   04-ingame-chain.png     对局 · 连锁叠牌（Phase 3）
 *   05-target-select.png    对局 · 目标选择态（Phase 4，虚线锚点 + 确认按钮文案）
 *   06-mobile-hand.png      手机 390×844 · 紧凑手牌 + 抽屉大卡面（Phase 5.3）
 *   07-codex.png            图鉴 · 真卡（Phase 6）
 *
 * 用法：node tools/acceptance_shots.mjs --url http://127.0.0.1:5055/ [--out dir]
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const OUT = argOf('--out', '.tmp/acceptance');
// ⚠️ 2026-09-27：--w/--h 以前是**声明了但没接线**的（用法行里写着、代码里没人读），
//    于是对局那几张图永远出在浏览器默认窗口上（实测 749x489 = 紧凑档），
//    宽屏三区布局根本没法用这个工具验收。现在真的按传入的宽高走，
//    并且**同时**设到实际先手那个标签页上（以前只设了 A 页；先手是 B 时全部白设）。
const VW = Number(argOf('--w', 1600)) || 1600;
const VH = Number(argOf('--h', 1000)) || 1000;
const PORT = 9474;
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome'); process.exit(0); }
fs.mkdirSync(OUT, { recursive: true });

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--remote-debugging-port=' + PORT, '--user-data-dir=C:/Windows/Temp/acceptance_profile', APP], { stdio: 'ignore' });
await sleep(3500);

async function openTab(url) {
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`,
    { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let seq = 0; const pend = new Map();
  ws.onmessage = (m) => { const x = JSON.parse(m.data); if (x.id && pend.has(x.id)) { const { res, rej } = pend.get(x.id); pend.delete(x.id); x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result); } };
  const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + method)); } }, 30000); });
  await send('Runtime.enable');
  const ev = async (e) => { const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 300) }; return r.result && r.result.value; };
  const ready = async () => { const t0 = Date.now(); while (Date.now() - t0 < 20000) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true; await sleep(200); } return false; };
  const shot = async (file) => { const r = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(path.join(OUT, file), Buffer.from(r.data, 'base64')); console.log('  SHOT ' + file); };
  const viewport = async (w, h, mobile) => { await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: !!mobile }); await send('Emulation.setTouchEmulationEnabled', { enabled: !!mobile, maxTouchPoints: 5 }); await sleep(700); };
  return { ev, send, ready, shot, viewport, ws };
}

// ---------------------------------------------------------------- 首页（两档预设对照）
console.log('--- 首页：默认预设 vs 竞技场预设 ---');
const H = await openTab(APP);
await H.ready();
await H.viewport(VW, VH, false);
await H.ev('(function(){ try { localStorage.removeItem("battleship_theme_preset"); } catch(e){} return 1; })()');
await H.send('Page.reload');
await sleep(2500); await H.ready();
await H.shot('01-home-fluent.png');
await H.ev('(function(){ if (typeof applyThemePreset === "function") applyThemePreset("arena"); return document.documentElement.dataset.themePreset; })()');
await sleep(900);
await H.shot('02-home-arena.png');

// ---------------------------------------------------------------- 真对局
console.log('--- 真对局：两个标签页各当一个玩家 ---');
const A = await openTab(APP), B = await openTab(APP);
await A.ready(); await B.ready();
await A.viewport(VW, VH, false);
const created = await A.ev(`new Promise(function(res){
  ensureSocket(); gameState.playerName='ShotA';
  gameState.socket.emit('create_room', { player_name:'ShotA' }, function(r){ res(r); });
})`);
const roomId = created.room_id;
const joined = await B.ev(`new Promise(function(res){
  ensureSocket(); gameState.playerName='ShotB';
  gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name:'ShotB' }, function(r){ res(r); });
})`);
await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
const st0 = await A.ev(`new Promise(function(res){ gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); }); })`);
const bPid = joined.player_id;
const aPid = Object.keys(st0.game_state.players).find((p) => p !== bPid);
await A.ev(`gameState.playerId = ${JSON.stringify(aPid)}; true`);
await B.ev(`gameState.playerId = ${JSON.stringify(bPid)}; true`);
const ships = (seed) => Array.from({ length: 6 }, (_, i) => ({ positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [] }));
await A.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: gameState.roomId, player_id: ${JSON.stringify(aPid)}, ships: ${JSON.stringify(ships(0))} }, function(r){ res(r); }); })`);
await B.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: gameState.roomId, player_id: ${JSON.stringify(bPid)}, ships: ${JSON.stringify(ships(1))} }, function(r){ res(r); }); })`);
let attacker = null;
for (let i = 0; i < 12 && !attacker; i++) {
  await A.ev(`new Promise(function(res){ gameState.socket.emit('rps_choice', { room_id: gameState.roomId, player_id: ${JSON.stringify(aPid)}, choice:'rock' }, function(r){ res(r); }); })`);
  await B.ev(`new Promise(function(res){ gameState.socket.emit('rps_choice', { room_id: gameState.roomId, player_id: ${JSON.stringify(bPid)}, choice:'paper' }, function(r){ res(r); }); })`);
  await sleep(400);
  const s = await A.ev(`new Promise(function(res){ gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); }); })`);
  attacker = s.game_state.current_attacker;
}
const atk = attacker === aPid ? A : B;
const atkPid = attacker;
await atk.ev(`gameState.playerId = ${JSON.stringify(atkPid)}; true`);
await atk.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
console.log('  先手 = ' + (attacker === aPid ? 'A' : 'B'));
// 先手那页才是出图页：把 --w/--h 也设到它身上（详见文件头 VW/VH 的说明）
await atk.viewport(VW, VH, false);

// ⚠️ 本工具是**绕过 UI 直接发 socket** 推进对局的（摆船/猜拳都没点页面按钮），
//    所以客户端的 #ship-placement-screen 仍处于 active、把对局内容顶到下面去，
//    按卡片矩形裁出来的近景会落在空白上（实测 y=1410、视口只有 844）。
//    出图前把屏幕状态对齐到"就在对局屏"——这里只为了截图，流程正确性由别的门禁覆盖。
await atk.ev(`(function(){
  if (typeof showScreen === 'function') { try { showScreen('game-screen'); return 'showScreen'; } catch(e){} }
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  var gs = document.getElementById('game-screen'); if (gs) gs.classList.add('active');
  return 'forced';
})()`);
await sleep(600);

// 发 5 张卡（含需要目标的「冻结」，供 Phase 4 出图）
for (const n of ['神威！', '失灵！', '冻结', '八方来财', '看破！']) {
  await atk.ev(`new Promise(function(res){
    gameState.socket.emit('test_add_specific_magic_card', { room_id: gameState.roomId,
      player_id: gameState.playerId, card_name: ${JSON.stringify(n)} }, function(r){ res(r); });
  })`);
}
await sleep(900);

// ---------------------------------------------------------------- 03 手牌扇形 + 真卡
console.log('--- 03 对局 · 手牌 ---');
await atk.ev(`(function(){
  // 让扇形有东西可摆：把 5 张都渲染出来（服务端刚发过 hand_updated）
  if (typeof updateHandUI === 'function') updateHandUI();
  return document.querySelectorAll('#magic-hand .magic-card').length;
})()`);
await sleep(600);
await atk.shot('03-ingame-hand.png');

// ---------------------------------------------------------------- 04 连锁叠牌
console.log('--- 04 对局 · 连锁叠牌 ---');
await atk.ev(`(function(){
  gameState.chain = [
    { card:{name:'百亿补贴', speed:2, type:'普通', description:'每有一艘船死亡就加3攻击次数'}, playerId:'other' },
    { card:{name:'冻结', speed:3, type:'普通', description:'冻结一个 3×3 区域'}, playerId: gameState.playerId },
    { card:{name:'失灵！', speed:3, type:'普通', description:'无效化上一张魔法卡'}, playerId:'other' },
  ];
  if (typeof updateChainUI === 'function') updateChainUI();
  return 1;
})()`);
await sleep(700);
await atk.shot('04-ingame-chain.png');
await atk.ev('(function(){ gameState.chain = []; if (typeof updateChainUI === "function") updateChainUI(); return 1; })()');

// ---------------------------------------------------------------- 05 目标选择态
console.log('--- 05 对局 · 目标选择态 ---');
await atk.ev(`(function(){
  var i = (gameState.hand||[]).findIndex(function(c){ return c && c.name === '冻结'; });
  if (i < 0) return 'no-card';
  var cards = document.querySelectorAll('#magic-hand .magic-card');
  if (cards[i]) cards[i].click();
  return 'picked';
})()`);
await sleep(400);
await atk.ev(`(function(){
  var i = (gameState.hand||[]).findIndex(function(c){ return c && c.name === '冻结'; });
  var cards = document.querySelectorAll('#magic-hand .magic-card');
  if (cards[i]) cards[i].click();
  return 'opened';
})()`);
await sleep(700);
// 点一格定位（让按钮文案变成「确认使用 冻结！」、锚点变实框）
await atk.ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="1"][data-y="2"]');
  if (c) c.click();
  return 1;
})()`);
await sleep(600);
console.log('  ' + JSON.stringify(await atk.ev(`(function(){
  var b = document.getElementById('area-confirm');
  return { text: b ? b.textContent : null, disabled: b ? b.disabled : null,
           anchors: document.querySelectorAll('#opponent-board .cell.sel-anchor').length };
})()`)));
await atk.shot('05-target-select.png');
await atk.ev('(function(){ var b=document.querySelector("#area-cancel"); if(b) b.click(); return 1; })()');
await sleep(300);

// ---------------------------------------------------------------- 06 手机手牌 + 大卡面
console.log('--- 06 手机 390×844 · 抽屉大卡面 ---');
await atk.viewport(390, 844, true);
await sleep(1200);
await atk.ev(`(function(){
  var i = (gameState.hand||[]).findIndex(function(c){ return c && c.name === '神威！'; });
  if (i < 0) i = 0;
  var cards = document.querySelectorAll('#magic-hand .magic-card');
  if (cards[i]) cards[i].click();
  var dock = document.getElementById('aux-dock');
  if (dock) { dock.dataset.open = 'true'; dock.dataset.tab = 'card'; }
  if (typeof setDockOpen === 'function') { try { setDockOpen(true); } catch(e){} }
  var c = gameState.hand[i];
  if (typeof updateCardPreview === 'function') updateCardPreview(c, i);
  return 1;
})()`);
await sleep(900);
await atk.shot('06-mobile-hand.png');

// ---------------------------------------------------------------- 07 图鉴
console.log('--- 07 图鉴 · 真卡 ---');
await H.viewport(VW, VH, false);
await H.ev(`(function(){
  var m = document.getElementById('help-modal'); if (m) m.classList.remove('hidden');
  if (typeof renderCardCompendium === 'function') renderCardCompendium();
  var q = document.getElementById('compendium-search'); if (q) q.value = '';
  return 1;
})()`);
await sleep(900);
await H.shot('07-codex.png');

// ---------------------------------------------------------------- 08/09 卡面近景（native 分辨率）
// 手牌卡在整屏截图里只有 ~90px 宽，看不出卡面分区 —— 这里按卡的元素矩形裁一张放大的近景。
// ⚠️ CDP 的 clip 字段是 x/y/width/height/scale（不是 w/h），写错会报
//    "Failed to deserialize params.clip.height - mandatory field missing"。
console.log('--- 08/09 卡面近景（宽屏 / 手机各一张）---');
async function closeup(tab, file, scale, pad) {
  const box = await tab.ev(`(function(){
    var cards = document.querySelectorAll('#magic-hand .magic-card');
    if (!cards.length) return null;
    var a = cards[0].getBoundingClientRect();
    var b = cards[cards.length-1].getBoundingClientRect();
    return { x: Math.max(0, Math.round(a.left) - ${pad}), y: Math.max(0, Math.round(a.top) - ${pad}),
             width: Math.round(b.right - a.left) + 2*${pad}, height: Math.round(Math.max(a.bottom,b.bottom) - a.top) + 2*${pad} };
  })()`);
  if (!box || !Number.isFinite(box.width) || !Number.isFinite(box.height) || box.width <= 0 || box.height <= 0) {
    console.log('  跳过 ' + file + '（拿不到卡片矩形：' + JSON.stringify(box) + '）');
    return;
  }
  const r = await tab.send('Page.captureScreenshot', { format: 'png', clip: { x: box.x, y: box.y, width: box.width, height: box.height, scale } });
  fs.writeFileSync(path.join(OUT, file), Buffer.from(r.data, 'base64'));
  console.log('  SHOT ' + file + '  ' + JSON.stringify(box) + ' @' + scale + 'x');
}
await atk.viewport(VW, VH, false);
await sleep(1000);
await atk.ev(`(function(){ if (typeof updateHandUI === 'function') updateHandUI(); return 1; })()`);
await sleep(500);
await closeup(atk, '08-card-closeup-wide.png', 2, 8);
await atk.viewport(390, 844, true);
await sleep(1200);
// 手机档的这张近景**必须强制布局类**：本工具是绕过 UI 直接发 socket 推进的，
// #ship-placement-screen 一直 active（实测 placeActive:true），把对局内容顶到 y≈1416，
// 按卡片矩形裁出来是空白。真实用户走 UI 不会到这个状态（紧凑档门禁量到的手牌在 y=684 视口内）。
// 这里与 tools/mobile_bigcard_check.mjs 用同一套"强制 + 重渲染"的出图口径。
await atk.ev(`(function(){
  document.body.className = 'layout-ingame layout-compact';
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  var gs = document.getElementById('game-screen'); if (gs) gs.classList.add('active');
  var ms = document.getElementById('magic-system'); if (ms) ms.classList.remove('hand-empty');
  if (typeof updateHandUI === 'function') updateHandUI();
  return document.body.className;
})()`);
await sleep(700);
// ⚠️ 手机档的**手牌近景**不在这里出图：本工具靠 viewport 来回切 + 绕过 UI 发 socket 推进，
//    量到的 --board-size 会残留上一档的值 → 棋盘那行把手机手牌顶到视口外（实测 y=1118，
//    docH 只有 845），裁出来是空白。那是**合成状态**，真实流程不是这样：
//      · 紧凑档布局由 tools/ui_layout_check.mjs --only compact 走真流程验（手牌 y=684 在 844 视口内）；
//      · 手机卡面由 tools/mobile_bigcard_check.mjs 自己出图（它用干净的"强制+重渲染"口径，
//        实测 200×280、说明完整可读）。
//    这里只保留宽屏近景（在同一个 tab 上先切成 1600×1000，无残留）。

console.log('\n出图目录: ' + OUT);
browser.kill();
process.exit(0);
