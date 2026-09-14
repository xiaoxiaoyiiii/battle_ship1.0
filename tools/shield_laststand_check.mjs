#!/usr/bin/env node
/**
 * 「破盾格还能再打」「绝处逢生候选格能打」的前端回归检查（无头 Edge + CDP，喂真实事件）。
 *
 * 两个 bug 同一个病灶：**把"这一格打过了"当成铁律**。
 * `gameState.myAttacks / opponentAttacks` 同时决定两件事：
 *   ① 画不画 ✕   ② initGameBoards() 给不给这个格子绑 click
 * 于是"盾把炮弹吃了、船毫发无伤"和"绝处逢生的候选格（根本没被打过）"
 * 都被当成已打过 —— 玩家看到红叉、点下去毫无反应（作者实测反馈）。
 *
 * 覆盖：
 *   · attack_result{shield_blocked:true} → 画破盾标记（不是 ✕）、【仍然能点】
 *   · 之后真打中同一格 → 破盾标记消失、变成正常的 ✕，且不能再点
 *   · ship_sacrificed{reason:'last_stand'} → 不画叉、不误报成「恶魔契约」
 *   · last_stand_cells{cells:[...]} → 6 格高亮、不画叉、【能点】
 *   · last_stand_cells{cells:[]} → 高亮清除
 *
 * 用法：node tools/shield_laststand_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9437;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/shield_laststand_profile', APP], { stdio: 'ignore' });
await sleep(3000);

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || ''));
if (!page) { console.error('找不到页面'); process.exit(1); }
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
  setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
});
await send('Runtime.enable');
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
};

const t0 = Date.now();
while (Date.now() - t0 < 20000) {
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
  // ⚠️ 换掉 socket 之前先把页面真实注册的监听器抄下来
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
  window.__msgs = [];
  window.showAlert = function(m){ window.__alerts.push(String(m)); };
  window.showMessage = function(m){ window.__msgs.push(String(m)); };
  gameState.roomId = 'r1';
  gameState.playerId = 'me';
  gameState.currentPhase = 'battle';
  gameState.currentAttacker = 'me';
  gameState.currentMagicCard = null;
  gameState.frozen = false;
  gameState.ships = [];
  gameState.myAttacks = [];
  gameState.opponentAttacks = [];
  gameState.revealedCells = [];
  gameState.sacrificedSelf = [];
  gameState.sacrificedOpponent = [];
  gameState.shieldBrokenMine = [];
  gameState.shieldBrokenOpponent = [];
  gameState.lastStandCells = [];
  updateTurnIndicator('me', '6');
  return Object.keys(window.__realCallbacks).filter(function(k){
    return k.indexOf('attack_result') >= 0 || k.indexOf('ship_sacrificed') >= 0
        || k.indexOf('last_stand_cells') >= 0;
  });
})()`;
const registered = await ev(SETUP);
check(Array.isArray(registered) && registered.includes('$attack_result')
      && registered.includes('$ship_sacrificed') && registered.includes('$last_stand_cells'),
  '页面注册了 attack_result / ship_sacrificed / last_stand_cells 监听', registered);
await sleep(250);

async function fire(eventName, payload) {
  return await ev(`(function(){
    var cbs = (window.__realCallbacks || {})['$${eventName}'];
    if (!cbs || !cbs.length) return 'no-listener';
    cbs.forEach(function(cb){ cb(${JSON.stringify(payload)}); });
    return 'ok';
  })()`);
}
function cellState(board, x, y) {
  return ev(`(function(){
    var c = document.querySelector('#${board}-board .cell[data-x="${x}"][data-y="${y}"]');
    if (!c) return 'no-cell';
    return { cls: String(c.className), text: c.textContent, title: c.title || '' };
  })()`);
}
async function clickCell(board, x, y) {
  await ev(`(function(){ window.__sent = []; window.__alerts = []; return true; })()`);
  await ev(`(function(){
    var c = document.querySelector('#${board}-board .cell[data-x="${x}"][data-y="${y}"]');
    if (c) c.click();
    return true;
  })()`);
  await sleep(250);
  return { sent: await ev('window.__sent || []'), alerts: await ev('window.__alerts || []') };
}
const attackEmit = (r) => (r.sent || []).filter((e) => e.name === 'attack');

// ===========================================================================
// A. 仁王之盾：破盾格画破盾标记，而且还能再打
// ===========================================================================
console.log('--- A. 仁王之盾破盾 ---');
const shieldResult = {
  attacker: 'me', x: 2, y: 5, hit: true, ship_sunk: false,
  remaining_attacks: 5, attacker_remaining_ships: 6, defender_remaining_ships: 6,
  shield_blocked: true,
};
await fire('attack_result', shieldResult);
await sleep(350);

const broken = await cellState('opponent', 2, 5);
check(/shield-broken/.test(String(broken.cls)),
  '★ 被盾挡下的格子画成「破盾」样式', broken);
check(!/(^|\s)hit(\s|$)/.test(String(broken.cls)),
  '★ 破盾格【不带】hit 类（不然看起来就是普通命中红叉）', broken);
check(String(broken.text).indexOf('✕') < 0, '破盾格不画 ✕', broken);

const clickBroken = await clickCell('opponent', 2, 5);
check(attackEmit(clickBroken).length === 1,
  '★★ 破盾之后同一回合【还能点这一格再打】（这是本次修的核心）', clickBroken);
check((clickBroken.alerts || []).length === 0,
  '点击破盾格没有被守卫拦下（不是"没反应"）', clickBroken.alerts);

// 真打中之后：破盾标记消失，变成正常的命中格，且不能再点
await fire('attack_result', {
  attacker: 'me', x: 2, y: 5, hit: true, ship_sunk: false,
  remaining_attacks: 4, attacker_remaining_ships: 6, defender_remaining_ships: 6,
  shield_blocked: false,
});
await sleep(350);
const afterHit = await cellState('opponent', 2, 5);
check(!/shield-broken/.test(String(afterHit.cls)),
  '第二炮真打中之后，破盾标记消失', afterHit);
check(/(^|\s)hit(\s|$)/.test(String(afterHit.cls)), '这一格变成正常的命中格', afterHit);
const clickHit = await clickCell('opponent', 2, 5);
check(attackEmit(clickHit).length === 0,
  '（前提）真打过之后的格子点不动了 —— 说明上一段的"能点"不是假通过', clickHit);

// 对方打过来的破盾：画在我自己棋盘上
await fire('attack_result', {
  attacker: 'them', x: 4, y: 1, hit: true, ship_sunk: false,
  remaining_attacks: 3, attacker_remaining_ships: 6, defender_remaining_ships: 6,
  shield_blocked: true,
});
await sleep(350);
const brokenMine = await cellState('game-player', 4, 1);
check(/shield-broken/.test(String(brokenMine.cls)),
  '对方打过来的破盾也在我自己棋盘上标出来', brokenMine);

// ===========================================================================
// B. 绝处逢生：候选格高亮、不画叉、能打
// ===========================================================================
console.log('');
console.log('--- B. 绝处逢生候选格 ---');
await ev(`(function(){
  gameState.sacrificedOpponent = [];
  gameState.lastStandCells = [];
  initGameBoards();
  window.__msgs = [];
  return true;
})()`);
await sleep(200);

// 先喂"牺牲"事件（reason=last_stand）：绝不能画成叉
await fire('ship_sacrificed', {
  player: 'them', reason: 'last_stand',
  positions: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 2, y: 0 }, { x: 3, y: 0 }],
});
await sleep(300);
const sacCell = await cellState('opponent', 0, 0);
check(!/hit/.test(String(sacCell.cls)) && !/sacrificed/.test(String(sacCell.cls)),
  '★ 绝处逢生的自牺牲【不画红叉】', sacCell);
const sacMsgs = await ev('window.__msgs || []');
check(!sacMsgs.some((m) => m.indexOf('恶魔契约') >= 0),
  '★ 不再把绝处逢生误报成「恶魔契约」（旧实现写死了卡名）', sacMsgs);

// 再喂候选格
await fire('last_stand_cells', { cells: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 2, y: 0 }, { x: 3, y: 0 }] });
await sleep(350);
const cand = await cellState('opponent', 2, 0);
check(/last-stand-candidate/.test(String(cand.cls)),
  '★ 原本有船的格子对对方高亮标出来了', cand);
check(!/hit/.test(String(cand.cls)) && String(cand.text).indexOf('✕') < 0,
  '★ 候选格不是红叉', cand);
const candMsgs = await ev('window.__msgs || []');
check(candMsgs.some((m) => m.indexOf('绝处逢生') >= 0),
  '有明确播报告诉对方这几格能打', candMsgs.slice(-1));

const clickCand = await clickCell('opponent', 2, 0);
check(attackEmit(clickCand).length === 1,
  '★★ 候选格能打（对方点下去真的发攻击请求）', clickCand);

// 打过的候选格：显示真实结果，问号让位
await fire('attack_result', {
  attacker: 'me', x: 3, y: 0, hit: false, ship_sunk: false,
  remaining_attacks: 3, attacker_remaining_ships: 6, defender_remaining_ships: 6,
  shield_blocked: false,
});
await sleep(350);
const struck = await cellState('opponent', 3, 0);
check(/miss/.test(String(struck.cls)) && String(struck.text) === '○',
  '打过的候选格显示真实结果（○），不再挂着候选问号', struck);

// 换大回合：清空候选格
await fire('last_stand_cells', { cells: [] });
await sleep(350);
const cleared = await cellState('opponent', 0, 0);
check(!/last-stand-candidate/.test(String(cleared.cls)),
  '收到空候选格 → 高亮清除（不留过期线索）', cleared);

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
