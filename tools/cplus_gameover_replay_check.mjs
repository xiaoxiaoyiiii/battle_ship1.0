#!/usr/bin/env node
/**
 * 结算屏「本局回放」入口的定向检查（W5）
 *
 * 任务书 §W5 对这条入口的要求是**可验证的两半**：
 *   ① 「先追踪 … payload 的真实 match id」—— 必须端到端证明**本局的 id 真的到了前端**，
 *      而且点开回放屏加载的**就是这一局**（不是"历史第一条"）。
 *   ② 「缺少权威标识时 …」—— 没有 id 时必须**隐藏入口**，
 *      而不是显示一个点了没反应的按钮、更不许去猜一局。
 *
 * 所以本工具分两段：
 *   A. **真链路**（起两个真客户端打一局到结算）：从 `game_over` 里取 `match_id`，
 *      用它打 `GET /api/replay/<id>`，断言 200 且**步骤数 > 0**；
 *      并断言 `#over-replay-btn` 可见、点击后进回放屏且加载的是同一个 id。
 *      —— 这一段同时验证了"记录已可读取与权限"这条前置条件。
 *   B. **负例**（不依赖对局）：喂一个不带 `match_id` 的载荷，
 *      断言入口隐藏、`gameOverMatchId` 为空、点它什么都不会发生（不会去猜一局）。
 *
 * 用法：node tools/cplus_gameover_replay_check.mjs --url http://127.0.0.1:5097/
 * 退出码：0 全过；1 有 FAIL；2 SKIP（没有浏览器）。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..');
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT_A = Number(argOf('--port-a', '9385'));
const PORT_B = Number(argOf('--port-b', '9386'));
const SHOTS = argOf('--shots', '');
const KNOWN_BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const EDGE = KNOWN_BROWSERS.find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

if (!EDGE) {
  console.log('SKIP  没有找到可用的 Edge/Chrome —— 这**不是**通过，是未验收。');
  process.exit(2);
}
const PROF_A = path.join(REPO, '.tmp', 'cplus-goreplay', 'a');
const PROF_B = path.join(REPO, '.tmp', 'cplus-goreplay', 'b');
fs.mkdirSync(PROF_A, { recursive: true });
fs.mkdirSync(PROF_B, { recursive: true });
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

/* ---------- 一个最小的 CDP 客户端（本工具要两个浏览器） ---------- */
async function openBrowser(port, profile) {
  const proc = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + port,
    '--user-data-dir=' + profile, '--window-size=1500,1000', 'about:blank'], { stdio: 'ignore' });
  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还没起来 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接调试端口 ' + port);
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  let seq = 0;
  const pending = new Map();
  const jsProblems = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push(JSON.stringify(m.params.exceptionDetails).slice(0, 160));
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const id = ++seq; pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
  });
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 400) };
    return r.result && r.result.value;
  };
  const waitFor = async (fn, ms) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(200); }
    return false;
  };
  return { proc, ws, send, ev, waitFor, jsProblems, tag: 'B' + port };
}

console.log('== 结算屏「本局回放」入口定向检查（W5）==');
console.log('   目标 ' + APP);

const A = await openBrowser(PORT_A, PROF_A);
const B = await openBrowser(PORT_B, PROF_B);
const browsers = [A, B];

try {
  /* ================= 段 B：负例（先做，不需要对局） ================= */
  console.log('');
  console.log('-- 负例：载荷里没有 match_id 时必须隐藏入口 --');
  for (const br of browsers) {
    await br.send('Page.enable');
    await br.send('Runtime.enable');
    await br.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await br.send('Page.navigate', { url: APP });
    await br.waitFor(async () => await br.ev('document.readyState === "complete" && typeof window.gameState === "object"'), 25000);
    await sleep(500);
  }

  const neg = await A.ev(`(function(){
    // 先给一个**有** id 的载荷，确认入口能出现（否则"隐藏"这条断言可能恒真）
    rememberGameOverMatchId({ winner: 'x', match_id: 'FAKE-ID-1234' });
    var withId = { hidden: document.getElementById('over-replay-btn').classList.contains('hidden'),
                   id: gameOverMatchId };
    // 再喂一个**没有** id 的（正常结束之外的所有路径都是这个形状）
    rememberGameOverMatchId({ winner: 'x', reason: 'surrender' });
    var withoutId = { hidden: document.getElementById('over-replay-btn').classList.contains('hidden'),
                      id: gameOverMatchId };
    return { withId: withId, withoutId: withoutId };
  })()`);
  check(neg && neg.withId && neg.withId.hidden === false && neg.withId.id === 'FAKE-ID-1234',
    'B1 有 match_id 时入口**出现**（说明下一条的"隐藏"不是恒真）', neg && neg.withId);
  check(neg && neg.withoutId && neg.withoutId.hidden === true && neg.withoutId.id === '',
    'B2 没有 match_id 时入口**隐藏**且内部 id 被清空（不猜一局）', neg && neg.withoutId);

  const noClick = await A.ev(`(function(){
    // 隐藏状态下点它（脚本点击能绕过 pointer-events）：必须什么都不发生
    var before = { active: document.querySelectorAll('.screen.active').length };
    openGameOverReplay();
    var after = { active: document.querySelectorAll('.screen.active').length,
                  replayActive: document.getElementById('replay-screen').classList.contains('active') };
    return { before: before, after: after };
  })()`);
  check(noClick && noClick.after.replayActive === false,
    'B3 没有 id 时点入口不会进回放屏（不会拿别的一局来凑）', noClick);

  /* ================= 段 A：真链路 ================= */
  console.log('');
  console.log('-- 真链路：两个真客户端打一局到结算 --');
  const me = 'gorep' + String(Date.now() % 1000000);
  const pw = 'cplusgorep123456';
  const auth = `(async function () {
    var post = function (url) {
      return fetch(url, { method: 'POST', redirect: 'follow',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username: ${JSON.stringify(me)}, password: ${JSON.stringify(pw)} }).toString() });
    };
    var r1 = await post('/login'); var t1 = await r1.text();
    if (t1.indexOf('登录成功') >= 0) return 'login-ok';
    var r2 = await post('/register'); var t2 = await r2.text();
    if (t2.indexOf('注册成功') >= 0) return 'register-ok';
    return 'auth-failed: ' + t2.replace(/\\s+/g, ' ').slice(0, 100);
  })()`;
  await A.send('Page.navigate', { url: APP });
  await A.waitFor(async () => await A.ev('document.readyState === "complete"'), 25000);
  // 记录服务端**真正发出来的** game_over 载荷（只挂监听，不改产品代码）
  await A.ev(`(function(){
    window.__lastGameOverPayload = null;
    if (window.gameState && gameState.socket) {
      gameState.socket.on('game_over', function(d){ window.__lastGameOverPayload = d; });
    } else {
      var t = setInterval(function(){
        if (window.gameState && gameState.socket) { clearInterval(t);
          gameState.socket.on('game_over', function(d){ window.__lastGameOverPayload = d; }); }
      }, 100);
    }
    return 1; })()`);
  const authRes = await A.ev(auth);
  check(typeof authRes === 'string' && /-ok$/.test(authRes), 'A1 A 侧真实登录（回放鉴权要真账号）', authRes);
  /* ⚠️ 登录后**必须重新加载页面**再建房（2026-09-29 踩过）：
     Flask-SocketIO 在 `connect` 那一刻把会话复制给这条连接，而页面在登录**之前**
     就已经连过 socket 了 ⇒ 之后所有 socket handler 里 `session.get('user_id')` 都是空的，
     服务端把 A 当成游客（`player_id` = socket sid），于是：
       · 房间 seats 里 A 没有账号身份；
       · `_finalize_match` 里 `winner_user_id` 为 None ⇒ **不写 matches 行**（更不留回放）；
       · `game_over` 载荷自然也没有 match_id ⇒ 「本局回放」入口消失。
     症状看着像"入口功能没实现"，其实是**测试自己没在登录态下建连接**。
     刷新一次让 socket 带着已登录的会话重连即可。 */
  await A.send('Page.navigate', { url: APP });
  await A.waitFor(async () => await A.ev('document.readyState === "complete" && typeof window.gameState === "object"'), 25000);
  await sleep(600);
  const whoA = await A.ev('window.__USERNAME || null');
  check(whoA === me, 'A1b 刷新后页面认得登录身份（socket 会带着已登录会话重连）', { got: whoA, want: me });

  // B 侧：游客入座（join_room 允许游客），用房间码加入
  const room = await A.ev(`(function(){
    return new Promise(function(res){
      var s = ensureSocket();
      s.emit('create_room', {}, function(r){
        if (!r || r.status !== 'success') return res({ error: r });
        var rid = r.room_id;
        s.emit('join_room', { room_id: rid }, function(j){
          res({ room_id: rid, join: j && j.status });
        });
      });
    });
  })()`);
  check(room && room.room_id && room.join === 'success', 'A2 A 建房并入座（拿到真实房号）', room);
  if (!room || !room.room_id) throw new Error('建房失败，后面的真链路无法继续');

  await B.send('Page.navigate', { url: APP });
  await B.waitFor(async () => await B.ev('document.readyState === "complete" && typeof window.gameState === "object"'), 25000);
  await sleep(400);
  const joined = await B.ev(`(function(){
    return new Promise(function(res){
      var s = ensureSocket();
      s.emit('join_room', { room_id: ${JSON.stringify(room.room_id)}, player_name: '回放对手' }, function(j){
        res({ status: j && j.status, message: j && j.message });
      });
    });
  })()`);
  check(joined && joined.status === 'success', 'A3 B 用真实房号加入（双方就座）', joined);

  // 双方摆船 → 猜拳 → A 投降 → 真结算
  const placeAndConfirm = `(function(){
    return new Promise(function(res){
      var cells = [].slice.call(document.querySelectorAll('#player-board .cell'));
      for (var i = 0; i < 6 && i < cells.length; i++) cells[i].click();
      var b = document.getElementById('confirm-ships');
      if (b && b.disabled) return res({ error: 'confirm disabled', placed: gameState.placedShips });
      b.click();
      setTimeout(function(){ res({ placed: gameState.placedShips }); }, 800);
    });
  })()`;
  await A.waitFor(async () => await A.ev('document.getElementById("ship-placement-screen").classList.contains("active")'), 20000);
  await B.waitFor(async () => await B.ev('document.getElementById("ship-placement-screen").classList.contains("active")'), 20000);
  const pA = await A.ev(placeAndConfirm);
  const pB = await B.ev(placeAndConfirm);
  check(pA && pA.placed === 6, 'A4 A 摆满 6 格并提交', pA);
  check(pB && pB.placed === 6, 'A5 B 摆满 6 格并提交', pB);

  const rpsOk = await A.waitFor(async () => await A.ev('document.getElementById("rps-screen").classList.contains("active")'), 25000);
  check(rpsOk === true, 'A6 双方就绪后进入猜拳（服务端确认双方都摆好了）');
  // 猜拳：A 出 rock、B 出 scissors（确定性，避免平局拖时间）
  await A.ev('(function(){ document.querySelector("#rps-screen [data-choice=\\"rock\\"]").click(); return 1; })()');
  await B.ev('(function(){ document.querySelector("#rps-screen [data-choice=\\"scissors\\"]").click(); return 1; })()');
  const inGame = await A.waitFor(async () => await A.ev('document.getElementById("game-screen").classList.contains("active")'), 25000);
  check(inGame === true, 'A7 猜拳后进入对局屏');

  // A 投降 → 真结算（走 handle_surrender → _finalize_match → game_over）
  const over = await A.ev(`(function(){
    return new Promise(function(res){
      var s = ensureSocket();
      s.emit('surrender', { room_id: gameState.roomId, player_id: gameState.playerId }, function(r){
        res(r);
      });
    });
  })()`);
  void over;
  const overShown = await A.waitFor(async () => await A.ev('document.getElementById("game-over-screen").classList.contains("active")'), 25000);
  check(overShown === true, 'A8 A 投降后进入结算屏（真实结束路径）');

  /* ---- 关键断言：结算屏上的入口 + 权威 id ---- */
  const entry = await A.ev(`(function(){
    var btn = document.getElementById('over-replay-btn');
    return { gotPayload: (window.__lastGameOverPayload || null),
             id: (typeof gameOverMatchId !== 'undefined') ? gameOverMatchId : null,
             hidden: btn ? btn.classList.contains('hidden') : null,
             disabled: btn ? btn.disabled : null,
             label: btn ? btn.textContent.trim() : null };
  })()`);
  check(!!entry && !!entry.id, 'A9 结算屏拿到了**本局的**权威 match_id（不是猜的）', entry);
  check(entry && entry.hidden === false && entry.disabled === false,
    'A10 「本局回放」入口可见且可点', entry);

  /* ---- 这个 id 真的能读出回放吗（任务书要求"确认记录已可读取与权限"）---- */
  const readable = await A.ev(`fetch('/api/replay/' + encodeURIComponent(gameOverMatchId || ''), {credentials:'same-origin'})
    .then(function(r){ return r.json().then(function(j){
      return { status: r.status, ok: r.ok, success: j && j.success,
               steps: (j && j.replay && j.replay.steps) ? j.replay.steps.length : null,
               you_are: j && j.you_are }; }); })`);
  check(readable && readable.ok === true && readable.success === true,
    'A11 用这个 id 打 /api/replay 拿到成功响应（记录可读取 + 权限通过）', readable);
  check(readable && typeof readable.steps === 'number' && readable.steps > 0,
    'A12 这份回放**有内容**（步骤数 > 0，不是空壳）', readable && { steps: readable.steps });

  /* ---- 点入口：进回放屏，且加载的确实是这一局 ---- */
  const clicked = await A.ev(`(function(){
    document.getElementById('over-replay-btn').click();
    return true;
  })()`);
  void clicked;
  const replayShown = await A.waitFor(async () => await A.ev('document.getElementById("replay-screen").classList.contains("active")'), 20000);
  check(replayShown === true, 'A13 点「本局回放」真的进了回放屏（不是死按钮）');
  /* ⚠️ 必须等**数据真的到了**再断言（2026-09-29 踩过）：
     进屏那一刻状态还是「正在加载回放…」、`#replay-step-total` 还是 0 ——
     这是"屏已开、fetch 还在飞"的正常中间态，不是失败。
     直接读会得到 total=0 的**假红**（第一版就是这么红的）。判据是"步骤数 > 0"。 */
  const loaded = await A.waitFor(async () => {
    const n = await A.ev('Number((document.getElementById("replay-step-total")||{}).textContent || 0)');
    return n > 0;
  }, 20000);
  check(loaded === true, 'A13b 回放数据真的加载完成（步骤数变成 > 0）');
  const inReplay = await A.ev(`(function(){
    return { players: (document.getElementById('replay-players-title') || {}).textContent || '',
             total: (document.getElementById('replay-step-total') || {}).textContent || '',
             status: (document.getElementById('replay-status') || {}).textContent || '',
             err: (document.getElementById('replay-status') || {}).className || '' };
  })()`);
  check(inReplay && Number(inReplay.total) > 0,
    'A14 回放屏加载出了**步骤**（确实是这一局的内容，不是空/失败态）', inReplay);
  check(inReplay && !/replay-error/.test(inReplay.err || ''),
    'A15 回放加载没有报错（权限/损坏都会走 error 样式）', inReplay);

  if (SHOTS) {
    const shot = await A.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOTS, 'gameover-replay.png'), Buffer.from(shot.data, 'base64'));
  }

  const jsBad = [...A.jsProblems, ...B.jsProblems];
  check(jsBad.length === 0, '全程零 JS 异常', jsBad.slice(0, 4));
  console.log('');
  if (problems.length) {
    console.log('✗ ' + problems.length + ' 项未通过：');
    problems.slice(0, 30).forEach((p) => console.log('   · ' + p));
    process.exitCode = 1;
  } else {
    console.log('✓ 全部通过');
  }
} finally {
  for (const br of browsers) {
    try { br.ws.close(); } catch (e) { /* 已断 */ }
    try { br.proc.kill(); } catch (e) { /* 已经退了 */ }
  }
}
process.exit(process.exitCode || 0);
