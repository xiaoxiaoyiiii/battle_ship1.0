#!/usr/bin/env node
/**
 * 饮血「通过」流程的前端回归检查（无头 Edge + CDP）
 *
 * 覆盖：
 *   · 打空一发后点饮血 → 必须被前端拦下（牌不消耗），提示点名真实原因
 *   · 击沉后用饮血 → 放行
 *   · 只命中未击沉 → 拦下，且提示区分于"没打中"
 *   · 溅射 / 雷达子弹 同样的拦截
 *   · 反证：无关的卡不受影响
 *
 * 用法：node tools/yinxue_flow_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9345;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.error('找不到 Edge/Chrome，跳过饮血前端检查'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/yinxue_check_profile', APP], { stdio: 'ignore' });

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

await sleep(2800);
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
// ⚠️ 必须按 URL 选目标：列表里第一个 type==='page' 可能是 Edge 自己的
// edge://sync-confirmation-dialog（新 profile 首次启动就会出现），
// 连错页面会得到一堆 undefined，看起来像"函数没定义"。
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
  if (await ev('document.readyState === "complete" && typeof afterHitBlockReason === "function"')) break;
  await sleep(200);
}

async function drainToasts() {
  return await ev(`(function(){
    var box = document.getElementById('game-message-container');
    if (!box) return [];
    var t = Array.prototype.map.call(box.querySelectorAll('.game-message'), function(el){ return (el.textContent||'').trim(); }).filter(Boolean);
    box.innerHTML = '';
    return t;
  })()`);
}

// 让出牌流程停在前端拦截阶段：用一个不存在的 socket，若真的发出去会抛错暴露问题
async function tryPlay(cardName, lastAttack, phase) {
  await ev(`(function(){
    window.__sent = [];
    gameState.socket = { emit: function(n, p, cb){ window.__sent.push({name:n, payload:p}); if (typeof cb === 'function') cb({status:'error', message:'（测试桩）'}); } };
    gameState.playerId = 'me';
    gameState.roomId = 'r1';
    gameState.currentAttacker = 'me';
    gameState.currentPhase = ${JSON.stringify(phase)};
    gameState.activeEffects = [];
    gameState.fieldMagic = null;
    gameState.attackOrder = ['me', 'opp'];
    gameState.lastAttack = ${JSON.stringify(lastAttack)};
    gameState.hand = [{ name: ${JSON.stringify(cardName)}, speed: 2, type: '普通' }];
    playMagicCard(0);
    return true;
  })()`);
  await sleep(250);
  const toasts = await drainToasts();
  const sent = await ev('window.__sent || []');
  return { text: toasts.join(' | '), sent };
}

// ---- 1. 打空后用饮血：拦截 + 正确提示 ----
let r = await tryPlay('饮血', { x: 3, y: 3, attacker: 'me', hit: false, shipSunk: false }, 'battle');
check(/饮血/.test(r.text), '打空后用饮血会给出提示', r.text);
check(/击沉/.test(r.text), '提示说明需要「击沉」', r.text);
check(!r.sent.some((s) => s.name === 'use_magic_card'), '被拦时不得把牌发出去（否则牌会被吞）', r.sent);

// ---- 2. 没攻击过就用饮血 ----
r = await tryPlay('饮血', null, 'battle');
check(/饮血/.test(r.text), '没攻击过时也给出提示', r.text);
check(!r.sent.some((s) => s.name === 'use_magic_card'), '没攻击过时不得发牌', r.sent);

// ---- 3. 只命中未击沉 ----
r = await tryPlay('饮血', { x: 1, y: 1, attacker: 'me', hit: true, shipSunk: false }, 'battle');
check(/击沉/.test(r.text), '只命中未击沉时提示需要击沉', r.text);
check(!r.sent.some((s) => s.name === 'use_magic_card'), '只命中未击沉时不得发牌', r.sent);

// ---- 4. 击沉后放行 ----
r = await tryPlay('饮血', { x: 0, y: 0, attacker: 'me', hit: true, shipSunk: true }, 'battle');
check(!/无法使用/.test(r.text), '击沉后不应被拦截', r.text);
check(r.sent.some((s) => s.name === 'use_magic_card'), '击沉后应真的把牌发出去', r.sent);

// ---- 5. 溅射 / 雷达子弹 同样拦截 ----
for (const name of ['溅射', '雷达子弹']) {
  r = await tryPlay(name, { x: 3, y: 3, attacker: 'me', hit: false, shipSunk: false }, 'battle');
  check(new RegExp(name).test(r.text), `${name}：打空后被拦并提示`, r.text);
  check(!r.sent.some((s) => s.name === 'use_magic_card'), `${name}：被拦时不得发牌`, r.sent);
}

// ---- 6. 反证：无关的卡不受影响 ----
r = await tryPlay('增援', { x: 3, y: 3, attacker: 'me', hit: false, shipSunk: false }, 'battle');
check(!/击沉/.test(r.text), '无关的卡不该出现饮血相关文案', r.text);
check(r.sent.some((s) => s.name === 'use_magic_card'), '无关的卡应正常发出', r.sent);

// ---- 7. 卡面文案已同步 ----
const desc = await ev(`(function(){
  var c = (window.magicCards||[]).filter(function(x){ return x.name === '饮血'; })[0];
  return c ? c.description : null;
})()`);
check(desc && /击沉/.test(desc), '前端卡面已改为「击沉」口径', desc);

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
