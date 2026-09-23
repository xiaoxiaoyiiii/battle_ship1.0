#!/usr/bin/env node
/**
 * 对局回放端到端检查（真浏览器 + 真服务端 + 真打完一局）。
 *
 * 依据：`docs/REPLAY_2026_09_23.md` §7（前端界面）。这是回放批的**主证据**。
 *
 * 覆盖（契约 §7 逐条）：
 *   1. 真打完一局（人机局最快）→ 战绩里那一局有 `has_replay`；
 *   2. 战绩列表点开那一局 → 详情页出现「对局回放」按钮；
 *   3. 点按钮 → 进回放屏（`#replay-screen.active`）；
 *   4. **两块棋盘上真的画出了双方的船**（断言船格数量与后端 JSON 逐格一致）；
 *   5. **双方手牌可见**（卡名来自 magic_cards.js 的映射）；
 *   6. 「下一步」后棋盘按预期变化；「上一步」能回到上一帧（**与前一帧逐格相同**）；
 *   7. 进度条节点数量与后端 `nodes` 一致；
 *   8. hover 节点出 tooltip；
 *   9. 倍速按钮改变播放节奏（实测间隔，不是只看 class）；
 *  10. **拖拽 seek 到中间某一帧，画面与"连续点下一步到那一帧"完全一致**
 *      —— 这条是步进正确性的核心判据。
 *
 * 用法：
 *   node tools/replay_check.mjs --url http://127.0.0.1:5000/ [--shot out.png] [--keep]
 *
 * 被检查的服务端必须：
 *   · `CORS_ORIGINS=http://127.0.0.1:<端口>`（否则 socket.io **静默连不上**）；
 *   · `BATTLESHIP_DB_PATH` 指到隔离库（本工具注册账号、真打一局，会写数据）；
 *   · `ENABLE_TEST_EVENTS=1`（靠 `test_get_game_state` 读服务端真值，AI 房间靠它开炮）；
 *   · `TURN_TIMEOUT_SECONDS=0`（关掉思考超时兜底，免得后台任务替我们开炮）。
 *
 * ⚠️ 回放**只对上线的对局**存在（契约假设 A4：历史局无法补录）——
 *    所以本工具必须**自己打一局新对局**，不能拿老数据凑。
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/').replace(/\/+$/, '');
const SHOT = argOf('--shot', '');
const PORT = 9388;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const PROFILE_DIR = path.join(HERE, '..', '.tmp', 'replay_check_profile');
const BROWSER = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过回放检查'); process.exit(0); }

// 预清理：残留的无头进程会占着调试端口 + 锁住 profile，新浏览器**静默起不来**
// （CLAUDE.md 教训 #15：工具假红先怀疑工具）。
try {
  execSync('powershell -NoProfile -Command "' +
    'Get-CimInstance Win32_Process -Filter \\"Name=\'msedge.exe\'\\" | ' +
    'Where-Object { $_.CommandLine -like \'*replay_check_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没残留就够了 */ }

const problems = [];
const jsProblems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label
    + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

let browser = null;
let ws = null;
let seq = 0;
const pending = new Map();

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
  });
}

async function ev(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('页面异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeout) {
    try { const v = await fn(); if (v) return v; } catch (e) { last = e.message; }
    await sleep(200);
  }
  throw new Error('等待超时: ' + label + (last ? (' (' + last + ')') : ''));
}

// ---------------------------------------------------------------------------
// Node 侧账号：注册（成功时直接种好 session，省一次 /login 的限流配额）
// ⚠️ `/register` 与 `/login` 各有同 IP 60 秒 10 次限流（api.py `_rate_limited`），
//    超限的表现是"账号没登进去"（看着像 cookie 坏了）。
// ---------------------------------------------------------------------------
const SUFFIX = String(Date.now()).slice(-6);
const USERNAME = 'rplchk_' + SUFFIX;
const PW = 'check123456';

function readCookie(resp) {
  const raw = resp.headers.getSetCookie ? resp.headers.getSetCookie()
    : [resp.headers.get('set-cookie')].filter(Boolean);
  return raw.map((c) => String(c).split(';')[0]).filter(Boolean).join('; ');
}

async function nodeAuth() {
  const verify = async (cookie) => {
    if (!cookie) return '';
    try {
      const r = await fetch(APP + '/api/profile', { headers: { Accept: 'application/json', Cookie: cookie } });
      if (!r.ok) return '';
      const body = await r.json();
      const me = body && body.profile ? String(body.profile.username || '') : '';
      return me === USERNAME ? cookie : '';
    } catch (e) { return ''; }
  };
  const post = (p) => fetch(APP + p, {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: USERNAME, password: PW }).toString(),
  });
  const reg = await post('/register');
  let cookie = await verify(readCookie(reg));
  if (cookie) return cookie;
  for (let i = 0; i < 8; i++) {
    await sleep(6500);
    const a = await post('/login');
    cookie = await verify(readCookie(a));
    if (cookie) return cookie;
  }
  return '';
}

// ---------------------------------------------------------------------------
// 页面内探针（都是字符串化后送进浏览器执行的函数）
// ---------------------------------------------------------------------------
// 等 socket.io 连上，并发一次人机房
function pageStartAiRoom() {
  return new Promise(function (resolve) {
    var t0 = Date.now();
    (function tick() {
      if (window.gameState && window.gameState.socket && window.gameState.socket.connected) {
        window.gameState.playerName = window.__REPLAY_USER || 'rplchk';
        window.gameState.socket.emit('create_ai_room',
          { player_name: window.gameState.playerName, difficulty: 'easy' }, function (resp) {
            if (!resp || resp.status !== 'success') { resolve({ error: 'create_ai_room: ' + JSON.stringify(resp) }); return; }
            window.gameState.roomId = resp.room_id;
            window.gameState.socket.emit('join_room',
              { room_id: resp.room_id, player_name: window.gameState.playerName }, function (j) {
                if (!j || j.status !== 'success') { resolve({ error: 'join_room: ' + JSON.stringify(j) }); return; }
                window.gameState.playerId = j.player_id;
                resolve({ room_id: resp.room_id, player_id: j.player_id });
              });
          });
        return;
      }
      if (Date.now() - t0 > 15000) { resolve({ error: 'socket 未连上' }); return; }
      setTimeout(tick, 150);
    })();
  });
}

// 摆 6 艘单格船（棋规是 6 艘单格），然后读服务端真值。
// ⚠️ 用**固定间隔**的 6 格（棋盘格花纹）而不是随机格：随机摆放偶尔会把 6 艘挤在一起，
//    AI 几炮就打掉一大半 → 我方攻击次数掉到 3 → 永远追不上对方 6 艘（实测 30 炮 / 7 回合
//    后超时）。固定间隔摆放保证每次运行都是同一种"难度可控"的局。
function pagePlaceAndState() {
  var picks = [[0, 0], [2, 0], [4, 0], [0, 2], [2, 2], [4, 2]].map(function (c) {
    // ⚠️ 每艘船必须带 `hits`：服务端 `PlayerShip(**x)` 直接展开这个 dict，
    //    少了 hits 就是 `TypeError: missing 1 required positional argument: 'hits'`
    //    ⇒ handler 抛异常 ⇒ **连 ack 都不回** ⇒ 客户端只看到超时。
    return { positions: [{ x: c[0], y: c[1] }], hits: [] };
  });
  var gs = window.gameState;
  return new Promise(function (resolve) {
    gs.socket.emit('place_ships', { room_id: gs.roomId, player_id: gs.playerId, ships: picks },
      function (r) {
        if (!r || r.status !== 'success') { resolve({ error: 'place_ships: ' + JSON.stringify(r) }); return; }
        gs.socket.emit('test_get_game_state', { room_id: gs.roomId }, function (st) { resolve(st); });
      });
  });
}

// 猜拳：让 AI 随便出的那手被我们赢下来（直接问服务端它在等什么太绕，三手都发一遍不合法），
// 所以这里只发一手 'rock'：赢了就先手，输了就让 AI 先走（下面的循环两种都处理）。
function pageRps() {
  var gs = window.gameState;
  return new Promise(function (resolve) {
    gs.socket.emit('rps_choice', { room_id: gs.roomId, player_id: gs.playerId, choice: 'rock' },
      function (r) { resolve(r); });
  });
}

function pageState() {
  var gs = window.gameState;
  return new Promise(function (resolve) {
    gs.socket.emit('test_get_game_state', { room_id: gs.roomId }, function (st) { resolve(st); });
  });
}

function pageAttack(x, y) {
  var gs = window.gameState;
  return new Promise(function (resolve) {
    gs.socket.emit('attack', { room_id: gs.roomId, player_id: gs.playerId, x: x, y: y },
      function (r) { resolve(r); });
  });
}

function pageEndTurn() {
  var gs = window.gameState;
  return new Promise(function (resolve) {
    gs.socket.emit('end_turn', { room_id: gs.roomId, player_id: gs.playerId }, function (r) { resolve(r); });
  });
}

// 回放屏探针：把"当前帧每一格的 class"取出来，用来逐帧比对
function pageFrameSnapshot() {
  function cellsOf(id) {
    var board = document.getElementById(id);
    if (!board) return null;
    return [].slice.call(board.querySelectorAll('.cell')).map(function (c) {
      return c.dataset.x + ',' + c.dataset.y + ':' + c.className.replace(/\s+/g, ' ');
    });
  }
  var state = window.__replayProbe ? window.__replayProbe() : null;
  return {
    active: !!document.querySelector('#replay-screen.active'),
    board1: cellsOf('replay-board-1'),
    board2: cellsOf('replay-board-2'),
    stepIndex: (document.getElementById('replay-step-index') || {}).textContent,
    stepTotal: (document.getElementById('replay-step-total') || {}).textContent,
    stepKind: (document.getElementById('replay-step-kind') || {}).textContent,
    stepActor: (document.getElementById('replay-step-actor') || {}).textContent,
    playLabel: (document.getElementById('replay-play') || {}).textContent,
    prevDisabled: !!(document.getElementById('replay-prev') || {}).disabled,
    nextDisabled: !!(document.getElementById('replay-next') || {}).disabled,
    nodeCount: document.querySelectorAll('#replay-track-nodes .replay-track-node').length,
    nodeLefts: [].slice.call(document.querySelectorAll('#replay-track-nodes .replay-track-node'))
      .map(function (n) { return n.style.left; }),
    hand1: [].slice.call(document.querySelectorAll('#replay-hand-1 .replay-hand-card')).map(function (c) { return c.textContent; }),
    hand2: [].slice.call(document.querySelectorAll('#replay-hand-2 .replay-hand-card')).map(function (c) { return c.textContent; }),
    handHasButton: document.querySelectorAll('#replay-hand-1 button, #replay-hand-2 button').length,
    status: (document.getElementById('replay-status') || {}).textContent,
    k: state ? state.k : null,
    speed: state ? state.speed : null,
    playing: state ? state.playing : null,
    payloadSteps: state ? state.payloadSteps : null,
    payloadNodes: state ? state.payloadNodes : null
  };
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
try {
  fs.mkdirSync(path.join(HERE, '..', '.tmp'), { recursive: true });
  const cookie = await nodeAuth();
  if (!cookie) throw new Error('账号注册/登录失败（多半撞上 /register 的 IP 限流）');
  console.log('账号就绪: ' + USERNAME);

  browser = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || ''))
        || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还在启动 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') {
      jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setCookie', { name: 'session', value: cookie.split('=').slice(1).join('='), url: new URL(APP).origin + '/' });
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await waitFor(() => ev('document.readyState === "complete"'), 20000, '页面加载');
  await waitFor(() => ev('typeof window.gameState === "object" && !!window.gameState'), 20000, 'gameState 就绪');
  await ev('window.__REPLAY_USER = ' + JSON.stringify(USERNAME));
  const who = await ev('(function(){return document.body.innerText.indexOf(' + JSON.stringify(USERNAME) + ') >= 0;})()');
  console.log('浏览器侧登录态: ' + (who ? '已认出 ' + USERNAME : '（页面里没找到用户名，仍按 cookie 会话继续）'));

  // ---------- ① 真打完一局（人机局） ----------
  const room = await ev('(' + pageStartAiRoom.toString() + ')()');
  if (room.error) throw new Error(room.error);
  console.log('人机房: room_id=' + room.room_id + ' player_id=' + room.player_id);

  let st = await ev('(' + pagePlaceAndState.toString() + ')()');
  if (st.error) throw new Error(st.error);
  check(st.game_state && (st.game_state.state === 'rock_paper_scissors' || st.game_state.state === 'attacking'),
    '摆完船后进入猜拳（或直接开打）', st.game_state && st.game_state.state);

  // 猜拳会**平局**（1/3 概率）：平局时服务端清空选择、双方要重新出拳。
  // 所以这里必须**循环出拳直到进入 attacking**（第一版只发一手，撞上平局就卡死）。
  let rpsTries = 0;
  st = null;
  {
    const t0r = Date.now();
    while (Date.now() - t0r < 45000) {
      const rawst = await ev('(' + pageState.toString() + ')()');
      const gs0 = rawst && rawst.game_state;
      if (gs0 && gs0.state === 'attacking') { st = gs0; break; }
      if (gs0 && gs0.state === 'game_over') { st = gs0; break; }
      if (gs0 && gs0.state === 'rock_paper_scissors') {
        await ev('(' + pageRps.toString() + ')()');
        rpsTries++;
      }
      await sleep(600);
    }
  }
  check(!!st && st.state === 'attacking', '猜拳结束、进入攻击阶段（出了 ' + rpsTries + ' 手）',
    st && st.state);
  if (!st || st.state !== 'attacking') throw new Error('猜拳后一直没进入 attacking');

  // 目标：把对方的 6 艘单格船全打沉（打完就是 `game_over` + `_finalize_match`）。
  // ⚠️ 一轮只走一个阶段：`enter_battle_phase` → 打光次数 → `enter_end_phase` → `end_turn`。
  //    不走完这一串服务端不会换人（第一版就是漏了后两步，404 炮打了 150 秒都没结束）。
  let gameOver = false;
  let shots = 0;
  let turns = 0;
  let stalls = 0;
  let polls = 0;
  const triedLocal = {};
  const t0 = Date.now();
  while (!gameOver && Date.now() - t0 < 150000 && turns < 40) {
    const raw = await ev('(' + pageState.toString() + ')()');
    const s = raw && raw.game_state;
    if (!s) { await sleep(400); continue; }
    polls++;
    if (polls <= 12) {
      console.log('   [poll ' + polls + '] state=' + s.state + ' phase=' + s.current_phase
        + ' attacker=' + (s.current_attacker === room.player_id ? 'me' : 'opp')
        + ' attacks=' + s.attacks_remaining + ' myShips=' +
        ((s.players[room.player_id] || {}).remaining_ships)
        + ' oppShips=' + Object.keys(s.players).filter((k) => k !== room.player_id)
          .map((k) => (s.players[k] || {}).remaining_ships).join(','));
    }
    if (s.state === 'game_over') { gameOver = true; break; }

    const oppId = Object.keys(s.players).find((k) => k !== room.player_id);
    const opp = s.players[oppId] || {};
    const myTurn = s.current_attacker === room.player_id;

    if (!myTurn) { await sleep(500); continue; }        // 等 AI 走完

    if (s.current_phase === 'preparation') {
      await ev('(function(){var gs=window.gameState;return new Promise(function(r){' +
        'gs.socket.emit("enter_battle_phase",{room_id:gs.roomId,player_id:gs.playerId},function(x){r(x);});});})()');
      await sleep(250);
      continue;
    }
    if (s.current_phase === 'battle') {
      // ⚠️ 目标集合要**本地记住已经试过的格**：
      //    服务端拒掉的那一炮（`status:'error'`）不会出现在 `opp.attacks` 里，
      //    只看服务端状态就会反复挑同一个格子 → 打光次数却一发不出去 → **活锁**
      //    （第一版就是这样：441 炮、`attacks_remaining` 一直卡在 5）。
      const tried = {};
      (opp.attacks || []).forEach((a) => { tried[a.x + ',' + a.y] = true; });
      Object.keys(triedLocal).forEach((k) => { tried[k] = true; });
      // ⚠️ 只打**还没被击沉**的船所在的格：服务端已经告诉了我们哪艘船沉了
      //    （`hits.length >= positions.length`）。不筛的话会把次数浪费在空海上，
      //    几回合下来我方船被打光、次数变少，永远赢不了（实测 30 炮 / 7 回合 / 超时）。
      function shipAlive(sh) {
        var pos = sh.positions || [];
        var hit = {};
        (sh.hits || []).forEach(function (h) { hit[h[0] + ',' + h[1]] = true; });
        for (var i = 0; i < pos.length; i++) {
          if (!hit[pos[i][0] + ',' + pos[i][1]]) return true;
        }
        return false;
      }
      let pick = null;
      (opp.ships || []).forEach((sh) => {
        if (!shipAlive(sh)) return;
        (sh.positions || []).forEach((p) => {
          if (!pick && !tried[p[0] + ',' + p[1]]) pick = { x: p[0], y: p[1] };
        });
      });
      if (!pick) {
        for (let y = 0; y < 6 && !pick; y++) for (let x = 0; x < 6 && !pick; x++) {
          if (!tried[x + ',' + y]) pick = { x: x, y: y };
        }
      }
      if (!pick || (s.attacks_remaining || 0) <= 0) {
        // 能打的格子打光了（或次数用完）→ 进结束阶段、交回合
        await ev('(function(){var gs=window.gameState;return new Promise(function(r){' +
          'gs.socket.emit("enter_end_phase",{room_id:gs.roomId,player_id:gs.playerId},function(x){r(x);});});})()');
        await sleep(250);
        continue;
      }
      triedLocal[pick.x + ',' + pick.y] = true;
      await ev('(' + pageAttack.toString() + ')(' + pick.x + ',' + pick.y + ')');
      shots++;
      await sleep(320);
      const after = await ev('(' + pageState.toString() + ')()');
      const ga = after && after.game_state;
      if (ga && ga.state === 'game_over') { gameOver = true; break; }
      continue;
    }
    if (s.current_phase === 'end') {
      await ev('(' + pageEndTurn.toString() + ')()');
      turns++;
      await sleep(500);
      continue;
    }
    await sleep(400);
  }
  check(gameOver, '真打完一局（' + shots + ' 炮 / ' + turns + ' 次交回合 / ' +
    Math.round((Date.now() - t0) / 1000) + 's / 卡顿 ' + stalls + '）', { shots, turns, stalls });

  // ---------- ② 战绩里那一局有 has_replay ----------
  const stats = await ev('fetch("/user_stats?limit=30",{credentials:"same-origin"})' +
    '.then(function(r){return r.json();})');
  const history = (stats && stats.history) || [];
  check(history.length > 0, '战绩里出现了这一局', { rows: history.length });
  const latest = history.find((h) => h.has_replay === true) || history[0];
  check(!!latest && latest.has_replay === true,
    '★ 这一局带 has_replay=true（回放真的落库了）',
    { keys: latest ? Object.keys(latest) : null,
      has_replay: latest && latest.has_replay, mode: latest && latest.mode,
      logs: latest && (latest.logs || []).length });
  if (!latest) throw new Error('这一局没有回放，后面无法继续');
  check(latest.mode === 'ai', '★ 这一局的 mode 是 ai（任务 B 的数据源）', latest.mode);
  const matchId = latest.id || latest.match_id;
  console.log('本局 match id: ' + matchId + '（行字段: ' + Object.keys(latest).join(',') + '）');
  if (!matchId) throw new Error('战绩行里没有 match id，无法继续');

  // ---------- ③ 从战绩列表点开 → 详情页有「对局回放」按钮 ----------
  await ev('(function(){var m=document.getElementById("user-stats-modal");m.classList.remove("hidden");' +
    'document.getElementById("user-stats-content").innerHTML=' +
    'window.renderUserStatsHTML(' + JSON.stringify(stats.stats) + ',' + JSON.stringify(history) + ',{hasMore:false});})()');
  const rowInfo = await ev('(function(){' +
    'var rows=[].slice.call(document.querySelectorAll("#user-stats-content .match-history-btn"));' +
    'var first=rows[0];' +
    'return {rows:rows.length, firstText:first?first.innerText.replace(/\\s+/g," ").trim():"",' +
    ' firstClassTag:first?(first.querySelector(".hist-tag-mode")||{}).className||"":"",' +
    ' firstTagText:first?((first.querySelector(".hist-tag-mode")||{}).textContent||""):"" };})()');
  console.log('战绩首行: "' + rowInfo.firstText + '"  模式标签=' + JSON.stringify(rowInfo.firstTagText));
  check(rowInfo.firstTagText === '人机', '★ 战绩列表里这一行标出「人机」（任务 B）',
    { tag: rowInfo.firstTagText, cls: rowInfo.firstClassTag });

  // ⚠️ 光把 HTML 塞进去不够：战绩行的点击是 `bindHistoryButtons` 绑的
  //    （第一版漏了这一步 ⇒ 点了没反应、后面全红，而且**不报错**）。
  // 自己的 id：`/user_stats` 的 stats.id 就是当前登录账号的 user_id
  // （⚠️ 不能拿 `latest.winner_id` 当自己的 id：那一列在**输的局**里是对手的）。
  const MY_ID = String((stats.stats || {}).id || '');
  console.log('战绩账号 id: ' + MY_ID + ' / 本局 match id: ' + matchId);
  const bound = await ev('(function(){' +
    'try { window.__bindHistoryForCheck(' + JSON.stringify(history) + ', ' +
    JSON.stringify(MY_ID) + '); return true; }' +
    'catch (e) { return String(e && e.message); }})()');
  console.log('战绩行点击绑定: ' + JSON.stringify(bound));

  await ev('document.querySelectorAll("#user-stats-content .match-history-btn")[0].click()');
  await sleep(600);
  const detail = await ev('(function(){' +
    'var m=document.getElementById("match-detail-modal");' +
    'var b=document.getElementById("match-detail-content").querySelector(".match-replay-btn");' +
    'var tag=document.getElementById("match-detail-content").querySelector(".hist-tag-mode");' +
    'return {modalVisible:!m.classList.contains("hidden"), hasBtn:!!b, disabled:b?b.disabled:null,' +
    ' matchId:b?b.dataset.matchId:"", hint:(document.getElementById("match-detail-content").innerText||"").indexOf("这局没有可回放的行动")>=0,' +
    ' detailTag:tag?tag.textContent:"" };})()');
  check(detail.modalVisible, '点战绩行打开了详情页');
  check(detail.hasBtn, '★ 详情页出现「对局回放」按钮');
  check(detail.disabled === false, '这一局按钮可点（has_replay 为真）', detail.disabled);
  check(String(detail.matchId) === String(matchId), '按钮带正确的 data-match-id', detail.matchId);
  check(detail.detailTag === '人机', '★ 详情页也标出「人机」（任务 B 的第二个入口）', detail.detailTag);

  // 后端 JSON（与画面比对的唯一真源）
  const api = await ev('fetch("/api/replay/" + encodeURIComponent(' + JSON.stringify(String(matchId)) + '),' +
    '{credentials:"same-origin"}).then(function(r){return r.json().then(function(j){return {status:r.status,body:j};});})');
  check(api.status === 200 && api.body && api.body.success === true, 'GET /api/replay/<id> 返回 200',
    { status: api.status });
  const replay = api.body.replay;
  check(replay && replay.version === 1, '回放 version=1', replay && replay.version);
  check(Array.isArray(replay.steps) && replay.steps.length > 0, '回放有步骤',
    { steps: replay.steps.length, nodes: (replay.nodes || []).length, resets: (replay.board_resets || []).length });
  const shipsTimeline = Array.isArray(replay.ships) ? replay.ships : [];
  const firstShipsRow = shipsTimeline.find((r) => r.p1 || r.p2) || {};
  const P1_SHIPS = (firstShipsRow.p1 || []).length;
  const P2_SHIPS = (firstShipsRow.p2 || []).length;
  console.log('后端船位时间线首行: p1=' + P1_SHIPS + ' 格, p2=' + P2_SHIPS + ' 格');
  check(P1_SHIPS + P2_SHIPS === 12, '★ 后端时间线里有双方各 6 格船位', { p1: P1_SHIPS, p2: P2_SHIPS });

  // ---------- ④ 进入回放屏 ----------
  await ev('document.querySelector("#match-detail-content .match-replay-btn").click()');
  await waitFor(() => ev('!!document.querySelector("#replay-screen.active")'), 10000, '回放屏 active');
  await waitFor(async () => {
    const s = await ev('(function(){return (document.getElementById("replay-step-total")||{}).textContent;})()');
    return s && s !== '0';
  }, 15000, '回放数据加载完成');
  check(true, '★ 点「对局回放」进入回放屏 #replay-screen.active');
  // ★ 浮层必须全部关掉：回放是整屏，战绩/详情弹窗还挂着就会"进了回放却没看到回放屏"
  //   （本批就是这么被截图抓到的）。
  const overlays = await ev('(function(){' +
    'var open=[]; document.querySelectorAll(".modal-overlay").forEach(function(el){' +
    '  if(!el.classList.contains("hidden")) open.push(el.id); });' +
    'return {open:open};})()');
  check(overlays.open.length === 0, '★ 进回放屏后所有浮层都已关闭', overlays.open);

  // 把探针挂到页面里
  await ev('window.__replayProbe = function(){ return { k: replayState.k, speed: replayState.speed,' +
    ' playing: replayState.playing, payloadSteps: replayState.payload ? replayState.payload.steps.length : null,' +
    ' payloadNodes: replayState.payload ? replayState.payload.nodes.length : null }; };');

  const frame0 = await ev('(' + pageFrameSnapshot.toString() + ')()');
  check(frame0.active, '回放屏处于 active');
  check(frame0.board1 && frame0.board1.length === 36 && frame0.board2 && frame0.board2.length === 36,
    '两块棋盘各 36 格', { b1: frame0.board1 && frame0.board1.length, b2: frame0.board2 && frame0.board2.length });
  check(frame0.nodeCount === (replay.nodes || []).length,
    '★ 进度条节点数量与后端 nodes 一致',
    { ui: frame0.nodeCount, server: (replay.nodes || []).length });
  check(frame0.handHasButton === 0, '手牌是只读的（没有按钮、不可点）', frame0.handHasButton);

  // ★ 手牌必须与后端时间线**同一帧**一致。
  //   ⚠️ 第 0 帧（刚摆完船、还没猜拳）双方**本来就是空手** —— 牌是猜拳之后才发的，
  //      所以"第 0 帧看不到牌"不是 bug。真正的判据是"有条目那一帧，画面上的牌
  //      与后端最后一份手牌逐张相同"。
  await ev('(function(){ replayStepTo(replayState.payload.steps.length - 1, {}); })()');
  await sleep(300);
  const lastFrame = await ev('(' + pageFrameSnapshot.toString() + ')()');
  let lastHand = { p1: [], p2: [] };
  (replay.hands || []).forEach((row) => {
    if (Array.isArray(row.p1)) lastHand.p1 = row.p1;
    if (Array.isArray(row.p2)) lastHand.p2 = row.p2;
  });
  console.log('后端最终手牌: p1=' + JSON.stringify(lastHand.p1) + ' p2=' + JSON.stringify(lastHand.p2));
  console.log('最后一帧画面手牌: p1=' + JSON.stringify(lastFrame.hand1) + ' p2=' + JSON.stringify(lastFrame.hand2));
  check(lastHand.p1.length + lastHand.p2.length > 0, '后端时间线里这一局有手牌记录',
    { p1: lastHand.p1, p2: lastHand.p2 });
  check(lastFrame.hand1.length === lastHand.p1.length
    && lastFrame.hand2.length === lastHand.p2.length,
    '★ 双方手牌可见，张数与后端时间线一致',
    { ui: [lastFrame.hand1.length, lastFrame.hand2.length],
      server: [lastHand.p1.length, lastHand.p2.length] });
  // 卡名取自 magic_cards.js 的映射（有卡面数据时可验证名字逐字来自卡表）
  const cardNames = await ev('(window.magicCards||[]).map(function(c){return c.name;})');
  const allShown = [].concat(lastFrame.hand1, lastFrame.hand2);
  const unknown = allShown.filter((t) => !cardNames.some((n) => String(t).indexOf(n) >= 0));
  check(unknown.length === 0, '★ 画面上的卡名都来自 magic_cards.js 的卡表',
    { unknown, shown: allShown });

  // ★ 船格数量与后端 JSON 逐侧一致（"两块棋盘上真的画出了双方的船"）
  function shipCellCount(cells) {
    return (cells || []).filter((c) => /(^|\s)ship(\s|$)/.test(c.split(':')[1])).length;
  }
  // 走到最后一帧 —— 那时时间线取的是最终船位，与后端第一条（开局 6 艘）可能已不同；
  // 所以先断言"某一帧的船格总数"，再在最后一帧与后端**最终**时间线比对。
  const lastIdx = replay.steps.length - 1;
  await ev('(function(){ document.getElementById("replay-track"); replayStepTo(' + lastIdx + ',{}); })()');
  await sleep(300);
  const frameLast = await ev('(' + pageFrameSnapshot.toString() + ')()');
  let lastShips = { p1: [], p2: [] };
  shipsTimeline.forEach((row) => {
    if (row.p1) lastShips.p1 = row.p1;
    if (row.p2) lastShips.p2 = row.p2;
  });
  const drawn1 = shipCellCount(frameLast.board1);
  const drawn2 = shipCellCount(frameLast.board2);
  console.log('最后一帧船格: 画了 p1=' + drawn1 + ' p2=' + drawn2 +
    ' / 后端最终 p1=' + lastShips.p1.length + ' p2=' + lastShips.p2.length);
  check(drawn1 === lastShips.p1.length && drawn2 === lastShips.p2.length,
    '★ 两块棋盘画出的船格数与后端 JSON 一致',
    { drawn: [drawn1, drawn2], server: [lastShips.p1.length, lastShips.p2.length] });
  check(drawn1 + drawn2 === 12, '★ 双方船位都在（各 6 格，全透视）', { p1: drawn1, p2: drawn2 });

  // ---------- ⑤ 上一步 / 下一步 ----------
  await ev('(function(){ replayStepTo(0, {}); })()');
  await sleep(200);
  const atStart = await ev('(' + pageFrameSnapshot.toString() + ')()');
  check(atStart.prevDisabled === true, '第 0 帧「上一步」被禁用（k 不越界）', atStart.prevDisabled);

  // 连点 6 次下一步，记录每一帧
  const walked = [];
  for (let i = 0; i < 6; i++) {
    await ev('document.getElementById("replay-next").click()');
    await sleep(120);
    walked.push(await ev('(' + pageFrameSnapshot.toString() + ')()'));
  }
  check(walked[5].k === 6, '连点 6 次「下一步」后 k=6', walked.map((w) => w.k));
  const changed = JSON.stringify(walked[0].board2) !== JSON.stringify(walked[5].board2)
    || JSON.stringify(walked[0].board1) !== JSON.stringify(walked[5].board1);
  check(changed, '★「下一步」后棋盘按预期发生了变化');

  // 上一步必须逐格回到前一帧
  await ev('document.getElementById("replay-prev").click()');
  await sleep(200);
  const back = await ev('(' + pageFrameSnapshot.toString() + ')()');
  check(back.k === walked[4].k, '「上一步」后 k 回到 5', { now: back.k, want: walked[4].k });
  check(JSON.stringify(back.board1) === JSON.stringify(walked[4].board1)
    && JSON.stringify(back.board2) === JSON.stringify(walked[4].board2),
    '★「上一步」后的画面与前一帧**逐格相同**');

  // ---------- ⑥ 拖拽 seek == 连续点下一步（本批的核心判据） ----------
  const TARGET_K = Math.floor(lastIdx / 2);
  // 先用"连续点下一步"走到 TARGET_K（从 0 开始）
  await ev('(function(){ replayStepTo(0, {}); })()');
  await sleep(150);
  for (let i = 0; i < TARGET_K; i++) {
    await ev('document.getElementById("replay-next").click()');
    await sleep(60);
  }
  const bySteps = await ev('(' + pageFrameSnapshot.toString() + ')()');
  check(bySteps.k === TARGET_K, '连续点下一步到达目标帧', { k: bySteps.k, want: TARGET_K });

  // 再"拖拽"到同一帧：用真实的 pointer 事件点在 track 的对应比例处
  await ev('(function(){ replayStepTo(0, {}); })()');
  await sleep(150);
  const dragged = await ev('(function(){' +
    'var track=document.getElementById("replay-track");' +
    'var r=track.getBoundingClientRect();' +
    'var total=replayState.payload.steps.length;' +
    'var target=' + TARGET_K + ';' +
    'var x=r.left + (target/(total-1))*r.width;' +
    'var y=r.top + r.height/2;' +
    'function pe(type, extra){ var o={bubbles:true,cancelable:true,pointerId:1,pointerType:"mouse",clientX:x,clientY:y,isPrimary:true};' +
    '  if(extra) for(var k2 in extra) o[k2]=extra[k2]; return new PointerEvent(type,o); }' +
    'track.dispatchEvent(pe("pointerdown"));' +
    'track.dispatchEvent(pe("pointermove"));' +
    'track.dispatchEvent(pe("pointerup"));' +
    'return {k: replayState.k, playing: replayState.playing};})()');
  await sleep(300);
  const byDrag = await ev('(' + pageFrameSnapshot.toString() + ')()');
  console.log('连续点下一步到 k=' + bySteps.k + '；拖拽到 k=' + byDrag.k + '；目标 ' + TARGET_K);
  check(dragged.playing === false, '拖拽后自动暂停', dragged.playing);
  check(byDrag.k === TARGET_K, '拖拽 seek 落在目标帧', { k: byDrag.k, want: TARGET_K });
  check(JSON.stringify(byDrag.board1) === JSON.stringify(bySteps.board1)
    && JSON.stringify(byDrag.board2) === JSON.stringify(bySteps.board2),
    '★★ 拖拽 seek 到某一帧的画面与"连续点下一步到那一帧"完全一致（逐格）');

  // ---------- ⑦ hover 节点 → tooltip ----------
  const tip = await ev('(function(){' +
    'var nodes=document.querySelectorAll("#replay-track-nodes .replay-track-node");' +
    'if(!nodes.length) return {none:true};' +
    'var n=nodes[Math.min(2,nodes.length-1)];' +
    'var r=n.getBoundingClientRect();' +
    'n.dispatchEvent(new MouseEvent("mouseover",{bubbles:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}));' +
    'n.dispatchEvent(new MouseEvent("mousemove",{bubbles:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}));' +
    'var t=document.getElementById("replay-node-tip");' +
    'return {hidden:t.classList.contains("hidden"), text:t.textContent, nodeTitle:n.title, nodeStep:Number(n.dataset.step)};})()');
  console.log('节点 tooltip: ' + JSON.stringify(tip));
  check(!tip.none && tip.hidden === false && (tip.text || '').length > 0,
    '★ hover 节点弹出 tooltip（说清那一步做了什么）', tip);
  check((tip.text || '').indexOf('第 ') === 0,
    'tooltip 里带"第 N 步"与那一步的内容', tip.text);

  // 点节点 = 跳那一步
  const jumped = await ev('(function(){' +
    'var nodes=document.querySelectorAll("#replay-track-nodes .replay-track-node");' +
    'var n=nodes[0]; n.click(); return {k: replayState.k, want:Number(n.dataset.step)};})()');
  await sleep(200);
  check(jumped.k === jumped.want, '★ 点节点跳到那一步', jumped);

  // ---------- ⑧ 倍速改变播放节奏（实测间隔，不是只看 class） ----------
  async function measureSpeed(speed) {
    await ev('(function(){ replayStepTo(0, {}); replaySetSpeed(' + speed + '); })()');
    await sleep(150);
    const t = Date.now();
    const before = await ev('replayState.k');
    await ev('document.getElementById("replay-play").click()');
    // 等它至少走一步
    let after = before;
    while (after === before && Date.now() - t < 6000) {
      await sleep(50);
      after = await ev('replayState.k');
    }
    const dt = Date.now() - t;
    await ev('(function(){ if(replayState.playing) replayPause(); })()');
    return { dt, speedClass: await ev('(function(){var a=document.querySelector("#replay-speed-group .replay-speed-btn.active");return a?a.textContent:null;})()') };
  }
  const s1 = await measureSpeed(1);
  const s4 = await measureSpeed(4);
  console.log('倍速实测: 1× 首步 ' + s1.dt + 'ms / 4× 首步 ' + s4.dt + 'ms');
  check(s1.dt > 700 && s1.dt < 1600, '1× 的首步大约 900ms', s1.dt);
  check(s4.dt < s1.dt * 0.6, '★ 4× 明显更快（倍速真的改变了播放节奏）', { one: s1.dt, four: s4.dt });
  check(s4.speedClass === '4×', '倍速按钮的 active 档位跟着变', s4.speedClass);

  // ---------- ⑨ 进度条节点只来自服务端 ----------
  const nodesMatch = await ev('(function(){' +
    'var ui=document.querySelectorAll("#replay-track-nodes .replay-track-node").length;' +
    'var srv=replayState.payload.nodes.length;' +
    'var firstLeft=document.querySelector("#replay-track-nodes .replay-track-node").style.left;' +
    'return {ui:ui, srv:srv, firstLeft:firstLeft};})()');
  check(nodesMatch.ui === nodesMatch.srv, '节点数量 = 服务端 nodes 数量', nodesMatch);
  check(nodesMatch.firstLeft === '0%', '第一个节点定位在 0%（i/(n-1) 口径）', nodesMatch.firstLeft);

  // ---------- ⑩ 退出回放 ----------
  await ev('document.getElementById("replay-leave").click()');
  await sleep(400);
  const left = await ev('(function(){return {active:!!document.querySelector("#replay-screen.active"),' +
    ' start:!!document.querySelector("#start-screen.active"),' +
    ' payload:replayState.payload};})()');
  check(left.active === false && left.start === true, '★ 「退出回放」回到开始界面（不会卡在回放里）', left);
  check(left.payload === null, '退出时清掉了回放数据', left.payload);

  if (SHOT) {
    // 重新进一次屏再截图，方便人肉核对"回放屏长什么样"
    await ev('(function(){var m=document.getElementById("user-stats-modal");m.classList.remove("hidden");' +
      'document.getElementById("user-stats-content").innerHTML=window.renderUserStatsHTML(' +
      JSON.stringify(stats.stats) + ',' + JSON.stringify(history) + ',{hasMore:false});' +
      'document.querySelectorAll("#user-stats-content .match-history-btn")[0].click();})()');
    await sleep(400);
    await ev('document.querySelector("#match-detail-content .match-replay-btn").click()');
    await sleep(1200);
    await ev('(function(){ var n=replayState.payload.nodes.length; replayStepTo(Math.floor((replayState.payload.steps.length-1)*0.6), {}); })()');
    await sleep(400);
    const s = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(s.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }

  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  console.log(NL + (problems.length
    ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL)
    : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
