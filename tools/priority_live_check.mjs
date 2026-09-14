#!/usr/bin/env node
/**
 * 优先权询问（方案 D）真实浏览器端到端检查。
 *
 * 与 priority_prompt_check.mjs 的区别：那个是"喂假事件"验前端渲染，
 * 这个是【两个真实浏览器页面 + 真服务端】打一局，验证：
 *   · 真人 A 点「进入战斗阶段」→ B 的浏览器真的弹出优先权面板
 *   · 此时 A 的阶段【没有】推进（这是本次修的核心）
 *   · B 点取消 → A 的界面推进到战斗阶段
 *   · B 全程能看到倒计时数字在走
 *
 * 用法：node tools/priority_live_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9395;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/priority_live_profile', APP], { stdio: 'ignore' });

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

await sleep(3000);

/** 开一个 CDP 会话（一个标签页 = 一个玩家）。 */
async function openTab(url) {
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`,
    { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
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
    if (r.exceptionDetails) return 'EXC: ' + JSON.stringify(r.exceptionDetails).slice(0, 160);
    return r.result && r.result.value;
  };
  const ready = async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 15000) {
      if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true;
      await sleep(200);
    }
    return false;
  };
  return { ev, send, ws, ready, id: t.id };
}

async function closeTab(tab) {
  try { tab.ws.close(); } catch (e) {}
  try { await fetch(`http://127.0.0.1:${PORT}/json/close/${tab.id}`); } catch (e) {}
}

// ---------------------------------------------------------------- 布局
const A = await openTab(APP);
const B = await openTab(APP);
check(await A.ready(), 'A 页面就绪');
check(await B.ready(), 'B 页面就绪');

// ---------------------------------------------------------------- 建房 & 入房
const created = await A.ev(`new Promise(function(res){
  ensureSocket();
  gameState.playerName = 'LiveA';
  gameState.socket.emit('create_room', { player_name: 'LiveA' }, function(r){ res(r); });
})`);
check(created && created.status === 'success', 'A 建自定义房', created);

const roomId = created.room_id;
const joined = await B.ev(`new Promise(function(res){
  ensureSocket();
  gameState.playerName = 'LiveB';
  gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name: 'LiveB' },
    function(r){ res(r); });
})`);
check(joined && joined.status === 'success', 'B 加入房间', joined);

// 让前端知道自己的身份
await A.ev(`(function(){
  gameState.roomId = ${JSON.stringify(roomId)};
  gameState.playerId = ${JSON.stringify(Object.keys(joined ? {} : {}).length ? '' : '')} || gameState.playerId;
  return true;
})()`);

// A 的 pid 需要从服务端问：join 返回的是 B 的 pid，A 是另一个
const aPid = await A.ev(`(function(){
  var keys = Object.keys(gameState.players || {});
  return keys.length ? keys : null;
})()`);

// 用 test 事件拿准确 pid（服务端已开 ENABLE_TEST_EVENTS）
async function stateOf(tab) {
  return await tab.ev(`new Promise(function(res){
    gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(r){ res(r); });
  })`);
}

// 先让两个页面把 roomId 记住
await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await A.ev(`gameState.playerId = ${JSON.stringify(joined.player_id)}; true`);

const st0 = await stateOf(A);
check(st0 && st0.status === 'success', '能读到房间状态', st0 && st0.status);

const pids = Object.keys(st0.game_state.players);
const bPid = joined.player_id;
const aPid2 = pids.find((p) => p !== bPid);
await A.ev(`gameState.playerId = ${JSON.stringify(aPid2)}; true`);

// ---------------------------------------------------------------- 摆船 + 猜拳
// 直接走服务端事件（UI 摆船交互太重，不是本次要验的东西）
async function placeAndRps() {
  const ships = (seed) => Array.from({ length: 6 }, (_, i) => ({
    positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [],
  }));
  await A.ev(`new Promise(function(res){
    gameState.socket.emit('place_ships', { room_id: gameState.roomId,
      player_id: ${JSON.stringify(aPid2)}, ships: ${JSON.stringify(ships(0))} }, function(r){ res(r); });
  })`);
  await B.ev(`new Promise(function(res){
    gameState.socket.emit('place_ships', { room_id: gameState.roomId,
      player_id: ${JSON.stringify(bPid)}, ships: ${JSON.stringify(ships(1))} }, function(r){ res(r); });
  })`);
  for (let i = 0; i < 12; i++) {
    await A.ev(`new Promise(function(res){
      gameState.socket.emit('rps_choice', { room_id: gameState.roomId,
        player_id: ${JSON.stringify(aPid2)}, choice: 'rock' }, function(r){ res(r); });
    })`);
    await B.ev(`new Promise(function(res){
      gameState.socket.emit('rps_choice', { room_id: gameState.roomId,
        player_id: ${JSON.stringify(bPid)}, choice: 'paper' }, function(r){ res(r); });
    })`);
    await sleep(400);
    const s = await stateOf(A);
    if (s.game_state.current_attacker) return s.game_state.current_attacker;
  }
  return null;
}
const attacker = await placeAndRps();
check(!!attacker, '猜拳分出先手', attacker);

// 先手 = A（rock vs paper 在本实现下 A 胜）；若反转则整体对调
const atkTab = attacker === aPid2 ? A : B;
const dfnTab = attacker === aPid2 ? B : A;
const atkPid = attacker;
const dfnPid = attacker === aPid2 ? bPid : aPid2;
await dfnTab.ev(`gameState.playerId = ${JSON.stringify(dfnPid)}; true`);
await atkTab.ev(`gameState.playerId = ${JSON.stringify(atkPid)}; true`);

// 给防守方一张速阶3（失灵！），让询问必然触发
await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('test_add_specific_magic_card', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(dfnPid)}, card_name: '失灵！' }, function(r){ res(r); });
})`);
await sleep(500);

// ---------------------------------------------------------------- 核心：点「进入战斗」
const beforeAtk = await stateOf(atkTab);
check(beforeAtk.game_state.current_phase === 'preparation',
  'A 处于准备阶段（前置条件）', beforeAtk.game_state.current_phase);

const enterRes = await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('enter_battle_phase', { room_id: gameState.roomId,
    player_id: gameState.playerId }, function(r){ res(r); });
})`);
check(enterRes && enterRes.awaiting_priority === true,
  '服务端挂起了阶段推进', enterRes);

// 等防守方的浏览器真的弹出面板
let panel = null;
for (let i = 0; i < 30; i++) {
  await sleep(200);
  panel = await dfnTab.ev(`(function(){
    var p = document.querySelector('.priority-prompt');
    if (!p) return null;
    var cd = p.querySelector('#priority-countdown');
    var cards = Array.prototype.map.call(p.querySelectorAll('.priority-card-name'),
      function(b){ return b.textContent; });
    return { title: p.querySelector('.priority-head h3').textContent,
             badge: p.querySelector('.priority-badge').textContent,
             countdown: cd ? cd.textContent : '',
             cards: cards,
             hasToggle: !!p.querySelector('#decline-priority-toggle'),
             hasCancel: !!p.querySelector('#priority-cancel') };
  })()`);
  if (panel) break;
}

check(!!panel, '★ 防守方的浏览器真的弹出了优先权面板', panel);
if (panel) {
  check(/优先权/.test(panel.badge), '徽章是「优先权」', panel.badge);
  check(/进入战斗阶段/.test(panel.title), '标题写明对方要进战斗阶段', panel.title);
  check(panel.cards.indexOf('失灵！') >= 0, '列出了他手上的速阶3', panel.cards);
  check(panel.hasToggle, '有拒绝开关');
  check(panel.hasCancel, '有取消按钮');
  // 倒计时在走
  //
  // ⚠️ 这条以前偶发假红（cd1=cd2=10）。根因不是功能坏了，而是**无头浏览器把
  // 后台标签页的 setInterval 节流**（两个标签页共用一个浏览器窗口时，非活动
  // 那个被当成 hidden，计时器可能被压到分钟级）。倒计时用的是 setInterval(1000)。
  // 修法：先把这个标签页置前（Page.bringToFront 会解除节流），再轮询等它真的变。
  const cd1 = panel.countdown;
  try { await dfnTab.send('Page.bringToFront'); } catch (e) { /* 置前失败也不致命 */ }
  await sleep(300);
  let cd2 = cd1;
  for (let i = 0; i < 8 && Number(cd2) >= Number(cd1); i++) {
    await sleep(700);
    cd2 = await dfnTab.ev(`(function(){
      var c = document.querySelector('#priority-countdown');
      return c ? c.textContent : null;
    })()`);
    if (cd2 === null) break;   // 窗口已经因超时关掉了，也算"走完了"
  }
  check(cd2 === null || Number(cd2) < Number(cd1), '倒计时在走', { cd1, cd2 });
}

// 关键断言：此刻 A 的阶段【还没推进】
const during = await stateOf(atkTab);
check(during.game_state.current_phase === 'preparation',
  '★ 询问期间发起者的阶段没被推进（本次修的核心）', during.game_state.current_phase);

// ────────────────────────────────────────────────────────────────
// 等待期间发起方必须被冻结（作者反馈：「对方不能暂停行动」）
// 以前只有阶段转换本身被拦下，发起方在 10 秒里照样能开炮/出牌，
// 这个仲裁窗口就等于没有。
// ────────────────────────────────────────────────────────────────
const waitUI = await atkTab.ev(`(function(){
  var banner = document.getElementById('priority-waiting-banner');
  var btn = document.getElementById('enter-battle-phase');
  return {
    waiting: !!gameState.priorityWaiting,
    bannerShown: !!banner && getComputedStyle(banner).display !== 'none',
    bannerText: banner ? banner.textContent : '',
    btnDisabled: btn ? btn.disabled : null
  };
})()`);
check(waitUI.waiting === true, '★ 发起方收到"等待对方响应"状态', waitUI);
check(waitUI.bannerShown && /等待对方响应/.test(waitUI.bannerText),
  '★ 发起方界面上显示等待横幅（不是一动不动）', waitUI);
check(waitUI.btnDisabled === true, '★ 等待期间阶段按钮被禁用', waitUI);

// 再点一次「进入战斗阶段」→ 必须被拒（否则双击就绕过了询问）
const bypass = await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('enter_battle_phase', { room_id: gameState.roomId,
    player_id: gameState.playerId }, function(r){ res(r); });
})`);
await sleep(600);
const afterBypass = await stateOf(atkTab);
check(bypass && bypass.status === 'error' && /等待对方响应/.test(bypass.message || ''),
  '★ 等待期间重复点阶段按钮会被拒绝（双击不能绕过询问）', bypass);
check(afterBypass.game_state.current_phase === 'preparation',
  '★ 被拒之后阶段仍然没被推进', afterBypass.game_state.current_phase);

// 攻击也要被拒。
// ⚠️ 这条走的是「阶段还没推进」这道既有门禁（此刻阶段仍是 preparation），
// 不是冻结本身；"战斗阶段 + 等待窗口"下攻击被冻结挡住的情形由
// tests/test_priority_prompt.py::test_actor_cannot_attack_while_waiting 精确覆盖。
const atkDuring = await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('attack', { room_id: gameState.roomId,
    player_id: gameState.playerId, x: 0, y: 0 }, function(r){ res(r); });
})`);
check(atkDuring && atkDuring.status === 'error',
  '★ 等待期间发起方无法继续攻击（服务端拒绝）', atkDuring);

// 出牌也要被拒
await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('test_add_specific_magic_card', { room_id: gameState.roomId,
    player_id: gameState.playerId, card_name: '五险一金' }, function(r){ res(r); });
})`);
await sleep(400);
const playDuring = await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('use_magic_card', { room_id: gameState.roomId,
    player_id: gameState.playerId, card: { name: '五险一金' }, targets: {} }, function(r){ res(r); });
})`);
check(playDuring && playDuring.status === 'error' && /等待对方响应/.test(playDuring.message || ''),
  '★ 等待期间发起方不能出牌', playDuring);

// ---------------------------------------------------------------- 点取消，阶段应推进
await dfnTab.ev(`(function(){
  var b = document.querySelector('#priority-cancel');
  if (b) b.click();
  return true;
})()`);
await sleep(1500);

const after = await stateOf(atkTab);
check(after.game_state.current_phase === 'battle',
  '★ 取消后阶段推进到 battle', after.game_state.current_phase);
const gone = await dfnTab.ev(`document.querySelectorAll('.priority-prompt').length`);
check(gone === 0, '防守方面板已关闭', gone);

// 等待结束后发起方必须解冻
const afterWaitUI = await atkTab.ev(`(function(){
  var banner = document.getElementById('priority-waiting-banner');
  return {
    waiting: !!gameState.priorityWaiting,
    bannerShown: !!banner && getComputedStyle(banner).display !== 'none'
  };
})()`);
check(afterWaitUI.waiting === false && afterWaitUI.bannerShown === false,
  '★ 响应到达后发起方解冻（横幅撤掉）', afterWaitUI);

console.log('');
if (problems.length) {
  console.log(`✗ ${problems.length} 项未通过：`);
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}

await closeTab(A);
await closeTab(B);
browser.kill();
process.exit(problems.length ? 1 : 0);
