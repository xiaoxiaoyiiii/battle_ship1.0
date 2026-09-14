#!/usr/bin/env node
/**
 * 定位「轰炸 报『准备阶段不允许使用』」的真实触发条件。
 *
 * 做法：在真实页面里直接调 canPlayCard / playMagicCard，
 * 穷举 (阶段 × 是否自己回合 × speed 数据类型) 的组合，
 * 记录每一组合下弹出的 Alert 文案。
 *
 * 用法：node tools/diag_bomb_alert.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9405;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/diag_bomb', APP], { stdio: 'ignore' });
await sleep(3000);

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

// 接管 showAlert，把文案记下来而不是真弹窗
await ev(`(function(){
  window.__alerts = [];
  window.showAlert = function(msg){ window.__alerts.push(String(msg)); };
  return true;
})()`);

// 找出页面里 轰炸 这张卡的真实数据（前端数据文件）
const bombSpeed = await ev(`(function(){
  if (typeof magicCards === 'undefined') return 'no-magicCards';
  var arr = Array.isArray(magicCards) ? magicCards : (magicCards.magic_cards || []);
  var c = arr.find(function(x){ return x.name === '轰炸'; });
  return c ? { speed: c.speed, type: typeof c.speed } : 'not-found';
})()`);
console.log('前端数据里的 轰炸: ' + JSON.stringify(bombSpeed));

const phases = ['preparation', 'battle', 'end'];
const results = [];

for (const phase of phases) {
  for (const mine of [true, false]) {
    for (const speed of [bombSpeed && bombSpeed.speed, String(bombSpeed && bombSpeed.speed)]) {
      const r = await ev(`(function(){
        window.__alerts = [];
        gameState.roomId = 'r1';
        gameState.playerId = 'me';
        gameState.currentPhase = ${JSON.stringify(phase)};
        gameState.currentAttacker = ${mine ? "'me'" : "'opp'"};
        gameState.hand = [ { name: '轰炸', speed: ${JSON.stringify(speed)}, type: '普通', description: '' } ];
        gameState.selectedCardIndex = 0;
        gameState.selectedCardKey = '轰炸\\u0000' + ${JSON.stringify(speed)};
        gameState.socket = { emit: function(){}, on: function(){ return this; } };
        var can = null;
        try { can = canPlayCard(gameState.hand[0]); } catch (e) { can = 'EXC:' + e.message; }
        var alertMsg = null;
        try { playMagicCard(0); alertMsg = window.__alerts[0] || null; } catch (e) { alertMsg = 'EXC:' + e.message; }
        return { can: can, alert: alertMsg };
      })()`);
      results.push({ phase, mine, speedType: typeof speed, speed, can: r.can, alert: r.alert });
    }
  }
}

console.log('');
console.log('阶段        我的回合  speed类型  canPlayCard  Alert');
console.log('─'.repeat(96));
for (const r of results) {
  const phaseMsg = r.alert && /不允许使用速阶/.test(r.alert);
  console.log(
    r.phase.padEnd(12) +
    String(r.mine).padEnd(10) +
    r.speedType.padEnd(10) +
    String(r.can).padEnd(13) +
    (r.alert || '(无弹窗)') +
    (phaseMsg ? '   <<< 就是这条烦人的文案' : ''));
}

try { ws.close(); } catch (e) {}
browser.kill();
