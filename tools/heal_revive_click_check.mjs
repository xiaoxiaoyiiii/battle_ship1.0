#!/usr/bin/env node
/**
 * 疗愈复活后，那一格必须能被对方重新点击攻击（前端部分）。
 *
 * 真正卡住玩家的是这一层：
 *   initGameBoards() 只在 `!alreadyAttacked` 时才给对手棋盘的格子绑点击监听。
 *   服务端把格子从攻击历史里清掉后，如果没把结果重发给前端，
 *   前端本地 myAttacks 里还留着那格 → 格子继续画 ✕ 且【没有点击监听】，
 *   玩家点它毫无反应（作者报的"无法攻击这个复活的格子"）。
 *
 * 断言：
 *   · 前提：打过的格子画着 ✕ 且点不动
 *   · 收到真实的 board_attacks_updated 后：✕ 消失
 *   · ★ 那一格重新获得点击监听（点下去会发出 attack）
 *   · 没被清理的格子仍然保留 ✕ 且仍然点不动
 *
 * 用法：node tools/heal_revive_click_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9419;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome'); process.exit(0); }

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/heal_click', '--window-size=1280,900', APP], { stdio: 'ignore' });
await sleep(3200);

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || ''))
  || list.find((t) => t.type === 'page');
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
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq; pend.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method, params }));
  setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout')); } }, 20000);
});
await send('Runtime.enable');
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return 'EXC: ' + JSON.stringify(r.exceptionDetails).slice(0, 250);
  return r.result && r.result.value;
};
const t0 = Date.now();
while (Date.now() - t0 < 15000) {
  if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break;
  await sleep(200);
}

const SETUP = `(function(){
  if (typeof switchScreen === 'function' && typeof gameScreen !== 'undefined' && gameScreen) {
    switchScreen(gameScreen);
  } else {
    document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
    var el = document.getElementById('game-screen');
    if (el) el.classList.add('active');
  }
  // ⚠️ 必须在换掉 socket 之前把页面真实注册的监听器抄下来，
  // 否则投递事件时抓不到（game.js 用 socket.on 注册，列表存在 _callbacks 里）。
  if (!window.__realCallbacks) {
    if (!gameState.socket) { ensureSocket(); }
    window.__realCallbacks = (gameState.socket && gameState.socket._callbacks) || {};
  }
  window.__sent = [];
  gameState.socket = {
    emit: function(name, payload){ window.__sent.push({ name: name, payload: payload }); },
    on: function(){ return this; }
  };
  window.__alerts = [];
  window.showAlert = function(m){ window.__alerts.push(String(m)); };
  gameState.roomId = 'r1';
  gameState.playerId = 'me';
  // ⚠️ 阶段/回合必须设齐：handleAttack 里有一串守卫
  // （currentMagicCard / isMyTurn / freezeAlert / currentPhase / 次数），
  // 少设一个就会在守卫处 return —— 那样"点不动"就不是"没绑监听"了，
  // 前面的前提断言会变成假通过。下面每条点击断言都同时看有没有弹提示来区分。
  gameState.currentPhase = 'battle';
  gameState.currentAttacker = 'me';
  gameState.currentMagicCard = null;
  gameState.frozen = false;
  gameState.ships = [];
  gameState.opponentAttacks = [];
  gameState.revealedCells = [];
  gameState.sacrificedSelf = [];
  // 我打过对手两格：(2,5) 打中（就是被疗愈原地复活的那格），(0,0) 打空
  gameState.myAttacks = [
    { x: 2, y: 5, hit: true },
    { x: 0, y: 0, hit: false },
  ];
  return Object.keys(window.__realCallbacks).filter(function(k){
    return k.indexOf('board_attacks') >= 0;
  });
})()`;
const registered = await ev(SETUP);
check(Array.isArray(registered) && registered.includes('$board_attacks_updated'),
  '页面注册了 board_attacks_updated 监听', registered);
await sleep(200);

async function fire(eventName, payload) {
  return await ev(`(function(){
    var cbs = (window.__realCallbacks || {})['$${eventName}'];
    if (!cbs || !cbs.length) return 'no-listener';
    cbs.forEach(function(cb){ cb(${JSON.stringify(payload)}); });
    return 'ok';
  })()`);
}
async function refreshTurn(attacker, attacks) {
  await ev(`(function(){
    if (typeof updateTurnIndicator === 'function') {
      updateTurnIndicator(${JSON.stringify(attacker)}, ${JSON.stringify(String(attacks))});
    }
    return true;
  })()`);
  await sleep(200);
}
function cellState(x, y) {
  return ev(`(function(){
    var c = document.querySelector('#opponent-board .cell[data-x="${x}"][data-y="${y}"]');
    if (!c) return 'no-cell';
    return { cls: c.className, text: c.textContent };
  })()`);
}
async function clickCell(x, y) {
  await ev(`(function(){ window.__sent = []; window.__alerts = []; return true; })()`);
  await ev(`(function(){
    var c = document.querySelector('#opponent-board .cell[data-x="${x}"][data-y="${y}"]');
    if (c) c.click();
    return true;
  })()`);
  await sleep(250);
  return {
    sent: await ev('window.__sent || []'),
    alerts: await ev('window.__alerts || []'),
  };
}

await refreshTurn('me', 3);
const screenOk = await ev(`document.getElementById('game-screen').classList.contains('active')`);
check(screenOk === true, '（前提）已进入对局界面', screenOk);
check(await ev(`gameState.isMyTurn === true`) === true, '（前提）isMyTurn 已就位', await ev('gameState.isMyTurn'));
check(await ev(`document.getElementById('attacks-remaining').textContent`) === '3',
  '（前提）攻击次数显示为 3', await ev(`document.getElementById('attacks-remaining').textContent`));

// ---- 前提：打过的格子画着 ✕ 且点不动 ----
const before = await cellState(2, 5);
check(/hit/.test(String(before.cls)), '（前提）打过的格子带着 hit 类（红色 ✕）', before);
const beforeClick = await clickCell(2, 5);
check(beforeClick.sent.length === 0 && beforeClick.alerts.length === 0,
  '（前提）打过的格子点它【既没发请求也没弹提示】= 真的没绑监听（不是被守卫拦下）',
  beforeClick);

// ---- 喂真实事件：把 (2,5) 从列表里去掉（模拟疗愈复活后的重发） ----
const fired = await fire('board_attacks_updated', {
  my_attacks: [{ x: 0, y: 0, hit: false }],
  opponent_attacks: [],
});
check(fired === 'ok', '事件已投递给页面真实监听器', fired);
await sleep(350);

const after = await cellState(2, 5);
check(!/hit|miss/.test(String(after.cls)), '★ 收到更新后 (2,5) 的 ✕ 消失', after);
check((await cellState(0, 0)).cls.includes('miss'), '没被清理的格子仍然保留标记', await cellState(0, 0));

const sentAfter = await clickCell(2, 5);
const atk = sentAfter.sent.filter((s) => s.name === 'attack');
check(atk.length === 1, '★ 复活后的那一格重新可以点击攻击',
  { sent: sentAfter.sent.map((s) => s.name), alerts: sentAfter.alerts });
check(atk.length === 1 && atk[0].payload.x === 2 && atk[0].payload.y === 5,
  '发出的攻击坐标就是那一格', atk[0] && atk[0].payload);
const keptClick = await clickCell(0, 0);
check(keptClick.sent.length === 0 && keptClick.alerts.length === 0,
  '没被清理的格子仍然点不动（不会重复攻击同一格）', keptClick);

// ---- 复活的自己：棋盘上的 ✕ 也要擦掉 ----
await fire('board_attacks_updated', {
  my_attacks: [{ x: 0, y: 0, hit: false }],
  opponent_attacks: [],
});
await sleep(300);
await ev(`(function(){
  gameState.ships = [{ positions: [{x:2,y:5}], hits: [], frozen: false, alive: true }];
  gameState.opponentAttacks = [ { x: 2, y: 5, hit: true } ];
  initGameBoards();
  return true;
})()`);
await sleep(250);
const ownBefore = await ev(`(function(){
  var c = document.querySelector('#game-player-board .cell[data-x="2"][data-y="5"]');
  return c ? c.className : 'no-cell';
})()`);
check(/hit/.test(String(ownBefore)), '（前提）自己棋盘上那格也画着对方的 ✕', ownBefore);
await fire('board_attacks_updated', { my_attacks: [{ x: 0, y: 0, hit: false }], opponent_attacks: [] });
await sleep(350);
const ownAfter = await ev(`(function(){
  var c = document.querySelector('#game-player-board .cell[data-x="2"][data-y="5"]');
  return c ? { cls: c.className, hasShip: c.classList.contains('ship') } : 'no-cell';
})()`);
check(!/hit|miss/.test(String(ownAfter.cls)),
  '★ 复活方自己棋盘上的 ✕ 也被擦掉了', ownAfter);
check(ownAfter.hasShip === true, '复活的那艘船仍在棋盘上（没被误删）', ownAfter);

console.log('');
if (problems.length) {
  console.log(`✗ ${problems.length} 项未通过：`);
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}
try { ws.close(); } catch (e) {}
browser.kill();
process.exit(problems.length ? 1 : 0);
