#!/usr/bin/env node
/**
 * 绝处逢生「候选格画在哪块棋盘」的回归检查（无头 Edge + CDP）。
 *
 * 作者实测（2026-09-16）：自己放绝处逢生后，属于**自己棋盘**的候选格被画到了
 * **对手棋盘**上 —— 看起来像"敌方可能在这几格"，直接误导自己的攻击。
 *
 * 根因：initGameBoards() 里两块棋盘是两个独立循环，而候选格只写在对手棋盘那个
 * 循环里；服务端下发的 last_stand_cells 也不带归属，前端无从判断。
 * 修法：载荷加 owner，前端按 owner 决定画在哪块棋盘。
 *
 * 用法：node tools/last_stand_board_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9447;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  // profile 放项目内 .tmp/（C:/Windows/Temp 出现过 ACL 损坏）
  '--user-data-dir=' + path.join(HERE, '..', '.tmp', 'last_stand_board_profile'),
  '--window-size=1600,1000', 'about:blank'], { stdio: 'ignore' });
await sleep(3000);

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || '')) ||
  list.find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0; const pend = new Map();
ws.onmessage = (m) => {
  const x = JSON.parse(m.data);
  if (x.id && pend.has(x.id)) { const p = pend.get(x.id); pend.delete(x.id); x.error ? p.j(new Error(JSON.stringify(x.error))) : p.r(x.result); }
};
const send = (method, params = {}) => new Promise((r, j) => { const id = ++seq; pend.set(id, { r, j }); ws.send(JSON.stringify({ id, method, params })); });
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return 'EXC: ' + (r.exceptionDetails.exception?.description || '').slice(0, 220);
  return r.result && r.result.value;
};

const problems = [];
const check = (ok, label, detail) => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
};

await send('Page.enable');
await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: APP });
await sleep(2800);

await ev(`(function(){
  if (typeof switchScreen === 'function' && typeof gameScreen !== 'undefined' && gameScreen) switchScreen(gameScreen);
  gameState.playerId = 'me'; gameState.roomId = 'r1';
  window.__fired = [];
  var s = gameState.socket;
  if (!s) return 'no-socket';
  if (!s.__realEmit) { s.__realEmit = s.emit; s.emit = function (ev, data, cb) { window.__fired.push({ ev: ev, data: data }); if (typeof cb === 'function') { try { cb({ status: 'success' }); } catch (e) {} } }; }
  return 'ready'; })()`);
await sleep(300);

// 触发页面**真实注册**的 last_stand_cells 监听器
async function fire(cells, owner) {
  return await ev(`(function(){
    var cbs = gameState.socket && gameState.socket._callbacks && gameState.socket._callbacks['$last_stand_cells'];
    if (!cbs || !cbs.length) return 'no-handler';
    cbs[0]({ cells: ${JSON.stringify(cells)}, owner: ${JSON.stringify(owner)} });
    return 'ok'; })()`);
}

function countExpr(board, cls) {
  return `document.querySelectorAll('#${board} .cell.${cls}').length`;
}

// ---- 1. owner = 我 → 高亮必须在我的棋盘 ----
let r = await fire([{ x: 1, y: 1 }, { x: 3, y: 4 }], 'me');
check(r === 'ok', '1a 触发 last_stand_cells（owner = 我）', r);
await sleep(350);
const mineOnMine = await ev(countExpr('game-player-board', 'last-stand-candidate'));
const mineOnOpp = await ev(countExpr('opponent-board', 'last-stand-candidate'));
check(mineOnMine === 2, '★ 1b 我放的候选格高亮在【我的】棋盘（2 格）', mineOnMine);
check(mineOnOpp === 0, '★ 1c 绝不在【对手】棋盘上出现（作者报的 bug）', mineOnOpp);

// 候选格不能被画成叉（09-14 的教训：一画叉玩家就以为打不了）
const wronglyHit = await ev(`document.querySelectorAll('#game-player-board .cell.last-stand-candidate.hit, #game-player-board .cell.last-stand-candidate.miss').length`);
check(wronglyHit === 0, '1d 候选格没有被画成命中/落空（否则玩家以为打不了）', wronglyHit);

// ---- 2. owner = 对方 → 高亮必须在攻击目标棋盘 ----
r = await fire([{ x: 2, y: 2 }], 'opp');
check(r === 'ok', '2a 触发 last_stand_cells（owner = 对方）', r);
await sleep(350);
const oppOnOpp = await ev(countExpr('opponent-board', 'last-stand-candidate'));
const oppOnMine = await ev(countExpr('game-player-board', 'last-stand-candidate'));
check(oppOnOpp === 1, '★ 2b 对方放的候选格高亮在【攻击目标】棋盘（1 格）', oppOnOpp);
check(oppOnMine === 0, '★ 2c 不该出现在我自己的棋盘上', oppOnMine);
const oppClickable = await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="2"][data-y="2"]');
  if (!c) return 'missing';
  return { blocked: c.classList.contains('blocked') || c.disabled === true, cls: c.className }; })()`);
check(oppClickable && oppClickable.blocked === false, '2d 候选格仍可点（对方要能往这几格打）', oppClickable);

// ---- 3. 清空 ----
r = await fire([], null);
check(r === 'ok', '3a 触发清空', r);
await sleep(300);
const afterClear = await ev(`document.querySelectorAll('.last-stand-candidate').length`);
check(afterClear === 0, '3b 清空后两块棋盘都不再高亮', afterClear);

console.log('');
if (problems.length) {
  console.log('✗ ' + problems.length + ' 项未通过：');
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}
try { ws.close(); } catch (e) {}
browser.kill();
process.exit(problems.length ? 1 : 0);
