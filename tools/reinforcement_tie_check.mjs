#!/usr/bin/env node
/**
 * 「极限增援结算时双方船数相同 → 卡死 / 阶段按钮消失」真实浏览器复现 + 回归。
 *
 * 作者反馈：
 *   极限增援卡牌出现问题。当双方船数相等时不会判定谁获胜，
 *   但是游戏会直接卡死，无法进行下一步操作，就是不能结束阶段了按钮直接消失了。
 *
 * 读代码的嫌疑点：`end_turn` 里 `if next_index == 0:` 那一段是【进入新大回合】的收尾，
 * 极限增援的结算就夹在里面。双方船数相同时它走的是：
 *     room.game_effects.pop('reinforcement_check', None)
 *     emit('message', {…'无人获胜'…})
 *     return {'status': 'success'}          # ← 从 end_turn 里直接 return
 * 这个 return 把后面【真正换人 + 重置阶段 + 广播】全跳过了：
 *   · room.state 不回到 rock_paper_scissors
 *   · current_attacker / current_phase 原样不动
 *   · 一条 turn_change / phase_updated / game_state 都不发
 * 于是客户端的阶段按钮停在旧状态 —— 玩家看到的就是"下一步不了 / 按钮没了"。
 *
 * 本工具在真实浏览器里把这条路径走完，并断言：
 *   · 结算之后客户端仍能继续操作（按钮还在，点了真的推进回合）
 *   · 结算那一刻客户端收到了能反映"回合推进/需要重新猜拳"的事件
 *
 * 用法：ENABLE_TEST_EVENTS=1 起服务，然后
 *      node tools/reinforcement_tie_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9423;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/reinf_tie_profile', APP], { stdio: 'ignore' });

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

await sleep(3000);

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
    setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + method)); } }, 25000);
  });
  await send('Runtime.enable');
  const ev = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 300) };
    return r.result && r.result.value;
  };
  return { ev, ws, id: t.id, name: '?',
    ready: async () => {
      const t0 = Date.now();
      while (Date.now() - t0 < 15000) {
        if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true;
        await sleep(200);
      }
      return false;
    } };
}

const A = await openTab(APP);
const B = await openTab(APP);
A.name = 'A'; B.name = 'B';
await A.ready(); await B.ready();

// 记录客户端视角的阶段状态与三个阶段按钮的可见性
const SNAP = `(function(){
  var btn = function(id){
    var el = document.getElementById(id);
    if (!el) return 'no-element';
    return getComputedStyle(el).display;
  };
  return {
    phase: gameState.currentPhase,
    attackerIsMe: gameState.currentAttacker === gameState.playerId,
    state: gameState.gameStateName || null,
    screens: Array.prototype.filter.call(document.querySelectorAll('.screen'), function(s){
      return s.classList.contains('active');
    }).map(function(s){ return s.id; }),
    enterBattle: btn('enter-battle-phase'),
    enterEnd: btn('enter-end-phase'),
    endTurn: btn('end-turn-btn'),
    phaseText: (document.getElementById('current-phase') || {}).textContent || '',
    attacks: (document.getElementById('attacks-remaining') || {}).textContent || ''
  };
})()`;

async function snap(tab, tag) {
  const s = await tab.ev(SNAP);
  console.log(`  [${tag}] phase=${s.phase} 我攻=${s.attackerIsMe} 屏幕=${JSON.stringify(s.screens)} ` +
              `按钮(战/末/交)=${s.enterBattle}/${s.enterEnd}/${s.endTurn} 攻击次数=${s.attacks}`);
  return s;
}

// ── 建房 / 入房 / 摆船 / 猜拳 ─────────────────────────────────
const created = await A.ev(`new Promise(function(res){
  ensureSocket();
  gameState.playerName = 'ReinfA';
  gameState.socket.emit('create_room', { player_name: 'ReinfA' }, function(r){ res(r); });
})`);
const roomId = created.room_id;
const joined = await B.ev(`new Promise(function(res){
  ensureSocket();
  gameState.playerName = 'ReinfB';
  gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name: 'ReinfB' },
    function(r){ res(r); });
})`);
await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await A.ev(`gameState.playerId = ${JSON.stringify(joined.player_id)}; true`);
const st0 = await A.ev(`new Promise(function(res){
  gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
})`);
const bPid = joined.player_id;
const aPid = Object.keys(st0.game_state.players).find((p) => p !== bPid);
await A.ev(`gameState.playerId = ${JSON.stringify(aPid)}; true`);
await B.ev(`gameState.playerId = ${JSON.stringify(bPid)}; true`);

const ships = (seed) => Array.from({ length: 6 }, (_, i) => ({
  positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [],
}));
await A.ev(`new Promise(function(res){
  gameState.socket.emit('place_ships', { room_id: gameState.roomId, player_id: ${JSON.stringify(aPid)},
    ships: ${JSON.stringify(ships(0))} }, function(r){ res(r); });
})`);
await B.ev(`new Promise(function(res){
  gameState.socket.emit('place_ships', { room_id: gameState.roomId, player_id: ${JSON.stringify(bPid)},
    ships: ${JSON.stringify(ships(1))} }, function(r){ res(r); });
})`);

// 页面自己处理猜拳/优先权询问/连锁（点真实按钮或直接 emit）
await A.ev(`(function(){
  window.__msg = [];
  ['showAlert','showMessage'].forEach(function(fn){
    var o = window[fn];
    if (typeof o === 'function') window[fn] = function(){ window.__msg.push(fn+': '+arguments[0]); return o.apply(this, arguments); };
  });
  return true;
})()`);
await B.ev(`(function(){
  window.__msg = [];
  ['showAlert','showMessage'].forEach(function(fn){
    var o = window[fn];
    if (typeof o === 'function') window[fn] = function(){ window.__msg.push(fn+': '+arguments[0]); return o.apply(this, arguments); };
  });
  return true;
})()`);

let attacker = null;
for (let i = 0; i < 12 && !attacker; i++) {
  await A.ev(`new Promise(function(res){
    gameState.socket.emit('rps_choice', { room_id: gameState.roomId, player_id: ${JSON.stringify(aPid)},
      choice: 'rock' }, function(r){ res(r); });
  })`);
  await B.ev(`new Promise(function(res){
    gameState.socket.emit('rps_choice', { room_id: gameState.roomId, player_id: ${JSON.stringify(bPid)},
      choice: 'paper' }, function(r){ res(r); });
  })`);
  await sleep(400);
  const s = await A.ev(`new Promise(function(res){
    gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
  })`);
  attacker = s.game_state.current_attacker;
}
check(!!attacker, '猜拳分出先手', attacker);
const atkTab = attacker === aPid ? A : B;
const dfnTab = attacker === aPid ? B : A;
const atkPid = attacker;
const dfnPid = attacker === aPid ? bPid : aPid;
await atkTab.ev(`gameState.playerId = ${JSON.stringify(atkPid)}; true`);
await dfnTab.ev(`gameState.playerId = ${JSON.stringify(dfnPid)}; true`);
console.log('攻击方 =', atkTab.name);

// 前端把阶段/回合状态交给客户端自己的事件处理；确保页面已经在对局屏
await A.ev(`(function(){ var s = document.getElementById('game-screen'); if (s) switchScreen(s); return true; })()`);
await B.ev(`(function(){ var s = document.getElementById('game-screen'); if (s) switchScreen(s); return true; })()`);
await sleep(800);

async function gs(tab) {
  return await tab.ev(`new Promise(function(res){
    gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
  })`);
}

// 把可能挡路的窗口都点掉：优先权询问 / 连锁响应。
// ⚠️ 连锁窗口不关掉，use_magic_card 的效果就不会结算（一直挂在 chain 里），
// 本用例会假红（"极限增援没生效"）。
async function dismissAll() {
  for (const tab of [A, B]) {
    await tab.ev(`(function(){
      var acted = [];
      var p = document.querySelector('#priority-cancel');
      if (p) { p.click(); acted.push('priority'); }
      var c = document.querySelector('#chain-cancel');
      if (c) { c.click(); acted.push('chain'); }
      return acted;
    })()`);
  }
}

// 等连锁结算完（窗口归属会在两边来回），期间不断点掉响应窗口
async function waitChainClear(maxMs = 14000) {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    const s = await gs(A);
    const g = s && s.game_state;
    if (!g || (!g.chain_window && (!g.chain || g.chain.length === 0))) return true;
    await dismissAll();
    await sleep(400);
  }
  return false;
}

// 让当前攻击者打出「极限增援」（速阶1 → 准备阶段）
await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('test_add_specific_magic_card', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(atkPid)}, card_name: '极限增援' }, function(r){ res(r); });
})`);
await sleep(400);
let st = await gs(atkTab);
if (st.game_state.current_phase !== 'preparation') {
  console.log('（当前不在准备阶段，先把回合走完再打）phase =', st.game_state.current_phase);
}
const cast = await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('use_magic_card', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(atkPid)}, card: { name: '极限增援' }, targets: {} }, function(r){ res(r); });
})`);
await waitChainClear();
await sleep(500);
st = await gs(atkTab);
check(st.game_state.game_effects.indexOf('reinforcement_check') >= 0,
  '★ 前置条件：极限增援已生效', { ack: cast, effects: st.game_state.game_effects });

// 双方船数调成相等
await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('test_set_player_ships', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(atkPid)}, ship_count: 4 }, function(r){ res(r); });
})`);
await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('test_set_opponent_ships', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(atkPid)}, ship_count: 4 }, function(r){ res(r); });
})`);
await sleep(600);
st = await gs(atkTab);
const shipCounts = Object.keys(st.game_state.players)
  .map((p) => (p === aPid ? 'A' : 'B') + ':' + st.game_state.players[p].remaining_ships);
check(new Set(shipCounts.map((s) => s.split(':')[1])).size === 1,
  '★ 前置条件：双方船数相等', shipCounts);

// ── 推进大回合，直到极限增援结算 ────────────────────────────────
// 大回合之间会回到猜拳：必须把猜拳打掉，否则房间一直停在 rock_paper_scissors
async function ensureAttacking() {
  for (let i = 0; i < 14; i++) {
    const s = await gs(A);
    if (s.game_state.state === 'attacking') return true;
    if (s.game_state.state === 'game_over') return false;
    await A.ev(`new Promise(function(res){
      gameState.socket.emit('rps_choice', { room_id: gameState.roomId,
        player_id: ${JSON.stringify(aPid)}, choice: 'rock' }, function(r){ res(r); });
    })`);
    await B.ev(`new Promise(function(res){
      gameState.socket.emit('rps_choice', { room_id: gameState.roomId,
        player_id: ${JSON.stringify(bPid)}, choice: 'paper' }, function(r){ res(r); });
    })`);
    await sleep(500);
  }
  return false;
}

async function advanceOneTurn() {
  await ensureAttacking();
  const s = await gs(atkTab);
  if (s.game_state.state !== 'attacking') return { skipped: 'state=' + s.game_state.state };
  const pid = s.game_state.current_attacker;
  const tab = pid === aPid ? A : B;
  if (s.game_state.current_phase === 'preparation') {
    await tab.ev(`new Promise(function(res){
      gameState.socket.emit('enter_battle_phase', { room_id: gameState.roomId,
        player_id: gameState.playerId }, function(r){ res(r); });
    })`);
    await sleep(900);
    await dismissAll();       // 对方的优先权询问
    await sleep(700);
  }
  const s2 = await gs(atkTab);
  if (s2.game_state.current_phase === 'battle') {
    await tab.ev(`new Promise(function(res){
      gameState.socket.emit('test_end_turn', { room_id: gameState.roomId }, function(r){ res(r); });
    })`);
    await sleep(300);
  }
  return await tab.ev(`new Promise(function(res){
    gameState.socket.emit('end_turn', { room_id: gameState.roomId, player_id: gameState.playerId },
      function(r){ res(r); });
  })`);
}

let tieStep = -1;
let roundAtTie = 0;
for (let step = 0; step < 20; step++) {
  const s = await gs(atkTab);
  if (s.game_state.game_effects.indexOf('reinforcement_check') < 0) break;
  console.log(`\n--- 第 ${step} 步（round=${s.game_state.round} phase=${s.game_state.current_phase} state=${s.game_state.state}）---`);
  await A.ev('window.__msg = []; true'); await B.ev('window.__msg = []; true');
  const ack = await advanceOneTurn();
  await sleep(1200);
  const s2 = await gs(atkTab);
  console.log('    ack =', JSON.stringify(ack), '-> round=', s2.game_state.round,
              'phase=', s2.game_state.current_phase, 'state=', s2.game_state.state,
              'attacker=', s2.game_state.current_attacker === aPid ? 'A' : 'B');
  const msgs = await atkTab.ev('window.__msg || []');
  if (msgs && msgs.length) console.log('    提示:', JSON.stringify(msgs));
  if (s2.game_state.game_effects.indexOf('reinforcement_check') < 0) {
    tieStep = step;
    roundAtTie = s.game_state.round;   // 结算前那一刻的回合数
    console.log('    ★ 极限增援在本步结算了');
    break;
  }
}
check(tieStep >= 0, '★ 走到极限增援结算那一步（前置条件）', tieStep);

// ── 核心：结算之后游戏必须还能继续 ────────────────────────────────
console.log('\n=== 结算后的客户端状态 ===');
const afterAtk = await snap(atkTab, atkTab.name + '(刚结束回合的玩家)');
const afterDfn = await snap(dfnTab, dfnTab.name);
const stAfter = await gs(atkTab);
console.log('  服务端:', JSON.stringify({ state: stAfter.game_state.state,
  phase: stAfter.game_state.current_phase, round: stAfter.game_state.round }));

check(stAfter.game_state.state !== 'game_over',
  '★ 平局不判胜负（作者裁定）', stAfter.game_state.state);

// 平局之后必须【照常进入新大回合】：回合数 +1、状态回到猜拳。
// 以前这里直接从 end_turn 里 return，回合不推进、一条状态事件都不发，
// 客户端界面停在旧阶段 → 交回合按钮消失、下一步不了。
check(stAfter.game_state.state === 'rock_paper_scissors',
  '★ 平局后进入新大回合（state=rock_paper_scissors，而不是卡在 attacking+end）',
  { state: stAfter.game_state.state, phase: stAfter.game_state.current_phase });
check(stAfter.game_state.round >= roundAtTie + 1,
  '★ 回合数正常 +1（不是原地不动，也不是靠玩家再点一次才 +2）',
  { before: roundAtTie, after: stAfter.game_state.round });

// 客户端必须收到 game_state 并切到猜拳界面 —— 这才是"能继续操作"的证据
const onRps = [afterAtk, afterDfn].filter((s) => (s.screens || []).indexOf('rps-screen') >= 0);
check(onRps.length === 2,
  '★ 双方客户端都切到了猜拳界面（收到了状态广播，不是停在对局屏干等）',
  { A: afterAtk.screens, B: afterDfn.screens });

// 真的把猜拳打掉，确认能回到对局并轮换攻击者
const resumed = await ensureAttacking();
const stResumed = await gs(atkTab);
check(resumed && stResumed.game_state.state === 'attacking',
  '★ 打完猜拳能回到对局（没有卡死）',
  { state: stResumed.game_state.state, round: stResumed.game_state.round });

console.log('');
if (problems.length) {
  console.log(`✗ ${problems.length} 项未通过：`);
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}

try { A.ws.close(); await fetch(`http://127.0.0.1:${PORT}/json/close/${A.id}`); } catch (e) {}
try { B.ws.close(); await fetch(`http://127.0.0.1:${PORT}/json/close/${B.id}`); } catch (e) {}
browser.kill();
process.exit(problems.length ? 1 : 0);
