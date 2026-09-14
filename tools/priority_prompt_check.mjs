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
 *   · 局内的「阶段时点」开关（阶段卡片右上角，绝对定位不破布局）
 *   · 发起方的等待冻结：priority_waiting → 横幅 + 按钮禁用；priority_waiting_end → 解冻
 *   · 发起方的等待冻结：priority_waiting → 横幅 + 按钮禁用；priority_waiting_end → 解冻
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
    // 标记"r1 这个房间已经同步过了"：updatePhaseUI() 里有 ensureDeclinePrioritySynced()
    // 会自动补推一次 set_decline_priority，不挡住的话前面几个场景的 emit 计数会被它带偏。
    gameState.declinePrioritySyncedRoom = 'r1';
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

// ---- 8. 设置面板里的常驻开关（修「勾上后就再也取消不了」的死结）----
// 原先开关只存在于优先权弹窗内，而勾上就不再弹窗 → 玩家永远没机会取消勾选。
// 作者 2026-09-14 明确要求：「做成一个开关放在局内，而不是在设置中」，
// 所以现在只有两个入口：阶段卡片右上角的 #phase-timing-toggle（常驻）+ 弹窗里那个。
console.log('');
console.log('--- 场景 8：局内的常驻开关 ---');
await installProbe();
await ev(`(function(){
  localStorage.removeItem('battleship_decline_priority');
  gameState.declinePriority = false;
  syncDeclinePriorityUI();
  // 开关在 #game-screen 里，屏幕没 active 时量出来是 0×0（尺寸断言会假红）
  var s = document.getElementById('game-screen');
  if (s) s.classList.add('active');
  return true;
})()`);
await sleep(300);

const boxInit = await ev(`(function(){
  var btn = document.getElementById('phase-timing-toggle');
  if (!btn) return null;
  var phaseCard = document.getElementById('turn-indicator');
  var cs = getComputedStyle(btn);
  var r = btn.getBoundingClientRect();
  return {
    inPhaseCard: !!(phaseCard && phaseCard.contains(btn)),
    // 必须是绝对定位：否则它会把居中的阶段按钮挤偏（宽屏有条不变量守这个）
    position: cs.position,
    text: btn.textContent.replace(/\\s+/g, ' ').trim(),
    state: (document.getElementById('phase-timing-state') || {}).textContent || '',
    size: Math.round(r.width) + 'x' + Math.round(r.height),
    pressed: btn.getAttribute('aria-pressed'),
    inSettings: !!document.getElementById('decline-priority-setting'),
    inPromptToggleExists: true
  };
})()`);
check(!!boxInit, '★ 对局信息区里有常驻的「阶段时点」开关');
check(!!boxInit && boxInit.inPhaseCard, '开关就在阶段卡片（#turn-indicator）里', boxInit);
check(!!boxInit && boxInit.inSettings === false,
  '★ 设置面板里那份已删除（按作者要求只留局内）', boxInit && boxInit.inSettings);
check(!!boxInit && (boxInit.position === 'absolute' || boxInit.position === 'fixed'),
  '★ 开关脱离流式布局（absolute / fixed），不会把阶段按钮挤得不居中', boxInit && boxInit.position);
check(!!boxInit && /阶段时点/.test(boxInit.text), '开关文案说明了作用', boxInit && boxInit.text);
check(!!boxInit && boxInit.state === '询问中', '默认状态显示「询问中」', boxInit && boxInit.state);
check(!!boxInit && boxInit.size.split('x').map(Number).every((v) => v >= 40),
  '★ 开关满足移动端触控目标 ≥40px', boxInit && boxInit.size);
check(!!boxInit && boxInit.pressed === 'false', '默认 aria-pressed=false', boxInit && boxInit.pressed);

// 点一下 → 发出 set_decline_priority(true)，写进 localStorage，按钮自己变成「已关闭」
await ev(`(function(){ document.getElementById('phase-timing-toggle').click(); return true; })()`);
await sleep(300);
let sent = await ev('window.__emitted || []');
let setDeclines = sent.filter((e) => e.name === 'set_decline_priority');
check(setDeclines.length === 1 && setDeclines[0].payload.decline === true,
  '★ 点一下开关就发出 set_decline_priority(decline=true)', setDeclines);
check(await ev('gameState.declinePriority === true') === true, '本地状态同步为 true');
check(await ev(`localStorage.getItem('battleship_decline_priority')`) === '1',
  '偏好写进了 localStorage（服务端那份是房间级的，换局会被重置）');
const offState = await ev(`(function(){
  var btn = document.getElementById('phase-timing-toggle');
  return { state: document.getElementById('phase-timing-state').textContent,
           isOff: btn.classList.contains('is-off'),
           pressed: btn.getAttribute('aria-pressed') };
})()`);
check(offState.state === '已关闭' && offState.isOff && offState.pressed === 'true',
  '按钮自己显示成「已关闭」（不是静默无反应）', offState);

// ★ 关键：不需要任何弹窗，再点一下就能恢复（这正是原来的死结）
await ev(`(function(){ document.getElementById('phase-timing-toggle').click(); return true; })()`);
await sleep(300);
sent = await ev('window.__emitted || []');
setDeclines = sent.filter((e) => e.name === 'set_decline_priority');
check(setDeclines.length === 2 && setDeclines[1].payload.decline === false,
  '★★ 不需要弹窗就能恢复询问（修掉了「勾上就再也改不回来」的死结）', setDeclines);
check(await ev('gameState.declinePriority === false') === true, '本地状态同步回 false');
check(await ev(`localStorage.getItem('battleship_decline_priority')`) === '0', 'localStorage 也跟着回到 0');

// 弹窗里勾过之后，局内开关也要跟着变（两个入口一份状态）
await ev(`(function(){ setDeclinePriority(true, { notify: false, silent: true }); return true; })()`);
await sleep(200);
check(await ev(`document.getElementById('phase-timing-state').textContent`) === '已关闭',
  '弹窗里勾过之后，局内开关同步为「已关闭」');

// 本地偏好要能跨"重新打开页面"存活：把内存状态清掉再走一遍初始化
const reloaded = await ev(`(function(){
  gameState.declinePriority = false;
  gameState.declinePrioritySyncedRoom = null;
  document.getElementById('phase-timing-state').textContent = '询问中';
  bindDeclinePriorityToggle();
  return { state: gameState.declinePriority,
           state2: document.getElementById('phase-timing-state').textContent };
})()`);
check(reloaded && reloaded.state === true && reloaded.state2 === '已关闭',
  '★ 重新载入时从 localStorage 恢复偏好，并回填到局内开关', reloaded);

// 进了新房间要把偏好推给服务端 —— 不推的话新房间又开始问
await ev(`(function(){
  window.__emitted = [];
  gameState.roomId = 'r2';
  gameState.playerId = 'me';
  ensureDeclinePrioritySynced();
  ensureDeclinePrioritySynced();
  return true;
})()`);
await sleep(200);
const roomSync = (await ev('window.__emitted || []')).filter((e) => e.name === 'set_decline_priority');
check(roomSync.length === 1 && roomSync[0].payload.decline === true,
  '★ 进新房间时把偏好同步给服务端，同一房间只推一次', roomSync);

// ────────────────────────────────────────────────────────────
// 场景 9：发起方的"等待对方响应"状态（冻结）
// 作者反馈：「在等待阶段转换的响应的时候，对方不能暂停行动」——
// 以前发起方在 10 秒窗口里还能继续开炮/出牌，等于把仲裁窗口架空了。
// 现在服务端会冻结他，前端要同步显示"等待中"+ 禁用阶段按钮。
// ────────────────────────────────────────────────────────────
console.log('');
console.log('--- 场景 9：等待对方响应时的冻结 ---');
await installProbe();
await ev(`(function(){
  gameState.roomId = 'r1';
  gameState.playerId = 'me';
  gameState.currentAttacker = 'me';
  gameState.currentPhase = 'preparation';
  updatePhaseUI();
  return true;
})()`);
await sleep(200);
const beforeWait = await ev(`(function(){
  var b = document.getElementById('enter-battle-phase');
  return { display: getComputedStyle(b).display, disabled: b.disabled,
           banner: !!document.getElementById('priority-waiting-banner') };
})()`);
check(beforeWait.disabled === false, '前置条件：正常情况下阶段按钮是可点的', beforeWait);

// 服务端下发 priority_waiting（与真实事件同名同载荷）
await fire('priority_waiting', { action: 'enter_battle', action_text: '进入战斗阶段', countdown: 10 });
await sleep(400);
const waitState = await ev(`(function(){
  var b = document.getElementById('enter-battle-phase');
  var banner = document.getElementById('priority-waiting-banner');
  return {
    disabled: b.disabled,
    bannerShown: !!banner && getComputedStyle(banner).display !== 'none',
    bannerText: banner ? banner.textContent : '',
    waiting: !!gameState.priorityWaiting
  };
})()`);
check(waitState.waiting === true, '★ 收到 priority_waiting 后本地进入等待状态', waitState);
check(waitState.disabled === true, '★ 等待期间阶段按钮被禁用（点了也没用，服务端也会拒）', waitState);
check(waitState.bannerShown && /等待对方响应/.test(waitState.bannerText),
  '★ 界面上明确显示「等待对方响应」横幅（不是静默卡住）', waitState);

// 再点一下被禁用的按钮不应该发出任何请求
await ev(`(function(){ window.__emitted = []; document.getElementById('enter-battle-phase').click(); return true; })()`);
await sleep(250);
const blockedClicks = (await ev('window.__emitted || []')).filter((e) => e.name === 'enter_battle_phase');
check(blockedClicks.length === 0, '★ 禁用状态下点不动（不会重复发阶段转换）', blockedClicks);

// 等待结束 → 解冻
await fire('priority_waiting_end', { action: 'enter_battle' });
await sleep(400);
const afterEnd = await ev(`(function(){
  var b = document.getElementById('enter-battle-phase');
  var banner = document.getElementById('priority-waiting-banner');
  return { disabled: b.disabled, waiting: !!gameState.priorityWaiting,
           bannerShown: !!banner && getComputedStyle(banner).display !== 'none' };
})()`);
check(afterEnd.waiting === false && afterEnd.disabled === false,
  '★ 收到 priority_waiting_end 后解冻（按钮恢复可点）', afterEnd);
check(afterEnd.bannerShown === false, '横幅撤掉', afterEnd);

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
