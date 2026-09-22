#!/usr/bin/env node
/**
 * 大厅系统端到端回归检查（无头 Edge + CDP，双浏览器）
 *
 * 依据：docs/LOBBY_2026_09_18.md（冻结契约 §1 事件 / §1.3 payload / §1.4 房间可见规则）。
 *
 * 为什么必须**两个真实浏览器**：大厅的全部价值就是"别人那边立刻能看到"。
 * 单浏览器里自己 emit / 自己断言只能测到"我把请求发出去了"，测不到
 * "服务端有没有把它广播给**别人**"—— 而本项目出过最多的正是这类故障
 * （CLAUDE.md 通用教训：工具全绿、线上全坏）。
 *
 * 覆盖 9 组：
 *   1. 入口：首页按钮 / 导航链接 → #lobby-screen 真的被激活，URL 变成 /lobby；
 *   2. 订阅握手：lobbySubscribed / lobbyKey 就位；
 *   3. **实时在线列表**：B 进大厅后 A 那边（没刷新）出现 B 那一行；
 *   4. 自己那一行带 .lobby-me，在线人数 ≥ 2；
 *   5. 公屏：A 发言 → B 的公屏出现同一条；A 自己那条带 .me；空消息不发送；
 *   6. 队列：A 快速匹配 → B 那边 A 的状态变"匹配中"、休闲队列 = 1；取消后回 0；
 *   7. 房间列表：A 用按钮建房 → B 的列表出现该房（名字/房主/1-2 座位）；
 *   8. **私密房不上榜**（A 直接 emit public:false，B 列表不变）；
 *   9. 离开大厅 ≠ 掉线：A 点返回首页后 lobbySubscribed=false，但 B 那边 A 仍在线上、
 *      房间仍挂在列表里（房主仍在线的口径）；B 点"加入"能真的进房（gameState.roomId 一致）。
 *
 * 用法：
 *   node tools/lobby_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 *
 * ⚠️ 需要一个**已经起好的**服务端。本地隔离跑法：
 *     $env:BATTLESHIP_DB_PATH="$PWD\.tmp\lobby_check.db"; python server.py
 *   然后另开一个终端跑本脚本。
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const TMP = path.join(HERE, '..', '.tmp');
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过大厅检查'); process.exit(0); }

const problems = [];
const jsProblems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// ---------------------------------------------------------------------------
// 浏览器实例
// ---------------------------------------------------------------------------
// ⚠️ 两个实例各有自己的 --user-data-dir 与调试端口：共用一个 profile 时第二个浏览器
//    **静默起不来**，工具会连上第一个实例，于是"两个玩家"其实是同一个人。
function preClean(tag) {
  try {
    execSync('powershell -NoProfile -Command "' +
      'Get-CimInstance Win32_Process -Filter \"Name=\'msedge.exe\'\" | ' +
      'Where-Object { $_.CommandLine -like \'*' + tag + '*\' } | ' +
      'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
      { stdio: 'ignore', timeout: 20000 });
  } catch (e) { /* 没有残留就够了 */ }
}

function pickPage(list) {
  const isApp = (t) => t.type === 'page' && /^(https?|file):/.test(t.url || '');
  return list.find(isApp) || list.find((t) => t.type === 'page' && t.url !== 'about:blank'
    && !/^(edge|chrome|devtools):/.test(t.url || '')) || list.find((t) => t.type === 'page');
}

async function launch(tag, port) {
  preClean(tag);
  const profile = path.join(TMP, tag);
  fs.mkdirSync(profile, { recursive: true });
  const proc = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + port,
    '--user-data-dir=' + profile, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
      target = pickPage(list);
      if (target) break;
    } catch (e) { /* still starting */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口 ' + port);

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败 ' + port)); });
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push(tag + ' JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') jsProblems.push(tag + ' console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
  };
  function send(method, params) {
    const id = ++seq;
    ws.send(JSON.stringify({ id: id, method: method, params: params || {} }));
    return new Promise((res, rej) => {
      pending.set(id, { res: res, rej: rej });
      setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
    });
  }
  async function ev(expression) {
    const r = await send('Runtime.evaluate', { expression: expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(tag + ' page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
    return r.result && r.result.value;
  }
  async function waitFor(fn, timeout, label) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      try { if (await fn()) return true; } catch (e) { /* keep polling */ }
      await sleep(200);
    }
    throw new Error('等待超时: ' + label);
  }
  return {
    tag: tag, ev: ev, send: send, waitFor: waitFor,
    // ⚠️ 收尾也要按 profile 清理：`proc.kill()` 只杀掉直接子进程，Edge 还会留下一串
    //    孙进程继续占着连接 —— 下一次跑工具时它们就是"多出来的在线玩家"，
    //    会让在线人数、房间列表等断言莫名其妙地对不上（实测踩过一次：
    //    在线人数显示 3，而工具只开了 2 个浏览器）。
    close: () => {
      try { ws.close(); } catch (e) { /* ignore */ }
      try { proc.kill(); } catch (e) { /* ignore */ }
      preClean(tag);
    },
  };
}

// ---------------------------------------------------------------------------
// 页面侧的小工具（字符串表达式，避免在工具里再套一层模板字符串）
// ---------------------------------------------------------------------------
const Q = String.fromCharCode(34);   // 双引号，拼 JSON 字面量用
function jsStr(s) { return JSON.stringify(s); }

const ENTER_LOBBY = (name) => '(function(){ var i = document.getElementById("player-name");'
  + ' if (i) i.value = ' + jsStr(name) + ';'
  + ' document.getElementById("lobby-btn").click(); return 1; })()';

const ROW_OF = (name) => '(function(){'
  + ' var rows = document.querySelectorAll("#lobby-players-list .lobby-player");'
  + ' for (var i = 0; i < rows.length; i++) {'
  + '   var n = rows[i].querySelector(".lobby-player-name");'
  + '   if (n && n.textContent.trim() === ' + jsStr(name) + ') {'
  + '     var s = rows[i].querySelector(".lobby-status");'
  + '     return { status: s ? s.textContent.trim() : "", me: rows[i].classList.contains("lobby-me") };'
  + '   }'
  + ' } return null; })()';

const ROOMS = '(function(){'
  + ' var out = [];'
  + ' document.querySelectorAll("#lobby-rooms-list .lobby-room").forEach(function(r){'
  + '   var nm = r.querySelector(".lobby-room-name");'
  + '   var hs = r.querySelector(".lobby-room-host");'
  + '   var st = r.querySelector(".lobby-room-seats");'
  + '   var jb = r.querySelector(".lobby-room-join");'
  + '   out.push({ name: nm ? nm.textContent.trim() : "", host: hs ? hs.textContent.trim() : "",'
  + '     seats: st ? st.textContent.trim() : "", roomId: jb ? (jb.dataset.room || "") : "" });'
  + ' }); return out; })()';

const CHAT_TEXTS = '(function(){'
  + ' var out = [];'
  + ' document.querySelectorAll("#lobby-chat-messages .lobby-chat-item").forEach(function(c){'
  + '   var t = c.querySelector(".lobby-chat-text");'
  + '   out.push({ text: t ? t.textContent : "", me: c.classList.contains("me"), key: c.dataset.key || "" });'
  + ' }); return out; })()';

const TYPE_AND_SEND_CHAT = (text) => '(function(){'
  + ' var i = document.getElementById("lobby-chat-input");'
  + ' i.value = ' + jsStr(text) + ';'
  + ' document.getElementById("lobby-chat-send").click(); return 1; })()';

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
let A = null, B = null;
try {
  A = await launch('lobby_check_a_profile', 9360);
  B = await launch('lobby_check_b_profile', 9361);
  for (const br of [A, B]) {
    await br.send('Page.enable');
    await br.send('Runtime.enable');
    await br.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await br.send('Page.navigate', { url: APP });
    await br.waitFor(async () => await br.ev('document.readyState === "complete"'), 20000, '页面加载 ' + br.tag);
  }

  // --- 1. 入口 -------------------------------------------------------------
  const navOk = await A.ev('(function(){ return !!document.querySelector(\'a[href="/lobby"]\'); })()');
  check(navOk === true, '导航栏里有指向 /lobby 的入口');
  const startBtnOk = await A.ev('!!document.getElementById("lobby-btn")');
  check(startBtnOk === true, '首页有「游戏大厅」按钮');

  await A.ev(ENTER_LOBBY('甲'));
  await A.waitFor(async () => await A.ev('document.getElementById("lobby-screen").classList.contains("active")'), 10000, 'A 进入大厅');
  const aPath = await A.ev('window.location.pathname');
  check(aPath === '/lobby', '进入大厅后 URL 变成 /lobby（SPA 路由）', aPath);

  // --- 2. 订阅握手 ---------------------------------------------------------
  await A.waitFor(async () => await A.ev('gameState.lobbySubscribed === true && !!gameState.lobbyKey'), 10000, 'A 订阅握手');
  check(true, 'A 完成订阅握手（lobbySubscribed / lobbyKey）');

  await B.ev(ENTER_LOBBY('乙'));
  await B.waitFor(async () => await B.ev('gameState.lobbySubscribed === true && !!gameState.lobbyKey'), 10000, 'B 订阅握手');

  // --- 3. 实时在线列表（A 那边没有刷新） ------------------------------------
  await A.waitFor(async () => (await A.ev(ROW_OF('乙'))) !== null, 15000, 'A 的列表里出现 B');
  check(true, 'B 进大厅后，A 的在线列表**实时**出现 B（没刷新页面）');

  // --- 4. 自己高亮 + 人数 ---------------------------------------------------
  const aRow = await A.ev(ROW_OF('甲'));
  const bRow = await B.ev(ROW_OF('乙'));
  check(!!aRow && aRow.me === true, 'A 自己那一行带 .lobby-me', aRow);
  check(!!bRow && bRow.me === true, 'B 自己那一行带 .lobby-me', bRow);
  const countText = await A.ev('document.getElementById("lobby-player-count").textContent.trim()');
  check(Number(countText) >= 2, '在线人数 ≥ 2', countText);

  // --- 5. 公屏 --------------------------------------------------------------
  await A.ev(TYPE_AND_SEND_CHAT('大厅公屏测试'));
  await B.waitFor(async () => {
    const list = await B.ev(CHAT_TEXTS);
    return Array.isArray(list) && list.some((m) => m.text === '大厅公屏测试');
  }, 15000, 'B 收到公屏消息');
  check(true, 'A 发言后 B 的公屏出现同一条（真实广播）');
  const aChat = await A.ev(CHAT_TEXTS);
  const aKey = await A.ev('gameState.lobbyKey');
  check(aChat.some((m) => m.text === '大厅公屏测试' && m.me === true),
    'A 自己那条标成 .me', { lobbyKey: aKey, chat: aChat });

  // ★ 回归：重新订阅补发历史**不许**冲掉已经上屏的实时消息。
  //   第一版这里走的是"清空重铺"，实测把自己刚发的那条整段冲没了
  //   （A 自己看不到、B 看得到）。合并（按 seq 只补缺的）之后才正确。
  await A.ev('gameState.socket.emit("lobby_subscribe", { player_name: "甲" }, function(){}); 1');
  await sleep(1200);
  const afterResub = await A.ev(CHAT_TEXTS);
  check(afterResub.some((m) => m.text === '大厅公屏测试' && m.me === true),
    '重新订阅补发历史不会冲掉已上屏的实时消息', afterResub);

  // 空消息：发送按钮点了什么都不该发生
  const beforeEmpty = (await B.ev(CHAT_TEXTS)).length;
  await A.ev(TYPE_AND_SEND_CHAT('   '));
  await sleep(800);
  const afterEmpty = (await B.ev(CHAT_TEXTS)).length;
  check(afterEmpty === beforeEmpty, '空白消息不会发出去', { before: beforeEmpty, after: afterEmpty });

  // --- 6. 队列状态 ----------------------------------------------------------
  await A.ev('document.getElementById("join-lobby-match").click()');
  await B.waitFor(async () => {
    const row = await B.ev(ROW_OF('甲'));
    return !!row && row.status === '匹配中';
  }, 15000, 'B 看到 A 变成匹配中');
  const q1 = await B.ev('document.getElementById("lobby-queue-casual").textContent.trim()');
  check(q1 === '1', 'B 那边休闲队列 = 1', q1);
  const leaveVisible = await A.ev('!document.getElementById("leave-lobby-match").classList.contains("hidden")');
  check(leaveVisible === true, 'A 入队后按钮切成「取消匹配」');

  await A.ev('document.getElementById("leave-lobby-match").click()');
  await B.waitFor(async () => await B.ev('document.getElementById("lobby-queue-casual").textContent.trim() === "0"'), 15000, '队列回到 0');
  check(true, '取消匹配后队列回到 0（B 那边同步）');

  // --- 7. 私密房不上榜（先做，因为它会被下一节建房回收掉）-------------------
  await A.ev('gameState.socket.emit("lobby_create_room", { name: "私密房", public: false }, function(){}); 1');
  await sleep(1500);
  const roomsAfterPrivate = await B.ev(ROOMS);
  check(roomsAfterPrivate.every((r) => r.name !== '私密房'),
    '私密房不出现在别人的大厅列表里', roomsAfterPrivate);

  // --- 8. 公开房 ------------------------------------------------------------
  await A.ev('(function(){ var i = document.getElementById("lobby-room-name"); i.value = "测试房";'
    + ' var p = document.getElementById("lobby-room-public"); p.checked = true;'
    + ' document.getElementById("lobby-create-room").click(); return 1; })()');
  await A.waitFor(async () => await A.ev('!!document.getElementById("custom-current-room-id").textContent.trim()'), 20000, 'A 建房完成');
  const roomId = await A.ev('document.getElementById("custom-current-room-id").textContent.trim()');
  check(!!roomId, '从大厅建房后拿到房间号', roomId);

  await B.waitFor(async () => {
    const rooms = await B.ev(ROOMS);
    return Array.isArray(rooms) && rooms.some((r) => r.name === '测试房');
  }, 15000, 'B 的列表出现测试房');
  const roomsB = await B.ev(ROOMS);
  const target = roomsB.find((r) => r.name === '测试房');
  check(!!target && target.host.indexOf('甲') >= 0, '房间行显示房主', target);
  check(!!target && target.seats === '1/2', '房间行显示座位 1/2', target);

  // --- 9. ★ 重复建房只留一间（2026-09-18 实测缺陷的回归）--------------------
  // 缺陷原貌：作者截图里大厅挂着 **7 间一模一样的房**。复现确认「一次点击 = 一间房」，
  // 不是双击/重复绑定 —— 是旧房永不回收（等待房 TTL 1 小时 + 房主一直在线）。
  // 修法：一个玩家同时只能主持一间等待房，再次建房先回收旧的。
  const backToLobby = '(function(){ history.pushState({}, "", "/"); switchScreen(startScreen); return 1; })()';
  for (let i = 0; i < 2; i++) {
    await A.ev(backToLobby);
    await A.ev(ENTER_LOBBY('甲'));
    await A.waitFor(async () => await A.ev('gameState.lobbySubscribed === true'), 10000, 'A 回到大厅');
    await A.ev('(function(){ var i = document.getElementById("lobby-room-name"); i.value = "重复房";'
      + ' var p = document.getElementById("lobby-room-public"); p.checked = true;'
      + ' document.getElementById("lobby-create-room").click(); return 1; })()');
    await A.waitFor(async () => await A.ev('!!document.getElementById("custom-current-room-id").textContent.trim()'), 20000, 'A 再次建房');
  }
  await sleep(1200);
  const roomsAfterRepeat = await B.ev(ROOMS);
  check(roomsAfterRepeat.length === 1,
    '★ 连点建房后大厅里仍只有 1 间（不堆同名房）', roomsAfterRepeat);
  check(roomsAfterRepeat.every((r) => r.name === '重复房'),
    '留下的应当是最后建的那一间', roomsAfterRepeat);

  // --- 10. ★ 解散房间 --------------------------------------------------------
  await A.ev('document.getElementById("custom-close-room").click()');
  await B.waitFor(async () => (await B.ev(ROOMS)).length === 0, 15000, 'B 的列表变空');
  check(true, '★ 房主「解散房间」后，别人的列表里立刻消失');
  const closedHidden = await A.ev('document.getElementById("custom-room-info").classList.contains("hidden")');
  check(closedHidden === true, '解散后房主那边也收起了房间信息块');

  // --- 11. 离开大厅 ≠ 掉线 --------------------------------------------------
  // A 用直接 emit 再开一间（点按钮会跳屏，这里要让 A 留在大厅上做退订断言）
  await A.ev(backToLobby);
  await A.ev(ENTER_LOBBY('甲'));
  await A.waitFor(async () => await A.ev('gameState.lobbySubscribed === true'), 10000, 'A 回到大厅');
  await A.ev('gameState.socket.emit("lobby_create_room", { name: "测试房", public: true }, function(){}); 1');
  await sleep(1500);
  await A.ev('document.getElementById("back-to-main-from-lobby").click()');
  await A.waitFor(async () => await A.ev('gameState.lobbySubscribed === false'), 10000, 'A 退订');
  check(true, 'A 返回首页后 lobbySubscribed=false（真的退订了）');
  await sleep(800);
  const stillThere = await B.ev(ROW_OF('甲'));
  check(!!stillThere, 'A 离开大厅后**仍显示在线**（离开大厅 ≠ 掉线）', stillThere);
  const roomsStill = await B.ev(ROOMS);
  check(roomsStill.some((r) => r.name === '测试房'), '房主仍在线，房间仍挂在列表里', roomsStill);
  // ⚠️ 房间号要**现取**：上面第 9 节把 A 的旧房回收过，早先捕获的 roomId 已经失效
  //    （第一版就是拿旧 id 去比，报了个"B 从大厅进入房间"的假红）。
  const joinRoomId = (roomsStill.find((r) => r.name === '测试房') || {}).roomId;
  check(!!joinRoomId, '房间行带得出房间号（加入按钮的 data-room）', joinRoomId);

  await B.ev('(function(){ var rows = document.querySelectorAll("#lobby-rooms-list .lobby-room");'
    + ' for (var i = 0; i < rows.length; i++) {'
    + '   var n = rows[i].querySelector(".lobby-room-name");'
    + '   if (n && n.textContent.trim() === "测试房") { rows[i].querySelector(".lobby-room-join").click(); return 1; }'
    + ' } return 0; })()');
  await B.waitFor(async () => await B.ev('gameState.roomId === ' + jsStr(joinRoomId)), 20000, 'B 从大厅进入房间');
  check(true, 'B 点「加入」真的进了这个房（gameState.roomId 一致）', joinRoomId);

  // --- 布局 -----------------------------------------------------------------
  const layout = await B.ev('(function(){'
    + ' var c = document.querySelector("#lobby-screen .lobby-columns");'
    + ' var panels = document.querySelectorAll("#lobby-screen .lobby-panel");'
    // ⚠️ 不能按空格 split：computed 值是 "minmax(0px, 1fr) minmax(0px, 1fr) …"，
    //    每条轨道内部就有一个空格（实测 3 列会被数成 6 列）。数 fr 才准。
    + ' return { cols: c ? (getComputedStyle(c).gridTemplateColumns.match(/fr/g) || []).length : 0,'
    + '   panels: panels.length,'
    + '   overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth }; })()');
  check(layout.cols === 3, '宽屏下大厅是三列', layout);
  // 观战第 3 批加了第 4 块面板「进行中的对局」（**在看板里，不在看板数里**：
  // 它复用同一个 .lobby-panel 类，所以列数仍是 3、面板数变成 4）。
  check(layout.panels === 4, '四块面板都在 DOM 里（含「进行中的对局」）', layout);
  check(layout.overflow <= 2, '大厅页没有水平溢出', layout);

  if (SHOT) {
    const s = await B.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(s.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }
  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  if (A) A.close();
  if (B) B.close();
  console.log(String.fromCharCode(10) + (problems.length
    ? '结果: ' + problems.length + ' 项不通过' + String.fromCharCode(10) + problems.map((p) => '  - ' + p).join(String.fromCharCode(10))
    : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
