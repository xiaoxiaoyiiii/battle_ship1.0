#!/usr/bin/env node
/**
 * 绝处逢生 的两类回归检查（无头 Edge + CDP）。
 *
 * 【1~3 节】候选格画在哪块棋盘（2026-09-16 作者实测）
 *   自己放绝处逢生后，属于**自己棋盘**的候选格被画到了**对手棋盘**上 ——
 *   看起来像"敌方可能在这几格"，直接误导自己的攻击。
 *   根因：initGameBoards() 里两块棋盘是两个独立循环，候选格只写在对手棋盘那个
 *   循环里；服务端下发的 last_stand_cells 也不带归属，前端无从判断。
 *   修法：载荷加 owner，前端按 owner 决定画在哪块棋盘。
 *
 * 【4 节】真机链路：放置面板里必须**有格子能点**（2026-09-17 作者实测）
 *   「绝处逢生生效后的船位置选择界面没有可用位置供玩家选择了」。
 *   病灶：绝处逢生把全部战舰牺牲进 sunken_ships，而 _placement_blocked_cells 按
 *   「ships ∪ sunken_ships」算己方占位（那是给死者苏生/增援加的"刚沉掉那格不能摆"
 *   口径）→ 六个候选格全被判成"已占用"；前端 `blocked.has(key)` 又优先于白名单
 *   （allowed），于是六格全灰、一个都点不了。
 *   这里用真页面 + 人机对手跑真实链路（不需要第二个客户端，避开合成场景的干扰）。
 *   ⚠️ 需要 `ENABLE_TEST_EVENTS=1`（要用测试桩把牌塞进手牌）；未开放时打印 SKIP。
 *
 * 用法：
 *   node tools/last_stand_board_check.mjs --url http://127.0.0.1:5000/
 *   被检查的服务端：PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 ENABLE_TEST_EVENTS=1 python server.py
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9447;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  // profile 放项目内 .tmp/（C:/Windows/Temp 出现过 ACL 损坏）
  '--user-data-dir=' + path.join(HERE, '..', '.tmp', 'last_stand_board_profile'),
  '--window-size=1600,1000', 'about:blank'], { stdio: 'ignore' });
await sleep(3000);

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || '')) ||
  list.find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0; const pend = new Map();
ws.onmessage = (m) => {
  const x = JSON.parse(m.data);
  if (x.id && pend.has(x.id)) { const p = pend.get(x.id); pend.delete(x.id); x.error ? p.j(new Error(JSON.stringify(x.error))) : p.r(x.result); }
};
const send = (method, params = {}) => new Promise((r, j) => { const id = ++seq; pend.set(id, { r, j }); ws.send(JSON.stringify({ id, method, params })); });
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return 'EXC: ' + (r.exceptionDetails.exception?.description || '').slice(0, 220);
  return r.result && r.result.value;
};
async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await fn()) return true; } catch (e) { /* keep polling */ }
    await sleep(200);
  }
  throw new Error('等待超时: ' + label);
}

const problems = [];
const check = (ok, label, detail) => {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
};

await send('Page.enable');
await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: APP });
await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');

// 先走真实流程进一局人机对战：第 4 节要在真机上出牌（真 socket），
// 顺序放在最前面，免得后面 stub 掉 emit 影响开局。
async function enterGame() {
  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="绝处检查"; document.getElementById("ai-match").click(); return true;})()');
  await waitFor(async () => await ev('document.getElementById("ship-placement-screen").classList.contains("active")'), 30000, '布船界面');
  await ev('document.getElementById("random-ships").click()');
  await sleep(400);
  await ev('document.getElementById("confirm-ships").click()');
  await waitFor(async () => await ev('document.getElementById("rps-screen").classList.contains("active")'), 30000, '猜拳界面');
  for (let i = 0; i < 6; i++) {
    await ev('document.querySelectorAll(".rps-choice")[0].click()');
    await sleep(3000);
    if (await ev('document.getElementById("game-screen").classList.contains("active")')) break;
  }
  await waitFor(async () => await ev('document.getElementById("game-screen").classList.contains("active")'), 20000, '对局界面');
  await sleep(800);
}

let enteredGame = false;
try { await enterGame(); enteredGame = true; } catch (e) { /* 进不去就跳过第 4 节 */ }

// ===================== 第 4 节：真机链路，放置面板必须有格子能点 =====================
if (!enteredGame) {
  console.log('SKIP  4x 真机链路：没能进入对局界面（' + APP + '）');
} else {
  const PANEL_STATE = `(function(){
    var cells = [].slice.call(document.querySelectorAll('#placement-prompt .placement-cell'));
    return {
      panel: !!document.getElementById('placement-prompt'),
      total: cells.length,
      blocked: cells.filter(function (c) { return c.classList.contains('blocked'); }).length,
      title: (document.querySelector('#placement-prompt h3') || {}).textContent || ''
    }; })()`;

  const added = await ev(`(function(){ window.__addAck = null;
    gameState.socket.emit('test_add_specific_magic_card', { room_id: gameState.roomId, player_id: gameState.playerId, card_name: '绝处逢生' },
      function (r) { window.__addAck = r; });
    return 'sent'; })()`);
  await sleep(500);
  const addResp = await ev('(function(){ return window.__addAck; })()');
  const hasCard = await ev(`(function(){ return (gameState.hand || []).some(function (c) { return c && c.name === '绝处逢生'; }); })()`);
  if (!hasCard) {
    console.log('SKIP  4x 真机链路（真实出牌触发放置面板）：本服务端未向本客户端开放调试事件');
    console.log('      ' + JSON.stringify(addResp));
    console.log('      本地跑法：PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 ENABLE_TEST_EVENTS=1 python server.py');
  } else {
    const ships = await ev('(function(){ return (gameState.ships || []).filter(function (s) { return s.alive !== false; }).length; })()');
    if (ships < 3) {
      // 绝处逢生要求 ≥3 艘；人机房默认 6 艘，打了一会儿可能已经掉到 3 以下
      await ev(`(function(){ gameState.socket.emit('test_set_player_ships', { room_id: gameState.roomId, player_id: gameState.playerId, ship_count: 5 }); return true; })()`);
      await sleep(900);
    }
    await ev(`(function(){ window.__useAck = null;
      gameState.socket.emit('use_magic_card', { room_id: gameState.roomId, player_id: gameState.playerId, card: { name: '绝处逢生' }, targets: {} },
        function (r) { window.__useAck = r; });
      return 'sent'; })()`);
    // 连锁要等对方放弃（人机由服务端自己响应）；期间我方若被问"要不要响应"就直接放弃
    let panel = null;
    for (let i = 0; i < 40; i++) {
      await sleep(500);
      panel = await ev(PANEL_STATE);
      if (panel && panel.panel) break;
      await ev('(function(){ var b = document.getElementById("chain-cancel"); if (b) { b.click(); return true; } return false; })()');
    }
    const useAck = await ev('(function(){ return window.__useAck; })()');
    check(!!panel && panel.panel === true, '★ 4a 真实出牌后弹出放置面板', { panel: panel && panel.panel, ack: useAck });
    if (panel && panel.panel) {
      const clickable = (panel.total || 0) - (panel.blocked || 0);
      check((panel.total || 0) > 0, '4b 面板里有格子', panel.total);
      check(clickable > 0, '★ 4c 至少有格子可以点（作者报的"没有可用位置"）',
        { total: panel.total, blocked: panel.blocked, clickable });
      const picked = await ev(`(function(){
        var c = [].slice.call(document.querySelectorAll('#placement-prompt .placement-cell'))
          .filter(function (el) { return !el.classList.contains('blocked'); })[0];
        if (!c) return 'none';
        c.click();
        var btn = document.getElementById('placement-confirm');
        return { selected: !!document.querySelector('#placement-prompt .placement-cell.selected'),
                 confirmEnabled: btn ? !btn.disabled : null }; })()`);
      check(picked && picked.selected === true, '★ 4d 候选格真的能被点选', picked);
      check(picked && picked.confirmEnabled === true, '4e 点选后「确认」可用', picked);
      // 真提交一次，确认服务端也接受（走真实 socket）
      const done = await ev(`(function(){ window.__doneAck = null;
        var btn = document.getElementById('placement-confirm');
        var s = gameState.socket;
        if (!s.__realEmit) { s.__realEmit = s.emit; }
        s.emit('confirm_reinforcement_position', { room_id: gameState.roomId, player_id: gameState.playerId,
          position: (function(){ var el = document.querySelector('#placement-prompt .placement-cell.selected'); return el ? { x: parseInt(el.dataset.x,10), y: parseInt(el.dataset.y,10) } : null; })() },
          function (r) { window.__doneAck = r; });
        return 'sent'; })()`);
      await sleep(900);
      const doneAck = await ev('(function(){ return window.__doneAck; })()');
      check(!!doneAck && doneAck.status === 'success', '★ 4f 提交后服务端接受（真的放得下这一艘船）', doneAck);
    }
  }
}

// ===================== 1~3 节：候选格画在哪块棋盘（注入事件） =====================
await ev(`(function(){
  if (typeof switchScreen === 'function' && typeof gameScreen !== 'undefined' && gameScreen) switchScreen(gameScreen);
  gameState.playerId = 'me'; gameState.roomId = 'r1';
  window.__fired = [];
  var s = gameState.socket;
  if (!s) return 'no-socket';
  if (!s.__realEmit) { s.__realEmit = s.emit; }
  s.emit = function (ev, data, cb) { window.__fired.push({ ev: ev, data: data }); if (typeof cb === 'function') { try { cb({ status: 'success' }); } catch (e) {} } };
  return 'ready'; })()`);
await sleep(300);

// 触发页面**真实注册**的 last_stand_cells 监听器
async function fire(cells, owner) {
  return await ev(`(function(){
    var cbs = gameState.socket && gameState.socket._callbacks && gameState.socket._callbacks['$last_stand_cells'];
    if (!cbs || !cbs.length) return 'no-handler';
    cbs[0]({ cells: ${JSON.stringify(cells)}, owner: ${JSON.stringify(owner)} });
    return 'ok'; })()`);
}

function countExpr(board, cls) {
  return `document.querySelectorAll('#${board} .cell.${cls}').length`;
}

// ---- 1. owner = 我 → 高亮必须在我的棋盘 ----
let r = await fire([{ x: 1, y: 1 }, { x: 3, y: 4 }], 'me');
check(r === 'ok', '1a 触发 last_stand_cells（owner = 我）', r);
await sleep(350);
const mineOnMine = await ev(countExpr('game-player-board', 'last-stand-candidate'));
const mineOnOpp = await ev(countExpr('opponent-board', 'last-stand-candidate'));
check(mineOnMine === 2, '★ 1b 我放的候选格高亮在【我的】棋盘（2 格）', mineOnMine);
check(mineOnOpp === 0, '★ 1c 绝不在【对手】棋盘上出现（作者报的 bug）', mineOnOpp);

// 候选格不能被画成叉（09-14 的教训：一画叉玩家就以为打不了）
const wronglyHit = await ev(`document.querySelectorAll('#game-player-board .cell.last-stand-candidate.hit, #game-player-board .cell.last-stand-candidate.miss').length`);
check(wronglyHit === 0, '1d 候选格没有被画成命中/落空（否则玩家以为打不了）', wronglyHit);

// ---- 2. owner = 对方 → 高亮必须在攻击目标棋盘 ----
r = await fire([{ x: 2, y: 2 }], 'opp');
check(r === 'ok', '2a 触发 last_stand_cells（owner = 对方）', r);
await sleep(350);
const oppOnOpp = await ev(countExpr('opponent-board', 'last-stand-candidate'));
const oppOnMine = await ev(countExpr('game-player-board', 'last-stand-candidate'));
check(oppOnOpp === 1, '★ 2b 对方放的候选格高亮在【攻击目标】棋盘（1 格）', oppOnOpp);
check(oppOnMine === 0, '★ 2c 不该出现在我自己的棋盘上', oppOnMine);
const oppClickable = await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="2"][data-y="2"]');
  if (!c) return 'missing';
  return { blocked: c.classList.contains('blocked') || c.disabled === true, cls: c.className }; })()`);
check(oppClickable && oppClickable.blocked === false, '2d 候选格仍可点（对方要能往这几格打）', oppClickable);

// ---- 3. 清空 ----
r = await fire([], null);
check(r === 'ok', '3a 触发清空', r);
await sleep(300);
const afterClear = await ev(`document.querySelectorAll('.last-stand-candidate').length`);
check(afterClear === 0, '3b 清空后两块棋盘都不再高亮', afterClear);

console.log('');
if (problems.length) {
  console.log('✗ ' + problems.length + ' 项未通过：');
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}
try { ws.close(); } catch (e) {}
browser.kill();
process.exit(problems.length ? 1 : 0);
