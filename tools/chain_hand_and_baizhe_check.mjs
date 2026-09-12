#!/usr/bin/env node
/**
 * 连锁手牌同步 + 败者食尘「重启对局」 的前端回归检查（无头 Edge + CDP）
 *
 * 覆盖：
 *   · 收到 hand_updated 后手牌 UI 真的刷新（连锁打出的牌从画面上消失）
 *   · 盗亦有道偷牌后，画面显示"少一张、多一张"的正确结果
 *   · reset_gameboard 带 new_max_ships=6 时，界面进入布船阶段且上限是 6
 *   · 反证：reset_gameboard 带别的船数时上限跟着变（别写死 6）
 *
 * 用法：node tools/chain_hand_and_baizhe_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9355;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.error('找不到 Edge/Chrome，跳过检查'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/chain_hand_baizhe_profile', APP], { stdio: 'ignore' });

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

await sleep(2800);
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
// 按 URL 选目标：新 profile 首启时列表第一个 page 是 Edge 自己的
// edge://sync-confirmation-dialog，连错会得到一片 undefined。
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

// 通过页面已注册的 socket 监听器触发事件（走真实链路，不直接调内部函数）
async function fire(eventName, payload) {
  return await ev(`(function(){
    var s = gameState.socket;
    if (!s || !s._callbacks || !s._callbacks['$${eventName}']) return 'no-listener';
    s._callbacks['$${eventName}'].forEach(function(cb){ cb(${JSON.stringify(payload)}); });
    return 'ok';
  })()`);
}

const HAND_TEXT = `(function(){
  var el = document.getElementById('magic-hand');
  return el ? el.textContent.replace(/\\s+/g, '') : '(no #magic-hand)';
})()`;

// ---- 1. hand_updated 会真的刷新手牌 UI ----
let r = await fire('hand_updated', { hand: [
  { name: '轰炸', speed: 3, type: '普通' },
  { name: '冻结', speed: 3, type: '普通' },
] });
check(r === 'ok', '页面注册了 hand_updated 监听', r);
await sleep(300);
let rendered = await ev(HAND_TEXT);
check(/轰炸/.test(rendered), '手牌 UI 显示了服务端下发的牌', rendered);

// ---- 2. 牌被消耗后，UI 里必须消失（这就是玩家报的"还在手上"）----
await fire('hand_updated', { hand: [{ name: '冻结', speed: 3, type: '普通' }] });
await sleep(300);
rendered = await ev(HAND_TEXT);
check(!/轰炸/.test(rendered), '牌被消耗后不再显示在手牌区', rendered);
check(/冻结/.test(rendered), '剩下的牌仍在手牌区', rendered);

// ---- 3. 盗亦有道场景：打出去 + 偷一张回来 ----
await fire('hand_updated', { hand: [
  { name: '盗亦有道', speed: 3, type: '普通' },
  { name: '冻结', speed: 3, type: '普通' },
] });
await sleep(250);
await fire('hand_updated', { hand: [
  { name: '冻结', speed: 3, type: '普通' },
  { name: '八方来财', speed: 3, type: '普通' },
] });
await sleep(300);
rendered = await ev(HAND_TEXT);
check(!/盗亦有道/.test(rendered), '打出的盗亦有道从手牌区消失', rendered);
check(/八方来财/.test(rendered), '偷到的牌出现在手牌区', rendered);

// ---- 4. reset_gameboard（败者食尘）进入布船阶段，上限 6 ----
r = await fire('reset_gameboard', {
  new_max_ships: 6,
  message: '败者食尘生效，双方棋盘已重置为6艘，请重新摆放（手牌保留）',
});
check(r === 'ok', '页面注册了 reset_gameboard 监听', r);
await sleep(400);
let placement = await ev(`(function(){
  var s = document.getElementById('ship-placement-screen');
  return { active: !!(s && s.classList.contains('active')), maxShips: window.gameState.maxShips, placed: window.gameState.placedShips, ships: (window.gameState.ships||[]).length };
})()`);
check(placement.active, '界面切到布船阶段', placement);
check(placement.maxShips === 6, '布船上限是服务端下发的 6', placement);
check(placement.placed === 0 && placement.ships === 0, '棋盘已清空', placement);

// ---- 5. 反证：别的船数要跟着变（别把 6 写死）----
await fire('reset_gameboard', { new_max_ships: 3, message: '灵气复苏生效' });
await sleep(400);
placement = await ev(`(function(){ return { maxShips: window.gameState.maxShips }; })()`);
check(placement.maxShips === 3, '上限跟随服务端下发的值变化（未写死 6）', placement);

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
