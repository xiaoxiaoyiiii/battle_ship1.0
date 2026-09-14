#!/usr/bin/env node
/**
 * 验证前端 sendMagicCard 的旧下标注销问题。
 *
 * 场景：手牌很少（1~2 张）时出牌；
 *   出牌请求发出后、服务器响应回来之前，收到一条 hand_updated
 *   （比如对方打无中生有，或自己因效果摸牌）。
 *   这时 gameState.hand 已经变了，而回调里还在用【旧下标】splice，
 *   于是删掉的是新数组里那个位置上的牌 —— 不是自己打出去的那张。
 *
 * 本脚本只驱动前端（喂真实形状的事件），不连服务端。
 *
 * 用法：node tools/repro_splice_index.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9403;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/splice_repro', APP], { stdio: 'ignore' });
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
  if (r.exceptionDetails) return 'EXC: ' + JSON.stringify(r.exceptionDetails).slice(0, 300);
  return r.result && r.result.value;
};
const t0 = Date.now();
while (Date.now() - t0 < 15000) {
  if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break;
  await sleep(200);
}

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// 用真实事件形状喂前端：直接调用页面自己的 hand_updated 回调 + sendMagicCard
const result = await ev(`(function(){
  // 1) 装成"对局中"，手牌只有 2 张（作者当时就是手牌很少）
  gameState.roomId = 'r1';
  gameState.playerId = 'me';
  var fired = [];
  gameState.socket = {
    emit: function(name, payload, cb){
      fired.push({ name: name, payload: payload });
      // 关键：把服务器回调【挂起来】，不立刻执行 ——
      // 模拟"请求在路上"的窗口期，这期间会收到 hand_updated。
      window.__pendingCb = cb;
    },
    on: function(){ return this; },
  };
  gameState.hand = [ { name: '饮血', speed: 2, type: '普通' },
                     { name: '冻结', speed: 2, type: '普通' } ];

  // 2) 调页面真实的出牌函数（0 号位 = 饮血）
  var before = gameState.hand.map(function(c){ return c.name; });
  sendMagicCard(0, []);

  // 3) 在回调返回【之前】，模拟一条 hand_updated：
  //    自己因为效果摸了一张新牌，插到了最前面
  //    （服务器把新牌 append 到手牌尾，但前端可能整份替换；
  //      这里模拟最坏情况：新牌出现在 0 号位）
  if (typeof updateHandUI === 'function') {
    gameState.hand = [ { name: '八方来财', speed: 3, type: '普通' },
                       { name: '饮血', speed: 2, type: '普通' },
                       { name: '冻结', speed: 2, type: '普通' } ];
    updateHandUI();
  }
  var mid = gameState.hand.map(function(c){ return c.name; });

  // 4) 现在服务器的成功响应回来了 —— 页面会执行 splice(0, 1)
  if (window.__pendingCb) window.__pendingCb({ status: 'success' });
  var after = gameState.hand.map(function(c){ return c.name; });

  return { before: before, mid: mid, after: after,
           cardSent: fired.length ? (fired[0].payload.card || {}).name : null };
})()`);

console.log('=== 前端 sendMagicCard 的旧下标注销 ===');
console.log('  出牌前手牌      :', JSON.stringify(result.before));
console.log('  实际打出去的卡  :', JSON.stringify(result.cardSent));
console.log('  回调前收到手牌更新:', JSON.stringify(result.mid));
console.log('  回调执行后手牌  :', JSON.stringify(result.after));
console.log();

check(result.cardSent === '饮血', '打出去的是饮血（0 号位）', result.cardSent);
const kept = result.after;
check(kept.indexOf('饮血') < 0, '饮血已从手牌移除');
check(kept.indexOf('八方来财') >= 0,
  '★ 新摸到的牌（八方来财）必须保留', kept);
check(kept.indexOf('冻结') >= 0, '冻结必须保留', kept);
check(kept.length === 2, '最终应剩 2 张（八方来财 + 冻结）', kept.length);

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
