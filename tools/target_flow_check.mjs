#!/usr/bin/env node
/**
 * Phase 4 门禁：用牌流程按「这张卡要不要选目标」分流。
 *
 * 规范（IMPLEMENTATION_PLAN_2026_09_23.md Phase 4 / UI_DEMO_OPTIONS §1 的 O 规范 C 方案）：
 *   · 无需目标的卡（失灵！/看破！…）→ **点两次即用**（保持原行为）
 *   · 需要目标的卡（神威！/冻结/轰炸/增援…）→ 选完目标再确认：
 *       ① 打开选择器时不提交，确认按钮**置灰**且文案是「在棋盘上选…」
 *       ② 点棋盘定位后，确认按钮**可用**且文案变成「确认使用 <卡名>！」
 *       ③ 点「确认」才真的发 use_magic_card
 *       ④ **点空白 = 取消**，不发 use_magic_card（= 不消耗卡）
 *       ⑤ 非法/越界 → 红框 + 确认置灰（不提交）
 *
 * 真实浏览器 + 真服务端（两标签页各当一个玩家），全部走真点击。
 * 用法：node tools/target_flow_check.mjs --url http://127.0.0.1:5055/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const PORT = 9465;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/target_flow_profile', APP], { stdio: 'ignore' });
await sleep(3200);

async function openTab(url) {
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`,
    { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let seq = 0; const pend = new Map();
  ws.onmessage = (m) => { const x = JSON.parse(m.data); if (x.id && pend.has(x.id)) { const { res, rej } = pend.get(x.id); pend.delete(x.id); x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result); } };
  const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + method)); } }, 25000); });
  await send('Runtime.enable');
  const ev = async (e) => { const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 300) }; return r.result && r.result.value; };
  return { ev, ws, id: t.id, ready: async () => { const t0 = Date.now(); while (Date.now() - t0 < 15000) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true; await sleep(200); } return false; } };
}

const A = await openTab(APP);
const B = await openTab(APP);
await A.ready(); await B.ready();

// 给页面装一个「数发了多少次 use_magic_card」的探针
const EMIT_TRAP = `(function(){
  window.__emits = [];
  var s = gameState.socket; if (!s) return 'no-socket';
  var orig = s.emit.bind(s);
  s.emit = function(ev, payload, cb){
    if (ev === 'use_magic_card') { window.__emits.push(payload && payload.card && payload.card.name); }
    return orig(ev, payload, cb);
  };
  return 'ok';
})()`;

const created = await A.ev(`new Promise(function(res){
  ensureSocket(); gameState.playerName='FlowA';
  gameState.socket.emit('create_room', { player_name:'FlowA' }, function(r){ res(r); });
})`);
const roomId = created.room_id;
const joined = await B.ev(`new Promise(function(res){
  ensureSocket(); gameState.playerName='FlowB';
  gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name:'FlowB' }, function(r){ res(r); });
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

const ships = (seed) => Array.from({ length: 6 }, (_, i) => ({ positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [] }));
await A.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: gameState.roomId, player_id: ${JSON.stringify(aPid)}, ships: ${JSON.stringify(ships(0))} }, function(r){ res(r); }); })`);
await B.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: gameState.roomId, player_id: ${JSON.stringify(bPid)}, ships: ${JSON.stringify(ships(1))} }, function(r){ res(r); }); })`);
let attacker = null;
for (let i = 0; i < 12 && !attacker; i++) {
  await A.ev(`new Promise(function(res){ gameState.socket.emit('rps_choice', { room_id: gameState.roomId, player_id: ${JSON.stringify(aPid)}, choice: 'rock' }, function(r){ res(r); }); })`);
  await B.ev(`new Promise(function(res){ gameState.socket.emit('rps_choice', { room_id: gameState.roomId, player_id: ${JSON.stringify(bPid)}, choice: 'paper' }, function(r){ res(r); }); })`);
  await sleep(400);
  const s = await A.ev(`new Promise(function(res){ gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); }); })`);
  attacker = s.game_state.current_attacker;
}
check(!!attacker, '（前提）猜拳分出先手', attacker);
const atkTab = attacker === aPid ? A : B;
const dfnTab = attacker === aPid ? B : A;
const atkPid = attacker;
const dfnPid = attacker === aPid ? bPid : aPid;
await atkTab.ev(`gameState.playerId = ${JSON.stringify(atkPid)}; true`);
await dfnTab.ev(`gameState.playerId = ${JSON.stringify(dfnPid)}; true`);
await atkTab.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
check(await atkTab.ev(EMIT_TRAP) === 'ok', '（前提）use_magic_card 探针已装上');

// 发一手卡：一张无需目标（看破！）+ 一张需要目标（冻结 3×3）。
// ⚠️ 用服务端现成的 test_add_specific_magic_card（逐张 append，见 hand_play_check 的用法）。
async function setHand(names) {
  await atkTab.ev(`new Promise(function(res){
    gameState.socket.emit('test_clear_all_effects', { room_id: gameState.roomId, player_id: gameState.playerId }, function(r){ res(r); });
  })`);
  await sleep(250);
  for (const n of names) {
    const r = await atkTab.ev(`new Promise(function(res){
      gameState.socket.emit('test_add_specific_magic_card', { room_id: gameState.roomId,
        player_id: gameState.playerId, card_name: ${JSON.stringify(n)} }, function(x){ res(x); });
    })`);
    if (r && r.status === 'error') return r;
  }
  await sleep(700);
  return { status: 'success' };
}

/** 数当前手牌里某张卡的下标 */
async function idxOf(name) {
  return await atkTab.ev(`(function(){
    var i = (gameState.hand||[]).findIndex(function(c){ return c && c.name === ${JSON.stringify(name)}; });
    return i;
  })()`);
}
/** 真实点击手牌里第 i 张 */
async function clickCard(i) {
  return await atkTab.ev(`(function(){
    var c = document.querySelector('#magic-hand .magic-card[data-index="${i}"]');
    if (!c) return 'no-card';
    c.click();
    return 'clicked';
  })()`);
}
const emits = async () => await atkTab.ev('(window.__emits||[]).slice()');

// ---------------------------------------------------------------- A. 无需目标：点两次即用
console.log('--- A. 无需目标的卡：点两次即用 ---');
{
  const r = await setHand(['看破！']);
  check(!(r && r.status === 'error'), '（前提）能发牌（看破！）', r && r.status);
  const i = await idxOf('看破！');
  check(i === 0, '（前提）看破！在手牌里', i);
  await atkTab.ev('window.__emits = []; true');
  await clickCard(i);            // 第一次：进入待使用
  await sleep(350);
  const midway = await emits();
  check(midway.length === 0, '第一次点击不发牌（只进待使用）', midway);
  await clickCard(i);            // 第二次：直接使用
  await sleep(700);
  const after = await emits();
  check(after.length === 1 && after[0] === '看破！', '★ 无需目标的卡：点两次即用（第二次点击直接发出）', after);
}

// ---------------------------------------------------------------- B. 需要目标：选完再确认
console.log('--- B. 需要目标的卡：选完目标再确认 ---');
{
  const r = await setHand(['冻结']);
  check(!(r && r.status === 'error'), '（前提）能发牌（冻结）', r && r.status);
  const i = await idxOf('冻结');
  check(i >= 0, '（前提）冻结在手牌里', i);
  await atkTab.ev('window.__emits = []; true');
  await clickCard(i);            // 1st
  await sleep(300);
  await clickCard(i);            // 2nd → 打开选择器（不提交）
  await sleep(500);

  const bar = await atkTab.ev(`(function(){
    var btn = document.getElementById('area-confirm');
    var info = document.getElementById('area-picker-info');
    var anchors = document.querySelectorAll('#opponent-board .cell.sel-anchor').length;
    return {
      hasBar: !!btn,
      disabled: btn ? btn.disabled : null,
      text: btn ? btn.textContent : null,
      info: info ? info.textContent : null,
      anchors: anchors,
    };
  })()`);
  check(bar.hasBar, '★ 需要目标的卡：第二次点击打开目标选择器（不再"再点即用"）', bar);
  check(bar.disabled === true, '★ 未选目标时确认按钮置灰', bar);
  check(/在棋盘上选/.test(String(bar.text)), '★ 未选目标时按钮文案是「在棋盘上选…」', bar.text);
  check(bar.anchors > 0, '★ 打开时把合法落点画成虚框锚点', bar.anchors);
  const preEmits = await emits();
  check(preEmits.length === 0, '★ 打开选择器本身不提交（未发 use_magic_card）', preEmits);

  // 点棋盘定位
  await atkTab.ev(`(function(){
    var c = document.querySelector('#opponent-board .cell[data-x="1"][data-y="1"]');
    if (c) c.click();
    return true;
  })()`);
  await sleep(400);
  const picked = await atkTab.ev(`(function(){
    var btn = document.getElementById('area-confirm');
    return { disabled: btn ? btn.disabled : null, text: btn ? btn.textContent : null };
  })()`);
  check(picked.disabled === false, '★ 选完目标后确认按钮可用', picked);
  check(/确认使用\s*冻结/.test(String(picked.text)), '★ 按钮文案随状态变成「确认使用 冻结！」', picked.text);
  const midEmits = await emits();
  check(midEmits.length === 0, '★ 选完目标仍未提交（要等确认）', midEmits);

  // 点空白 = 取消（不消耗卡）
  await atkTab.ev(`(function(){
    var t = document.querySelector('.log-container') || document.body;
    t.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return true;
  })()`);
  await sleep(500);
  const afterBlank = await atkTab.ev(`(function(){
    return {
      bar: !!document.getElementById('area-confirm'),
      hand: (gameState.hand||[]).map(function(c){ return c.name; }),
    };
  })()`);
  const blankEmits = await emits();
  check(blankEmits.length === 0, '★ 点空白 = 取消（不发 use_magic_card）', blankEmits);
  check(afterBlank.bar === false, '★ 点空白后选择器已关闭', afterBlank);
  check(afterBlank.hand.indexOf('冻结') >= 0, '★ 取消后卡还在手上（不消耗卡）', afterBlank.hand);

  // 再来一次，走完整确认路径
  const i2 = await idxOf('冻结');
  await clickCard(i2); await sleep(300);
  await clickCard(i2); await sleep(500);
  await atkTab.ev(`(function(){
    var c = document.querySelector('#opponent-board .cell[data-x="2"][data-y="2"]');
    if (c) c.click();
    return true;
  })()`);
  await sleep(350);
  await atkTab.ev(`(function(){ var b=document.getElementById('area-confirm'); if(b) b.click(); return true; })()`);
  await sleep(700);
  const finalEmits = await emits();
  check(finalEmits.length === 1 && finalEmits[0] === '冻结', '★ 点「确认使用」才真的发牌', finalEmits);
}

// ---------------------------------------------------------------- C. 非法/越界不提交
console.log('--- C. 合法落点被钳制在棋盘内（不会越界提交）---');
{
  const r = await setHand(['冻结']);
  check(!(r && r.status === 'error'), '（前提）再发一张冻结', r && r.status);
  const i = await idxOf('冻结');
  await atkTab.ev('window.__emits = []; true');
  await clickCard(i); await sleep(300);
  await clickCard(i); await sleep(500);
  // 点最右下角：3×3 区域必须被钳到 (3,3)-(5,5) 之内（不能越界）
  await atkTab.ev(`(function(){
    var c = document.querySelector('#opponent-board .cell[data-x="5"][data-y="5"]');
    if (c) c.click();
    return true;
  })()`);
  await sleep(350);
  const info = await atkTab.ev(`(function(){
    var el = document.getElementById('area-picker-info');
    return el ? el.textContent : null;
  })()`);
  // 3×3 落在 (3,3) 起 → 列 4–6、行 4–6；若出现 7 就是越界
  check(!!info && /第\s*4[–-]6\s*列/.test(info) && !/第\s*7/.test(info),
    '★ 点棋盘右下角时区域被钳制在 6×6 内（不出现第 7 列/行）', info);
  await atkTab.ev(`(function(){ var b=document.querySelector('#area-cancel'); if(b) b.click(); return true; })()`);
  await sleep(300);
}

console.log('\n' + (problems.length ? '✗ ' + problems.length + ' 项未通过：\n   · ' + problems.join('\n   · ') : '✓ 全部通过'));
browser.kill();
process.exit(problems.length ? 1 : 0);
