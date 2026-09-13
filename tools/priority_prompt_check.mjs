#!/usr/bin/env node
/**
 * 优先权询问弹窗的前端回归检查（无头 Edge + CDP）
 *
 * 覆盖：
 *   · priority_request → 弹出面板（金色优先权徽章 + 倒计时圆环 + 卡列表 + 开关）
 *   · 没有速阶3时也要弹（只有取消），文案说明"你手上没有速阶3"
 *   · 点「取消」→ 发出 priority_response {respond:false}
 *   · 勾选「拒绝所有阶段转换时点」→ 随响应一起上报 decline_all
 *   · 倒计时到 0 → 自动取消
 *   · 反证：chain_request 的弹窗不受影响
 *
 * 用法：node tools/priority_prompt_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9391;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.error('找不到 Edge/Chrome，跳过检查'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/priority_prompt_profile', APP], { stdio: 'ignore' });

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

// 用页面真实注册的监听器（socket.io 客户端把它们存在 _callbacks 里，
// 事件名带 '$' 前缀），并换上一个只记录 emit 的假 socket。
//
// ⚠️ 不要试图用"包装 socket.on"的办法抓监听器：页面的监听器早在
// DOMContentLoaded 里就注册完了，后包一层只能抓到之后再注册的那些，
// 结果是假红（no-listener）。直接读 _callbacks 才是可靠的。
async function installProbe() {
  return await ev(`(function(){
    // ⚠️ 幂等：第二次调用时 gameState.socket 已经是上一轮换上的假 socket，
    // 它的 _callbacks 不存在 —— 必须保留第一次抓到的真实回调表。
    if (!window.__realCallbacks) {
      if (!gameState.socket) { ensureSocket(); }
      window.__realCallbacks = (gameState.socket && gameState.socket._callbacks) || {};
    }
    // 关掉可能残留的弹窗，保证每次从干净状态开始
    document.querySelectorAll('.priority-prompt, .magic-prompt').forEach(function(el){ el.remove(); });
    window.__emitted = [];
    gameState.socket = {
      emit: function(name, payload){ window.__emitted.push({name:name, payload:payload}); },
      on: function(){ return this; },
    };
    gameState.roomId = 'r1';
    gameState.playerId = 'me';
    gameState.declinePriority = false;
    // 关掉可能残留的倒计时定时器
    if (window.__priorityTimer) { clearInterval(window.__priorityTimer); }
    return Object.keys(window.__realCallbacks).filter(function(k){
      return k.indexOf('priority') >= 0 || k.indexOf('chain') >= 0;
    });
  })()`);
}

async function fire(eventName, payload) {
  return await ev(`(function(){
    var cbs = (window.__realCallbacks || {})['$${eventName}'];
    if (!cbs || !cbs.length) return 'no-listener';
    cbs.forEach(function(cb){ cb(${JSON.stringify(payload)}); });
    return 'ok';
  })()`);
}

function panelInfo() {
  return ev(`(function(){
    var p = document.querySelector('.priority-prompt');
    if (!p) return null;
    var badge = p.querySelector('.priority-badge');
    var title = p.querySelector('.priority-head h3');
    var hint = p.querySelector('.priority-hint');
    var ring = p.querySelector('#priority-ring');
    var cd = p.querySelector('#priority-countdown');
    var cards = Array.prototype.map.call(p.querySelectorAll('.priority-card'), function(b){
      return b.querySelector('.priority-card-name').textContent;
    });
    var empty = p.querySelector('.priority-empty');
    var toggle = p.querySelector('#decline-priority-toggle');
    var cancel = p.querySelector('#priority-cancel');
    return {
      badge: badge ? badge.textContent : '',
      title: title ? title.textContent : '',
      hint: hint ? hint.textContent : '',
      countdown: cd ? cd.textContent : '',
      ringDeg: ring ? (ring.style.getPropertyValue('--ring-deg') || '') : '',
      cards: cards,
      emptyText: empty ? empty.textContent : '',
      hasToggle: !!toggle,
      toggleChecked: toggle ? toggle.checked : null,
      hasCancel: !!cancel,
      cancelText: cancel ? cancel.textContent : '',
    };
  })()`);
}

// ---- 1. 有速阶3时弹窗 ----
await installProbe();
let r = await fire('priority_request', {
  action: 'enter_battle', actor: 'opp',
  speed3_cards: [{ name: '失灵！', speed: 3 }, { name: '加百列之光', speed: 3 }],
  countdown: 10,
});
check(r === 'ok', '页面注册了 priority_request 监听', r);
await sleep(400);

let info = await panelInfo();
check(!!info, '弹出了优先权面板');
if (info) {
  check(/优先权/.test(info.badge), '有优先权徽章', info.badge);
  check(/进入战斗阶段/.test(info.title), '标题写明对方要做什么', info.title);
  check(info.countdown === '10', '倒计时显示 10', info.countdown);
  check(/\d+deg/.test(info.ringDeg), '圆环有进度（--ring-deg 已设置）', info.ringDeg);
  check(info.cards.length === 2, '列出两张速阶3卡', info.cards);
  check(info.hasToggle, '有「拒绝所有阶段转换时点」开关');
  check(info.toggleChecked === false, '开关默认未勾选', info.toggleChecked);
  check(info.hasCancel && /取消/.test(info.cancelText), '有取消按钮', info.cancelText);
}

// ---- 2. 点「取消」→ 上报 respond:false ----
await ev(`(function(){
  document.querySelector('#priority-cancel').click();
  return true;
})()`);
await sleep(300);
let emitted = await ev('window.__emitted || []');
let resp = emitted.filter((e) => e.name === 'priority_response');
check(resp.length === 1, '点取消后发出了 priority_response', emitted);
check(resp[0] && resp[0].payload.respond === false, 'respond 为 false', resp[0] && resp[0].payload);
check((await panelInfo()) === null, '面板已关闭');

// ---- 3. 没有速阶3时也要弹（只有取消）----
await installProbe();
await fire('priority_request', {
  action: 'enter_end', actor: 'opp', speed3_cards: [], countdown: 10,
});
await sleep(400);
info = await panelInfo();
check(!!info, '没有速阶3时照样弹窗（作者要求要有选择权）');
if (info) {
  check(/进入结束阶段/.test(info.title), '标题对应 enter_end', info.title);
  check(info.cards.length === 0, '没有可点的卡', info.cards);
  check(/没有速阶3/.test(info.emptyText), '明确说明手上没有速阶3', info.emptyText);
  check(info.hasCancel, '仍然有取消按钮');
}

// ---- 4. 勾选开关后取消 → 上报 decline_all ----
await ev(`(function(){
  var t = document.querySelector('#decline-priority-toggle');
  t.checked = true;
  return true;
})()`);
await ev(`(function(){ document.querySelector('#priority-cancel').click(); return true; })()`);
await sleep(300);
emitted = await ev('window.__emitted || []');
resp = emitted.filter((e) => e.name === 'priority_response');
check(resp.length === 1 && resp[0].payload.decline_all === true,
  '勾选开关后随响应上报 decline_all=true', resp[0] && resp[0].payload);
check(await ev('gameState.declinePriority === true'), '本地也记住了开关状态');

// ---- 5. 倒计时归零自动取消 ----
await installProbe();
await fire('priority_request', {
  action: 'enter_battle', actor: 'opp', speed3_cards: [], countdown: 1,
});
await sleep(1800);
emitted = await ev('window.__emitted || []');
const autoResp = emitted.filter((e) => e.name === 'priority_response');
check(autoResp.length >= 1, '倒计时归零后自动响应', emitted.length);
check((await panelInfo()) === null, '自动响应后面板关闭');

// ---- 6. 反证：连锁弹窗不受影响 ----
await installProbe();
await fire('chain_request', {
  card: { name: '轰炸', speed: 3 }, caster: 'opp',
  speed3_cards: [{ name: '失灵！', speed: 3 }], countdown: 10,
});
await sleep(400);
const chainShown = await ev(`document.querySelectorAll('.magic-prompt').length`);
check(chainShown >= 1, '连锁弹窗照常弹出', chainShown);
const priorityShown = await ev(`document.querySelectorAll('.priority-prompt').length`);
check(priorityShown === 0, '两类弹窗不会互相触发', priorityShown);

// ---- 7. 需要目标的速阶3：点卡后走目标选择器，确认后回填给 priority_response ----
// （2026-09-13 补的链路：点卡直接发 respond 会把 targets 丢掉，
//   轰炸/冻结/探测雷达这类卡在服务端会因缺目标直接失败）
await installProbe();
await fire('priority_request', {
  action: 'enter_battle', actor: 'opp',
  speed3_cards: [{ name: '轰炸', speed: 3 }], countdown: 10,
});
await sleep(400);
check(await ev(`document.querySelectorAll('.priority-card').length`) === 1,
  '有一张速阶3可选');
// 点那张卡
await ev(`(function(){
  document.querySelector('.priority-card').click();
  return true;
})()`);
await sleep(500);
const afterClick = await ev(`(function(){
  return {
    panelGone: document.querySelectorAll('.priority-prompt').length === 0,
    targetUI: document.querySelectorAll('.magic-target-prompt, #magic-target-selection').length,
    pending: !!gameState.pendingPriorityCard,
  };
})()`);
check(afterClick.panelGone, '点需要目标的卡后优先权面板收起', afterClick);
check(afterClick.pending, '记下了 pendingPriorityCard', afterClick);
check(afterClick.targetUI >= 1, '打开了目标选择器', afterClick);

// 走完整目标选择链路：轰炸是 target_line（行/列）
const dispatched = await ev(`(function(){
  if (typeof confirmMagicTarget !== 'function') return 'no-fn';
  try {
    confirmMagicTarget({ target_line: { type: 'row', index: 0 } });
  } catch (e) { return 'EXC: ' + e.message; }
  return window.__emitted.filter(function(e){ return e.name === 'priority_response'; });
})()`);
check(Array.isArray(dispatched) && dispatched.length === 1,
  '确认目标后发出 priority_response', dispatched);
if (Array.isArray(dispatched) && dispatched.length) {
  const p = dispatched[0].payload;
  check(p.respond === true, 'respond=true', p);
  check(!!p.card, '带上了要打的卡', p.card);
  check(p.targets && p.targets.target_line && p.targets.target_line.index === 0,
    '★ 目标被回填进 targets（旧实现会丢）', p.targets);
}
check(await ev('gameState.pendingPriorityCard === null'), 'pendingPriorityCard 已清空');

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
