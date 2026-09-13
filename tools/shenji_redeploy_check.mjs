#!/usr/bin/env node
/**
 * 神机妙算「重新部署」面板的前端回归检查（无头 Edge + CDP）
 *
 * 覆盖：
 *   · 收到 kind=shenji_redeploy 的 placement_request → 弹出面板且标题/提示正确
 *   · 原位置（已被对方打过）在 allowed 里 → 必须可点，不能画成灰色
 *   · 点选后能确认提交
 *   · 反证：其他 kind（增援/复活/绝处逢生）的文案与行为不受影响
 *
 * 用法：node tools/shenji_redeploy_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9381;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.error('找不到 Edge/Chrome，跳过检查'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/shenji_redeploy_profile', APP], { stdio: 'ignore' });

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

async function panelInfo() {
  return await ev(`(function(){
    var p = document.getElementById('placement-prompt');
    if (!p) return null;
    var titleEl = p.querySelector('h3');
    var hintEl = p.querySelector('.placement-hint');
    var cells = {};
    Array.prototype.forEach.call(p.querySelectorAll('.placement-cell'), function(c){
      cells[c.dataset.x + ',' + c.dataset.y] = c.className;
    });
    return {
      title: titleEl ? titleEl.textContent : '',
      hint: hintEl ? hintEl.textContent : '',
      cells: cells
    };
  })()`);
}

// ---- 1. 神机妙算：面板要弹出来，且原位置可点 ----
let r = await fire('placement_request', {
  kind: 'shenji_redeploy',
  remaining: 1, total: 1, placed: 0,
  allowed: [{ x: 0, y: 0 }],
  blocked: [{ x: 5, y: 5 }],
  message: '预言成功：请选择这艘战舰重新部署的位置（原位置或对方未打过的格子）',
});
check(r === 'ok', '页面注册了 placement_request 监听', r);
await sleep(400);

let info = await panelInfo();
check(!!info, '预言成功后弹出了放置面板');
if (info) {
  check(/神机妙算/.test(info.title), '标题点明是神机妙算', info.title);
  check(/原位置/.test(info.hint), '提示说明了可以放回原位置', info.hint);
  const cls00 = info.cells['0,0'] || '';
  check(!/blocked|disabled/.test(cls00), '原位置 (0,0) 未被画成不可点', cls00);
  const cls55 = info.cells['5,5'] || '';
  check(/blocked|disabled/.test(cls55), '被 blocked 的 (5,5) 不可点', cls55);
}

// ---- 2. 点选原位置并确认 ----
await ev(`(function(){
  var p = document.getElementById('placement-prompt');
  var cell = p.querySelector('.placement-cell[data-x="0"][data-y="0"]');
  cell.click();
  return true;
})()`);
await sleep(200);
const selected = await ev(`(function(){
  var p = document.getElementById('placement-prompt');
  return p.querySelector('.placement-cell[data-x="0"][data-y="0"]').className;
})()`);
check(/selected/.test(selected), '原位置可以被选中', selected);

const canConfirm = await ev(`(function(){
  var b = document.getElementById('placement-confirm');
  return b ? !b.disabled : null;
})()`);
check(canConfirm === true, '选中后确认按钮可用', canConfirm);

await ev(`(function(){ document.getElementById('placement-prompt').remove(); return true; })()`);

// ---- 3. 反证：增援的文案不带"原位置" ----
await fire('placement_request', {
  kind: 'reinforce', remaining: 1, total: 1, placed: 0, blocked: [],
});
await sleep(400);
info = await panelInfo();
check(!!info && /增援/.test(info.title), '增援面板照常弹出', info && info.title);
check(!!info && !/原位置/.test(info.hint), '增援提示不该混入"原位置"文案', info && info.hint);
await ev(`(function(){ var p=document.getElementById('placement-prompt'); if(p) p.remove(); return true; })()`);

// ---- 4. 反证：死苏生/复活的文案不受影响 ----
await fire('placement_request', {
  kind: 'revive', remaining: 2, total: 2, placed: 1, blocked: [],
});
await sleep(400);
info = await panelInfo();
check(!!info && /复活/.test(info.title), '复活面板照常弹出', info && info.title);
check(!!info && /2\/2/.test(info.hint), '多艘时显示进度', info && info.hint);
check(!!info && !/原位置/.test(info.hint), '复活提示不该混入"原位置"文案', info && info.hint);
await ev(`(function(){ var p=document.getElementById('placement-prompt'); if(p) p.remove(); return true; })()`);

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
