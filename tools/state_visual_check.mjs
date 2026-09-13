#!/usr/bin/env node
/**
 * 状态可视化回归检查（无头 Edge + CDP）
 *
 * 覆盖本轮"前后端同步"审计产出的缺口：
 *   · 护盾（仁王之盾）—— 加盾后棋盘要画出来；原来零 emit，前端完全不知道
 *   · 无敌（钢筋铁骨）—— 无敌船要有标记；原来前端连 invincible 字段都收不到
 *   · 盾挡下一击 —— 要有专门提示，不能被画成普通"命中"
 *   · 沉船（alive=false）—— 要被灰掉
 *   · 反证：没有这些状态时不画错
 *
 * 用法：node tools/state_visual_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9371;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.error('找不到 Edge/Chrome，跳过检查'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/state_visual_profile', APP], { stdio: 'ignore' });

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

await sleep(2800);
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.url.startsWith('http')) ||
             list.find((t) => t.type === 'page');
if (!page) { console.error('找不到页面目标'); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });

let seq = 0; const pending = new Map();
ws.onmessage = (m) => {
  const x = JSON.parse(m.data);
  if (x.id && pending.has(x.id)) {
    const { res, rej } = pending.get(x.id); pending.delete(x.id);
    x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result);
  }
};
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq; pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method, params }));
  setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
});
await send('Runtime.enable');
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 200));
  return r.result && r.result.value;
};

const t0 = Date.now();
while (Date.now() - t0 < 20000) {
  if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break;
  await sleep(200);
}

async function fire(eventName, payload) {
  return await ev(`(function(){
    var s = gameState.socket;
    if (!s || !s._callbacks || !s._callbacks['$${eventName}']) return 'no-listener';
    s._callbacks['$${eventName}'].forEach(function(cb){ cb(${JSON.stringify(payload)}); });
    return 'ok';
  })()`);
}

// 送一份己方棋盘并读回渲染结果
async function renderShips(ships) {
  const r = await fire('player_ships_updated', { ships });
  if (r !== 'ok') return { error: r };
  await sleep(300);
  return await ev(`(function(){
    var board = document.getElementById('game-player-board');
    if (!board) return { error: 'no board' };
    var out = {};
    Array.prototype.forEach.call(board.querySelectorAll('.cell'), function(c){
      var k = c.dataset.x + ',' + c.dataset.y;
      out[k] = { cls: c.className, title: c.title || '' };
    });
    return out;
  })()`);
}

function cellOf(board, x, y) { return board[x + ',' + y] || {}; }

// ---- 1. 护盾：必须画出来 ----
let board = await renderShips([
  { positions: [{ x: 0, y: 0 }], hits: [], alive: true, shield: true },
]);
if (board.error) { check(false, '护盾：页面可用', board.error); }
else {
  let c = cellOf(board, 0, 0);
  check(/shielded/.test(c.cls), '护盾船有 shielded 类', c.cls);
  check(/护盾/.test(c.title), '护盾船有说明文案', c.title);
}

// ---- 2. 无敌：必须画出来 ----
board = await renderShips([
  { positions: [{ x: 1, y: 0 }], hits: [], alive: true, invincible: true },
]);
if (!board.error) {
  const c = cellOf(board, 1, 0);
  check(/invincible/.test(c.cls), '无敌船有 invincible 类', c.cls);
  check(/无敌/.test(c.title), '无敌船有说明文案', c.title);
}

// ---- 3. 沉船：要被灰掉 ----
board = await renderShips([
  { positions: [{ x: 2, y: 0 }], hits: [], alive: false },
]);
if (!board.error) {
  const c = cellOf(board, 2, 0);
  check(/sunk/.test(c.cls), '沉船有 sunk 类', c.cls);
}

// ---- 4. 反证：普通船不该带这些类 ----
board = await renderShips([
  { positions: [{ x: 3, y: 0 }], hits: [], alive: true },
]);
if (!board.error) {
  const c = cellOf(board, 3, 0);
  check(/ship/.test(c.cls), '普通船仍画成船', c.cls);
  check(!/shielded|invincible|sunk|frozen/.test(c.cls), '普通船不带状态类', c.cls);
}

// ---- 5. 状态可以动态消失（盾被消耗后不能再画着） ----
board = await renderShips([
  { positions: [{ x: 4, y: 0 }], hits: [], alive: true, shield: true },
]);
if (!board.error) {
  check(/shielded/.test(cellOf(board, 4, 0).cls), '先确认护盾画上了');
}
board = await renderShips([
  { positions: [{ x: 4, y: 0 }], hits: [], alive: true, shield: false },
]);
if (!board.error) {
  check(!/shielded/.test(cellOf(board, 4, 0).cls), '盾被消耗后标记消失', cellOf(board, 4, 0).cls);
}

// ---- 6. 冻结标记不能被新状态挤掉 ----
board = await renderShips([
  { positions: [{ x: 5, y: 0 }], hits: [], alive: true, frozen: true, shield: true },
]);
if (!board.error) {
  const c = cellOf(board, 5, 0);
  check(/frozen/.test(c.cls), '冻结标记仍在', c.cls);
  check(/shielded/.test(c.cls), '护盾标记同时存在', c.cls);
}

// ---- 7. 盾挡下一击要有专门提示 ----
await ev(`(function(){
  var box = document.getElementById('game-message-container');
  if (box) box.innerHTML = '';
  return true;
})()`);
await ev(`(function(){ gameState.playerId = 'me'; return true; })()`);
let r = await fire('shield_absorbed', { player: 'me', positions: [{ x: 0, y: 0 }] });
check(r === 'ok', '页面注册了 shield_absorbed 监听', r);
await sleep(300);
let toasts = await ev(`(function(){
  var box = document.getElementById('game-message-container');
  if (!box) return '(no box)';
  return Array.prototype.map.call(box.querySelectorAll('.game-message'), function(el){ return el.textContent; }).join(' | ');
})()`);
check(/护盾/.test(toasts) && /挡下/.test(toasts), '盾挡下有明确提示（不是普通"命中"）', toasts);

// 对手视角的措辞
await ev(`(function(){ var b=document.getElementById('game-message-container'); if(b) b.innerHTML=''; return true; })()`);
await fire('shield_absorbed', { player: 'opp', positions: [] });
await sleep(300);
toasts = await ev(`(function(){
  var box = document.getElementById('game-message-container');
  if (!box) return '';
  return Array.prototype.map.call(box.querySelectorAll('.game-message'), function(el){ return el.textContent; }).join(' | ');
})()`);
check(/对方/.test(toasts), '对手的盾被挡时措辞区分', toasts);

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
