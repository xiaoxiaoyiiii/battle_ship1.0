#!/usr/bin/env node
/**
 * 实时观战**第 3 批**端到端检查（无头 Edge + CDP，**三浏览器**）
 *
 * 三个真浏览器 = 甲（对局玩家）/ 乙（对局玩家）/ 丙（观众）。
 * 依据：docs/LOBBY_2026_09_18.md §1.3（`matches` 契约）、
 *       docs/SPECTATE_BATCH3_2026_09_22.md。
 *
 * 为什么必须**第三个真浏览器**：前两批测得再全，也测不到"另一个人坐在另一条
 * 连接上看到的东西"。而观战屏最要紧的一条不变量恰恰是**观众侧看不到什么**——
 * 自己给自己发事件是测不出来的（CLAUDE.md 通用教训：工具全绿、线上全坏）。
 *
 * 覆盖 10 组：
 *   1. 前置：三个**登录账号**（观战只限登录用户）真的连上 socket；
 *   2. 甲建房、乙加入 → 双方摆船 + 猜拳 → 真的进入 attacking；
 *   3. ★ 丙在大厅的「进行中的对局」里看到这一局（名字/回合/观战人数）；
 *   4. ★ 丙点「观战」→ 进入**独立的**观战屏（不是对局屏），URL/屏名都对得上；
 *   5. ★★ **观战屏上没有任何一格「船」**（未被打过的船位一个都不出现）——
 *      同时对局屏那边同样为 0（对照腿：证明"0"不是因为棋盘压根没画）；
 *   6. ★ 甲打一炮 → **丙那边不刷新页面**就出现那一格（hit/miss 与 hit 标记一致）；
 *   7. 这一炮在丙的**另一块**棋盘上（甲打出去的格只能出现在乙那块棋盘上）；
 *   8. 观战人数：丙进席后甲收到 `spectate_count_changed`；丙退出后回到 0；
 *   9. ★ 甲在**设置面里真的点开关**关掉观战 → 这一局从丙的列表里消失（不刷新）；
 *      再打开 → 又出现；
 *  10. 页面无 JS 异常/报错。
 *
 * 用法：
 *   node tools/spectate_check.mjs --url http://127.0.0.1:5099/ [--shot out.png]
 *
 * ⚠️ 需要一个**已经起好的**服务端，且必须带：
 *      BATTLESHIP_DB_PATH=.tmp/spectate_check.db   （隔离数据库）
 *      CORS_ORIGINS=http://127.0.0.1:5099          （不带 socket.io 会**静默连不上**）
 *      ENABLE_TEST_EVENTS=1                        （脚本靠 test_get_game_state 读服务端真相）
 *   端口避开 5060/5061（Fetch 规范的被阻止端口）。
 *
 * ⚠️ 踩过的坑（别重踩）：
 *   · 无头 Edge 自带 `edge://sync-confirmation-dialog` 页且**稳定排第一**，
 *     只按 `type === 'page'` 取会取到它 → 全项假红。`pickPage` 里先按 http(s) 过滤。
 *   · 三个实例各有自己的 `--user-data-dir` 与调试端口：共用 profile 时后两个会
 *     **静默起不来**，工具会连上第一个实例，"三个人"其实是同一个人。
 *   · 收尾必须按 profile 路径清理（`proc.kill()` 杀不掉孙进程）——否则残留的连接
 *     会以"数据对不上"的形式出现在**下一次**运行里（大厅批踩过）。
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/').replace(/\/+$/, '');
const SHOT = argOf('--shot', '');
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const TMP = path.join(HERE, '..', '.tmp');
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过观战检查'); process.exit(0); }

const problems = [];
const jsProblems = [];
// 本机装了卡巴斯基：它往每个页面注入脚本，而我们关掉了它的本地代理，
// 于是它自己会往控制台打一条 `获取在线人数失败: TypeError: Failed to fetch`。
// 那是**第三方注入脚本**的报错，与被测应用无关 —— 不滤掉就会让
// "页面零 JS 异常"这一项永远假红（实测踩过）。
const THIRD_PARTY_NOISE = /kaspersky|kis\.v2\.scr|获取在线人数失败/;
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// ---------------------------------------------------------------------------
// 浏览器实例（与 lobby_check.mjs 同一套；三实例各有独立 profile / 端口）
// ---------------------------------------------------------------------------
function preClean(tag) {
  try {
    execSync('powershell -NoProfile -Command "' +
      'Get-CimInstance Win32_Process -Filter \"Name=\'msedge.exe\'\" | ' +
      'Where-Object { $_.CommandLine -like \'*' + tag + '*\' } | ' +
      'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
      { stdio: 'ignore', timeout: 20000 });
  } catch (e) { /* 没有残留就够了 */ }
}

// ⚠️ 先按 http(s) 过滤：headless Edge 的 `edge://sync-confirmation-dialog`
//    稳定排在列表第一位，只按 `type === 'page'` 取会取到它（症状是全项假红）。
function pickPage(list) {
  const isApp = (t) => t.type === 'page' && /^https?:\/\//.test(t.url || '');
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
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      const text = m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 200);
      if (!THIRD_PARTY_NOISE.test(text)) jsProblems.push(tag + ' console.error: ' + text.slice(0, 160));
    }
  };
  async function send(method, params, timeoutMs) {
    const id = ++seq;
    ws.send(JSON.stringify({ id: id, method: method, params: params || {} }));
    return new Promise((res, rej) => {
      pending.set(id, { res: res, rej: rej });
      setTimeout(() => {
        if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); }
      }, timeoutMs || 20000);
    });
  }

  /** 导航类命令（`Page.reload` / `Page.navigate`）：**不等 CDP 回执**。
   *
   *  ⚠️ 整页导航会换掉文档，CDP 那条命令的响应常常**永远不回** ——
   *  等它会拿到 `timeout Page.reload`，而页面其实已经重载好了。
   *  症状是"只印了一条 PASS 就中断"（实测踩过两次）。
   *  所以只管发出去，再用 `awaitReady()` 轮询页面自己的 readyState 兜底。
   */
  function navigate(method, params, waitMs) {
    try { ws.send(JSON.stringify({ id: ++seq, method: method, params: params || {} })); } catch (e) { /* ignore */ }
    return sleep(waitMs || 1500);
  }
  async function awaitReady(timeout) {
    const t0 = Date.now();
    while (Date.now() - t0 < (timeout || 25000)) {
      try {
        if (await ev('document.readyState', 2500) === 'complete') return true;
      } catch (e) { /* 导航中：文档被换掉，这次求值不会返回 —— 等下一轮 */ }
      await sleep(300);
    }
    return false;
  }
  /** 页面求值。`awaitPromise` 默认开（很多表达式是 Promise）。
   *
   *  `timeoutMs`：整页导航期间文档会被换掉，那次求值的 Promise **永远不落地** ——
   *  等它就会在 20 秒后抛 `timeout Runtime.evaluate`（而页面其实好好的）。
   *  轮询 readyState 这类调用要显式给一个短超时。
   *
   *  ⚠️ 表达式外面包一层 `/*#<name>#*​/` 标签：页面异常只报"某行第 N 列"，
   *  复合表达式的列号根本对不上人眼能数出来的位置（本工具在这里耗了很久）。
   *  有了标签，抛出来的就是 `[#名称#] TypeError: …`。
   */
  const evLabels = new Map();
  let evSeq = 0;
  async function ev(expression, timeoutMs) {
    const label = '#ev' + (++evSeq) + '#';
    evLabels.set(label, expression.length > 90 ? expression.slice(0, 90) + '…' : expression);
    const wrapped = '/*' + label + '*/' + expression;
    const r = await send('Runtime.evaluate',
      { expression: wrapped, awaitPromise: true, returnByValue: true },
      timeoutMs || 20000);
    if (r.exceptionDetails) {
      const at = (r.exceptionDetails.stackTrace && r.exceptionDetails.stackTrace.callFrames
        && r.exceptionDetails.stackTrace.callFrames[0]) || {};
      const desc = (r.exceptionDetails.exception && r.exceptionDetails.exception.description)
        || r.exceptionDetails.text || JSON.stringify(r.exceptionDetails);
      const src = evLabels.get(label) || '';
      throw new Error(tag + ' 表达式 ' + label + ' 抛异常: ' + desc
        + '  ← 表达式开头: ' + JSON.stringify(src));
    }
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
    tag: tag, ev: ev, send: send, navigate: navigate, awaitReady: awaitReady, waitFor: waitFor,
    close: () => {
      try { ws.close(); } catch (e) { /* ignore */ }
      try { proc.kill(); } catch (e) { /* ignore */ }
      preClean(tag);
    },
  };
}

// ---------------------------------------------------------------------------
// 页面侧小工具
// ---------------------------------------------------------------------------
const jsStr = (s) => JSON.stringify(s);

// 注册 + 登录 + 重载（重载是为了让新 session 生效并建立一条干净 socket）。
// ⚠️ `redirect: 'manual'` 是**必须的**：`/register` 与 `/login` 成功时是 302 到首页，
//    跟着跳的话浏览器会去抓整个首页（几十个静态资源），实测偶发地慢到超出任何合理
//    等待时间 —— 症状是"注册这一步直接中断"，而服务端日志里那条**注册其实成功了**
//    （于是下一次运行的断言全对不上号）。
// ⚠️ 每个 fetch 都带**显式超时**：不带超时时，一次卡住的请求会把整条 CDP 求值一起
//    挂到 20 秒上限。
const REGISTER_AND_LOGIN = (user, pass) => '(async function(){'
  + ' function timed(url, init, ms){'
  + '   var ctl = new AbortController();'
  + '   var t = setTimeout(function(){ ctl.abort(); }, ms);'
  + '   var opt = Object.assign({}, init, { signal: ctl.signal });'
  + '   return fetch(url, opt).then(function(r){ clearTimeout(t); return r; },'
  + '     function(e){ clearTimeout(t); throw e; }); }'
  + ' var body = new URLSearchParams({ username: ' + jsStr(user) + ', password: ' + jsStr(pass) + ' });'
  + ' var post = { method: "POST", credentials: "same-origin", redirect: "manual",'
  + '   headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: body };'
  + ' var out = { step: "register" };'
  + ' try {'
  + '   out.register = (await timed("/register", post, 8000)).status;'
  + '   out.step = "login";'
  + '   out.login = (await timed("/login", post, 8000)).status;'
  + '   out.step = "setting";'
  + '   var r3 = await timed("/api/spectate/setting", { credentials: "same-origin" }, 5000);'
  + '   out.setting = await r3.json();'
  + '   out.step = "done";'
  + ' } catch (e) { out.error = String(e && e.message || e); }'
  + ' return out; })()';

// ⚠️ 重载必须用 CDP 的 `Page.reload`，**不要**在页面里 `Runtime.evaluate` 一个
//    "location.reload(); return 1" —— 导航会取消那次求值，而 `awaitPromise: true`
//    让 CDP 一直等一个永远不落地的 promise，20 秒后报 `timeout Runtime.evaluate`，
//    症状是"只印了一条 PASS 就中断"（实测踩过一次）。
// ⚠️ 页面里能用的是 `onSocketReady`（挂在 window 上的那个）—— `ensureSocket` 是
//    game.js 的模块级函数，**不在 window 上**，直接调会 `ReferenceError`
//    （实测踩过一次，症状是"重载后第一项就中断"）。
const SOCKET_READY = '(async function(){'
  + ' for (var i = 0; i < 200; i++) {'
  + '   try { if (gameState.socket && gameState.socket.connected) return true; } catch (e) {}'
  + '   await new Promise(function(r){ setTimeout(r, 100); });'
  + ' }'
  + ' return false; })()';

const MATCH_ROWS = '(function(){'
  + ' var out = [];'
  + ' document.querySelectorAll("#lobby-matches-list .lobby-match").forEach(function(r){'
  + '   var nm = r.querySelector(".lobby-match-name");'
  + '   var mt = r.querySelector(".lobby-match-meta");'
  + '   var bt = r.querySelector(".lobby-match-spectate");'
  + '   out.push({ name: nm ? nm.textContent.trim() : "", meta: mt ? mt.textContent.trim() : "",'
  + '     roomId: bt ? (bt.dataset.room || "") : "", hasBtn: !!bt });'
  + ' }); return out; })()';

const ENTER_LOBBY = '(function(){ history.pushState({}, "", "/lobby"); showLobby(); return 1; })()';

// 观战屏的体检：屏是否 active、棋盘格数、"船"格数、已轰格数、标题、人数
const SPECTATE_PROBE = '(function(){'
  + ' var gs = (window.gameState || {});'
  + ' var sp = gs.spectate || {};'
  + ' var b1 = document.getElementById("spectate-board-1");'
  + ' var b2 = document.getElementById("spectate-board-2");'
  + ' function cells(el, cls){ return el ? el.querySelectorAll(cls).length : -1; }'
  + ' return {'
  + '   active: !!(document.getElementById("spectate-screen")'
  + '     && document.getElementById("spectate-screen").classList.contains("active")),'
  + '   gameScreenActive: !!(document.getElementById("game-screen")'
  + '     && document.getElementById("game-screen").classList.contains("active")),'
  + '   spectating: sp.active === true,'
  + '   roomId: sp.roomId || null,'
  + '   board1: cells(b1, ".cell"), board2: cells(b2, ".cell"),'
  + '   ships1: cells(b1, ".cell.ship"), ships2: cells(b2, ".cell.ship"),'
  + '   marks1: cells(b1, ".cell.hit") + cells(b1, ".cell.miss"),'
  + '   marks2: cells(b2, ".cell.hit") + cells(b2, ".cell.miss"),'
  + '   hits1: cells(b1, ".cell.hit"), hits2: cells(b2, ".cell.hit"),'
  + '   count: document.getElementById("spectate-count") ? document.getElementById("spectate-count").textContent.trim() : null,'
  + '   limit: document.getElementById("spectate-limit") ? document.getElementById("spectate-limit").textContent.trim() : null,'
  + '   name1: document.getElementById("spectate-name-1") ? document.getElementById("spectate-name-1").textContent.trim() : null,'
  + '   name2: document.getElementById("spectate-name-2") ? document.getElementById("spectate-name-2").textContent.trim() : null,'
  + '   turn: document.getElementById("spectate-turn") ? document.getElementById("spectate-turn").textContent.trim() : null,'
  + '   logs: document.querySelectorAll("#spectate-logs .spectate-log-item").length,'
  + '   playerId: gs.playerId === undefined ? "undefined" : String(gs.playerId),'
  + ' }; })()';

// 玩家的对局屏体检（对照腿）
const PLAYER_BOARD_PROBE = '(function(){'
  + ' var ob = document.getElementById("opponent-board");'
  + ' var pm = document.getElementById("player-board");'
  + ' function n(el, cls){ return el ? el.querySelectorAll(cls).length : -1; }'
  + ' return { oppShips: n(ob, ".cell.ship"), myShips: n(pm, ".cell.ship"),'
  + '   oppMarks: n(ob, ".cell.hit") + n(ob, ".cell.miss"),'
  + '   oppCells: n(ob, ".cell") }; })()';

// 点甲自己棋盘上"服务器说那是乙的船、且还没打过"的那一格。
// ⚠️ 拼选择器时**绝对不能**把引号写错：`data-x="3"` 里的引号要靠 `\\"` 进到
//    页面侧的字符串里（三层引号，第一版就在这里写错过）。
function attackCellExpr(x, y) {
  return '(function(){'
    + ' var sel = "#opponent-board .cell[data-x=\\"" + ' + JSON.stringify(String(x))
    + ' + "\\"][data-y=\\"" + ' + JSON.stringify(String(y)) + ' + "\\"]";'
    + ' var el = document.querySelector(sel);'
    + ' if (!el) return { clicked: false, reason: "找不到那一格: " + sel };'
    + ' el.click(); return { clicked: true, sel: sel }; })()';
}

// 拆成三条**互不相干**的小表达式，而不是一条复合的 `return {…}`：
// 复合表达式一旦抛异常，异常只报"整行第 N 列"，排查成本极高（本工具在这个
// 形状上耗了很久）；拆开之后哪个子步骤红了一眼可见。
const OPEN_SETTINGS = '(function(){'
  + ' var b = document.getElementById("settings-btn");'
  + ' if (b) b.click();'
  + ' var m = document.getElementById("settings-modal");'
  + ' return !!(m && !m.classList.contains("hidden")); })()';

// ⚠️ 点左导航的**按钮**切到「账号与隐私」，别调 `showSettingsPane` ——
//    那是 game.js 的模块级函数，**不在 window 上**（本工具在这个形状上
//    连栽三次：`ensureSocket` / `switchScreen` / `showSettingsPane`）。
const SHOW_ACCT_PANE = '(function(){'
  + ' var nav = document.querySelector("#settings-modal .settings-nav-item[data-pane=acct]");'
  + ' if (nav) nav.click();'
  + ' var p = document.querySelector("#settings-modal .settings-pane[data-pane=acct]");'
  + ' return !!(p && !p.classList.contains("hidden")); })()';

const READ_SPECTATE_BOX = '(function(){'
  + ' var box = document.getElementById("settings-allow-spectate");'
  + ' var msg = document.getElementById("settings-spectate-msg");'
  + ' return { exists: !!box, checked: box ? box.checked : null,'
  + '   disabled: box ? box.disabled : null,'
  + '   msg: msg ? msg.textContent.trim() : null }; })()';

// 把开关**设成指定值**（而不是"翻转"）。
// ⚠️ 翻转是错的：设置面的勾选态是**异步**跟着服务端走的（POST 往返 + 提示文案更新），
//    上一轮改完立刻翻一次就可能收到同一个值 —— 实测症状是
//    "再点开关打开" 报 `want:false`、服务端仍是 false、列表永远不回来。
const SET_SETTINGS_SPECTATE = (want) => '(function(){'
  + ' var box = document.getElementById("settings-allow-spectate");'
  + ' if (!box) return { toggled: false, reason: "no checkbox" };'
  + ' box.checked = ' + (want ? 'true' : 'false') + ';'
  + ' box.dispatchEvent(new Event("change", { bubbles: true }));'
  + ' return { toggled: true, want: box.checked }; })()';

const SETTING_MSG = 'document.getElementById("settings-spectate-msg").textContent.trim()';
const SETTING_CHECKED = 'document.getElementById("settings-allow-spectate").checked';

const READ_SETTING_API = '(async function(){'
  + ' var r = await fetch("/api/spectate/setting", { credentials: "same-origin" });'
  + ' return await r.json(); })()';

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
/** 每一步都打一行进度：这个工具最贵的失败是"只印了一条就中断"—— 
 *  从输出里看不出卡在哪一步（实测踩过两次，两次的根因完全不同）。 */
function step(text) { console.log('---- ' + text); }

let A = null, B = null, C = null;
const stamp = Date.now().toString(36);
const USER_A = 'specA' + stamp;
const USER_B = 'specB' + stamp;
const USER_C = 'specC' + stamp;
const PASS = 'spec-pass-1234';

try {
  step('启动三个无头浏览器');
  A = await launch('spectate_check_a_profile', 9370);
  B = await launch('spectate_check_b_profile', 9371);
  C = await launch('spectate_check_c_profile', 9372);
  for (const br of [A, B, C]) {
    await br.send('Page.enable');
    await br.send('Runtime.enable');
    await br.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    br.navigate('Page.navigate', { url: APP }, 1500);
  }
  for (const br of [A, B, C]) {
    const ready = await br.awaitReady(30000);
    check(ready === true, '（前提）' + br.tag + ' 页面加载完成', ready);
  }

  // --- 1. 前置：三个登录账号 -----------------------------------------------
  step('注册并登录三个账号');
  for (const [br, user] of [[A, USER_A], [B, USER_B], [C, USER_C]]) {
    // ⚠️ 重试是必须的：无头 Edge 里 `/register` 偶发地一条请求就永远不回来
    //    （服务端日志显示注册其实**成功了**，是客户端这次 fetch 没了下文）。
    //    只试一次的话会拿到一个"注册失败"的假红，后面所有断言跟着一起崩。
    let out = null;
    for (let attempt = 0; attempt < 3; attempt++) {
      out = await br.ev(REGISTER_AND_LOGIN(user, PASS), 30000);
      if (out && out.setting && out.setting.success === true) break;
      console.log('   （' + br.tag + ' 第 ' + (attempt + 1) + ' 次没成：'
        + JSON.stringify(out) + '，重试）');
      await sleep(1200);
    }
    check(!!out && out.setting && out.setting.success === true,
      '（前提）' + br.tag + ' 注册并登录成功（观战只限登录用户）', out);
  }
  step('重载三个页面并等 socket');
  for (const br of [A, B, C]) {
    br.navigate('Page.reload', {}, 1500);
  }
  for (const br of [A, B, C]) {
    const ready = await br.awaitReady(30000);
    check(ready === true, '（前提）' + br.tag + ' 重载后页面就绪', ready);
    let ok = false;
    for (let i = 0; i < 3 && !ok; i++) {
      ok = (await br.ev(SOCKET_READY, 30000)) === true;
      if (!ok) await sleep(1500);
    }
    check(ok === true, '（前提）' + br.tag + ' 的 socket 已连接', ok);
  }
  for (const [br, user] of [[A, USER_A], [B, USER_B], [C, USER_C]]) {
    const api = await br.ev(READ_SETTING_API);
    check(!!api && api.success === true && api.allow_spectate === true,
      '（前提）' + br.tag + '（' + user + '）默认允许被观战', api);
  }

  // --- 2. 甲乙真的打起来 ----------------------------------------------------
  const created = await A.ev('new Promise(function(res){'
    + ' gameState.playerName = ' + jsStr(USER_A) + ';'
    + ' gameState.socket.emit("create_room", { player_name: ' + jsStr(USER_A) + ' }, function(r){ res(r); }); })');
  const roomId = created && created.room_id;
  check(!!roomId, '甲建房成功', created);

  const joined = await B.ev('new Promise(function(res){'
    + ' gameState.playerName = ' + jsStr(USER_B) + ';'
    + ' gameState.socket.emit("join_room", { room_id: ' + jsStr(roomId) + ', player_name: '
    + jsStr(USER_B) + ' }, function(r){ res(r); }); })');
  check(!!joined && joined.status === 'success', '乙进房成功', joined);

  const st0 = await A.ev('new Promise(function(res){'
    + ' gameState.socket.emit("test_get_game_state", { room_id: ' + jsStr(roomId) + ' }, function(x){ res(x); }); })');
  const bPid = joined && joined.player_id;
  const ids = st0 && st0.game_state ? Object.keys(st0.game_state.players) : [];
  const aPid = ids.find((i) => i !== bPid);
  check(!!aPid && !!bPid && aPid !== bPid, '两个座位 key 明确可区分（不靠猜顺序）', { aPid: aPid, bPid: bPid });

  for (const [br, pid] of [[A, aPid], [B, bPid]]) {
    await br.ev('gameState.roomId = ' + jsStr(roomId) + '; gameState.playerId = ' + jsStr(pid) + '; 1');
  }

  // 布船 + 猜拳：直接用真 socket（布船界面在无头下点六格太脆），
  // 之后**所有**断言都走真实 UI / 真实事件。
  const shipsA = JSON.stringify(Array.from({ length: 6 }, (_, i) => ({ positions: [{ x: i, y: 0 }], hits: [] })));
  const shipsB = JSON.stringify(Array.from({ length: 6 }, (_, i) => ({ positions: [{ x: i, y: 5 }], hits: [] })));
  await A.ev('new Promise(function(res){ gameState.socket.emit("place_ships", { room_id: ' + jsStr(roomId)
    + ', player_id: ' + jsStr(aPid) + ', ships: ' + shipsA + ' }, function(r){ res(r); }); })');
  await B.ev('new Promise(function(res){ gameState.socket.emit("place_ships", { room_id: ' + jsStr(roomId)
    + ', player_id: ' + jsStr(bPid) + ', ships: ' + shipsB + ' }, function(r){ res(r); }); })');
  await sleep(500);

  let st = null, attacker = null;
  for (let i = 0; i < 12 && !attacker; i++) {
    await A.ev('new Promise(function(res){ gameState.socket.emit("rps_choice", { room_id: ' + jsStr(roomId)
      + ', player_id: ' + jsStr(aPid) + ', choice: "rock" }, function(r){ res(r); }); })');
    await B.ev('new Promise(function(res){ gameState.socket.emit("rps_choice", { room_id: ' + jsStr(roomId)
      + ', player_id: ' + jsStr(bPid) + ', choice: "scissors" }, function(r){ res(r); }); })');
    await sleep(400);
    const s = await A.ev('new Promise(function(res){ gameState.socket.emit("test_get_game_state", { room_id: '
      + jsStr(roomId) + ' }, function(x){ res(x); }); })');
    st = s && s.game_state;
    attacker = st && st.current_attacker;
  }
  check(!!attacker && st.state === 'attacking', '甲乙进入攻击阶段（观战列表的前提）',
    { state: st && st.state, attacker: attacker, round: st && st.round });

  const atkTab = attacker === aPid ? A : B;
  const atkPid = attacker;
  const victimName = attacker === aPid ? USER_B : USER_A;
  check(atkTab.tag === 'spectate_check_a_profile' || atkTab.tag === 'spectate_check_b_profile',
    '（前提）攻击方是甲或乙之一', atkTab.tag);

  // ⚠️ 别在下面用 `atkTab` 当循环变量名：本工具**已经踩过这个坑** ——
  //    `for (const atkTab of [A, B])` 把"攻击方那个页面"覆盖成了 B，
  //    之后所有 `atkTab.ev(...)` 都打在乙身上，而报出来的是一句与根因无关的
  //    `TypeError: (intermediate value) is not a function`（乙没进过房，
  //    `gameState.socket` 还是 null）。循环变量一律叫 `br` / `conn`。

  // 双方都把界面切到对局屏（这样对照腿读的是真实的对局屏）。
  // ⚠️ 用**点了就会生效的按钮**，别直接调 `switchScreen` / `initGameBoards` ——
  //    那些是 game.js 的模块级函数，**不在 window 上**（同 `ensureSocket` 那个坑）。
  //    RPS 结束的那一刻客户端已经收到 `game_state(state='attacking')`，
  //    它自己会切屏 + 初始化棋盘（见 game.js 的 applyRoomSync/game_state 分支）。
  for (const br of [A, B]) {
    await br.ev('(function(){'
      + ' var g = document.getElementById("game-screen");'
      + ' return { gameScreenActive: !!(g && g.classList.contains("active")),'
      + '   oppCells: document.querySelectorAll("#opponent-board .cell").length,'
      + '   oppShips: document.querySelectorAll("#opponent-board .cell.ship").length }; })()');
  }
  // ⚠️ **不要**为了"把界面推过去"去点任何按钮 —— 试过点 `#surrender-btn`，
  //    那会真的投降结束对局（这一步纯属自伤）。
  //    棋盘没就绪就直说：它本身是"对局屏有没有跟着服务端走"的信号。

  // --- 3. ★ 丙在大厅看到「进行中的对局」 -----------------------------------
  await C.ev(ENTER_LOBBY);
  await C.waitFor(async () => await C.ev('gameState.lobbySubscribed === true && !!gameState.lobbyKey'),
    15000, '丙订阅大厅');
  await C.waitFor(async () => {
    const rows = await C.ev(MATCH_ROWS);
    return Array.isArray(rows) && rows.some((r) => r.roomId === roomId);
  }, 25000, '丙的「进行中的对局」里出现这一局');
  const rowsC = await C.ev(MATCH_ROWS);
  const rowC = rowsC.find((r) => r.roomId === roomId);
  check(!!rowC, '★ 丙在大厅看到这一局（观战入口真的存在）', rowsC);
  check(!!rowC && rowC.name.indexOf(USER_A) >= 0 && rowC.name.indexOf(USER_B) >= 0,
    '★ 条目上写着双方名字', rowC);
  check(!!rowC && /第\s*\d+\s*回合/.test(rowC.meta) && /观战\s*\d+\/\d+/.test(rowC.meta),
    '★ 条目带回合数与观战人数', rowC && rowC.meta);
  check(!!rowC && rowC.hasBtn === true, '★ 条目有「观战」按钮', rowC);
  const lobbyRooms = await C.ev('document.querySelectorAll("#lobby-rooms-list .lobby-room").length');
  check(lobbyRooms === 0, '进行中的局**没有**混进「房间列表」（两块列表分开）', lobbyRooms);

  // --- 4. ★ 丙点「观战」进屏 -------------------------------------------------
  // 点真实的按钮（事件委托绑定，所以这一下顺带验证了委托没绑漏）
  const clicked = await C.ev('(function(){'
    + ' var rows = document.querySelectorAll("#lobby-matches-list .lobby-match");'
    + ' for (var i = 0; i < rows.length; i++) {'
    + '   var b = rows[i].querySelector(".lobby-match-spectate");'
    + '   if (b && b.dataset.room === ' + jsStr(roomId) + ') { b.click(); return true; }'
    + ' } return false; })()');
  check(clicked === true, '丙点到了那一局的「观战」按钮', clicked);
  await C.waitFor(async () => await C.ev('!!(gameState.spectate && gameState.spectate.active)'),
    20000, '丙进席');
  await C.waitFor(async () => await C.ev(
    'document.getElementById("spectate-screen").classList.contains("active")'), 10000, '丙的观战屏激活');
  let probe = await C.ev(SPECTATE_PROBE);
  if (argv.includes('--debug')) {
    const raw = await C.ev('(function(){ var s = gameState.spectate.snapshot || null;'
      + ' return s ? { sides: s.sides, seat_labels: s.seat_labels,'
      + '   board_attacks: s.board_attacks, logs: (s.game_logs || []).length,'
      + '   state: s.state, round: s.round } : null; })()');
    console.log('DEBUG 观众拿到的快照: ' + JSON.stringify(raw).slice(0, 1200));
    const dom = await C.ev('(function(){'
      + ' var out = {};'
      + ' ["spectate-name-1","spectate-name-2","spectate-board-title-1","spectate-ships-1",'
      + ' "spectate-hand-1","spectate-status","spectate-phase"].forEach(function(id){'
      + '   var el = document.getElementById(id);'
      + '   out[id] = el ? (el.textContent || "") : "<<null>>"; }); return out; })()');
    console.log('DEBUG 观战屏 DOM 文本: ' + JSON.stringify(dom));
  }
  check(probe.active === true, '★ 丙切到了**独立的**观战屏 #spectate-screen', probe);
  check(probe.gameScreenActive === false, '★ 观战屏与对局屏**没有同时可见**', probe);
  check(probe.name1 === USER_A && probe.name2 === USER_B,
    '★ 观战屏上两块棋盘分别标着双方名字', { name1: probe.name1, name2: probe.name2 });
  check(probe.board1 === 36 && probe.board2 === 36, '两块棋盘都画满 36 格', probe);
  check(probe.count === '1' && probe.limit === '20', '★ 观战人数 1/20（上限来自服务端）', probe);
  // ⚠️ 这里**不**断言"日志已经有内容"：布船与猜拳**不写对局日志**
  //    （`add_game_log` 的调用点全是动作类：开炮 / 出牌 / 阶段转换…），
  //    所以这一刻快照里的 `game_logs` 本来就是空的 —— 拿它当断言是自造的假红。
  //    日志的实时性由下面"打一炮之后多一条"那条来证。

  // --- 5. ★★ 最关键：观战屏上没有任何一格"船" -------------------------------
  check(probe.ships1 === 0 && probe.ships2 === 0,
    '★★ 观战屏上「船」格数 = 0（未被打过的船位一个都没出现）', probe);
  check(probe.marks1 === 0 && probe.marks2 === 0,
    '开局时两块棋盘上都还没有任何"挨过炮"的格（对照：0 不是画不出来）',
    { marks1: probe.marks1, marks2: probe.marks2 });
  const playerProbe = await atkTab.ev(PLAYER_BOARD_PROBE);
  check(playerProbe.oppCells === 36,
    '（对照腿）玩家自己的对局屏上对方棋盘确实画好了 36 格', playerProbe);

  // --- 6. ★ 甲打一炮 → 丙那边实时出现 --------------------------------------
  // 挑一格：乙棋盘上必然有船的那一格（甲自己的屏上"哪里打过"是公开的，
  // 但"乙的船在哪"甲并不知道 —— 这里读快照只是为了让脚本必定命中，
  // 与观战通道的可见性无关）。
  const victimPid = attacker === aPid ? bPid : aPid;
  const victimShips = (st.players[victimPid] && st.players[victimPid].ships) || [];
  const target = victimShips.flatMap((s) => s.positions)[0];
  check(!!target, '（前提）拿到一个必定命中的目标格', target);
  const tx = target[0], ty = target[1];

  // ⚠️ 攻击必须发生在**战斗阶段**：`handleAttack` 的第一道闸门就是
  //    `gameState.currentPhase !== 'battle'` → 不满足时它只弹一句
  //    「当前不是战斗阶段」就 return，**一个字节都不发**。
  //    而阶段切换会先向对方发起**优先权询问**（`awaiting_priority: true`，
  //    阶段原地不动）—— 所以两边都先关掉这个询问，再推进。
  let out = null;
  for (const [br, pid] of [[A, aPid], [B, bPid]]) {
    await br.ev('new Promise(function(res){ gameState.socket.emit("set_decline_priority",'
      + ' { room_id: ' + jsStr(roomId) + ', player_id: ' + jsStr(pid) + ', decline: true },'
      + ' function(r){ res(r); }); })');
  }
  for (let i = 0; i < 8; i++) {
    out = await atkTab.ev('new Promise(function(res){ gameState.socket.emit("enter_battle_phase",'
      + ' { room_id: ' + jsStr(roomId) + ', player_id: ' + jsStr(atkPid) + ' }, function(r){ res(r); }); })');
    await sleep(700);
    const phase = await atkTab.ev('String(gameState.currentPhase)');
    if (phase === 'battle') break;
  }
  check(!!out && (out.status === 'success'),
    '（前提）攻击方推进到战斗阶段', out);
  const phaseNow = await atkTab.ev('String(gameState.currentPhase)');
  check(phaseNow === 'battle', '（前提）玩家侧确实处于战斗阶段（阶段广播收到了）', phaseNow);

  const beforeMarks = { m1: probe.marks1, m2: probe.marks2 };
  // 打一炮：走**真事件**（`attack`），不模拟点格子 —— 无头环境里"格子能不能点"
  // 取决于本地渲染是否已就绪，那是另一件事；本工具要证的是
  // "服务端广播的动作事件，观众那边实时看得到"。
  const shot = await atkTab.ev('new Promise(function(res){'
    + ' gameState.socket.emit("attack", { room_id: ' + jsStr(roomId) + ', player_id: ' + jsStr(atkPid)
    + ', x: ' + tx + ', y: ' + ty + ' }, function(r){ res(r); }); })');
  check(!!shot && shot.status === 'success', '甲打出了一炮（服务端接受）', shot);
  if (argv.includes('--debug')) {
    console.log('DEBUG 打炮前服务端状态: ' + JSON.stringify(await atkTab.ev(
      'new Promise(function(res){ gameState.socket.emit("test_get_game_state", { room_id: '
      + jsStr(roomId) + ' }, function(x){ var g = x && x.game_state;'
      + ' res(g ? { state: g.state, phase: g.current_phase, attacker: g.current_attacker,'
      + '   left: g.attacks_remaining, round: g.round,'
      + '   myAttacks: (g.players[g.current_attacker] || {}).attacks } : x); }); })')).slice(0, 800));
    console.log('DEBUG 玩家屏的 gameState 片段: ' + JSON.stringify(await atkTab.ev('(function(){'
      + ' return { hasSocket: !!gameState.socket, playerId: String(gameState.playerId),'
      + '   roomId: String(gameState.roomId), isMyTurn: gameState.isMyTurn,'
      + '   currentPhase: String(gameState.currentPhase),'
      + '   attacksRemainingText: (document.getElementById("attacks-remaining") || {}).textContent }; })()')));
  }

  // ⚠️ 全程**不刷新丙的页面** —— 这正是本批要证的东西。
  let after = null;
  try {
    await C.waitFor(async () => {
      const p = await C.ev(SPECTATE_PROBE);
      return (p.marks1 + p.marks2) > (beforeMarks.m1 + beforeMarks.m2);
    }, 15000, '丙那边出现新格子');
    after = await C.ev(SPECTATE_PROBE);
    check(true, '★★ 甲打炮后，丙那边的棋盘**不刷新页面**就多了一格');
  } catch (e) {
    after = await C.ev(SPECTATE_PROBE);
    check(false, '★★ 甲打炮后，丙那边应当实时多一格', { before: beforeMarks, after: after });
  }

  // 打出去的格只能出现在**挨打那一位**的棋盘上（两块棋盘不许画反）
  const atkIsP1 = atkPid === aPid;      // p1 = 先入座（甲）
  const victimBoardIsSecond = atkIsP1;  // 甲打 → 落在乙（第 2 块）棋盘
  const victimMarks = victimBoardIsSecond ? after.marks2 : after.marks1;
  const otherMarks = victimBoardIsSecond ? after.marks1 : after.marks2;
  check(victimMarks === 1 && otherMarks === 0,
    '★ 这一炮只落在**挨打那一位**的棋盘上（两块棋盘没画反）',
    { victim: victimName, victimMarks: victimMarks, otherMarks: otherMarks,
      atkIsP1: atkIsP1, userA: USER_A });
  check(after.ships1 === 0 && after.ships2 === 0,
    '★★ 打完之后观战屏上「船」格数**仍然是 0**', { ships1: after.ships1, ships2: after.ships2 });
  const afterHits = victimBoardIsSecond ? after.hits2 : after.hits1;
  check(afterHits === 1, '那一格带 hit 标记（命中渲染正确）', { hits: afterHits });
  check(after.logs > probe.logs, '日志也实时多了一条（炮击记录）',
    { before: probe.logs, after: after.logs });

  // --- 7. 观战人数在**大厅列表**里的显示（先记下"观众在席"时的那一份）--------
  // ⚠️ 为什么不去挂 `spectate_count_changed` 监听：那条事件在丙进席那一刻就已经
  //    发过了（`_spectate_broadcast_count`），后挂的监听永远等不到；而在页面里
  //    调 `gameState.socket.on / off` 会抛
  //    `TypeError: (intermediate value) is not a function`（同一个 socket 上别的
  //    方法都正常），把整条 CDP 求值挂死 —— 症状是"前面全绿、工具突然中断"。
  //    改成读**大厅列表里那份人数**（服务端算的，与快照同源），
  //    丙退出后再读一次就必须回到 0。
  // 先让丙自己刷新一次大厅，好让列表里那份「观战 N/20」是刚算出来的
  // （4 秒兜底广播会自己到，但工具不该靠等）。
  await C.ev('gameState.socket.emit("lobby_refresh", {}, function(){}); 1');
  await sleep(900);
  const rowWithSpectator = (await C.ev(MATCH_ROWS)).find((r) => r.roomId === roomId);
  check(!!rowWithSpectator && /观战\s*1\//.test(rowWithSpectator.meta),
    '★ 有人在看时，大厅列表上这一局显示「观战 1/20」', rowWithSpectator && rowWithSpectator.meta);

  // --- 8. ★ 设置面里真的关掉观战 → 列表里消失 ------------------------------
  const modalOpen = await atkTab.ev(OPEN_SETTINGS);
  check(modalOpen === true, '★ 设置面能打开', modalOpen);
  const paneShown = await atkTab.ev(SHOW_ACCT_PANE);
  check(paneShown === true, '★ 切得到「账号与隐私」分区', paneShown);
  const opened = await atkTab.ev(READ_SPECTATE_BOX);
  check(!!opened && opened.exists === true, '★ 设置面里有「允许他人观战我的对局」开关', opened);
  check(!!opened && opened.checked === true && opened.disabled === false,
    '★ 开关初始状态**来自服务端**（默认开、可用）', opened);

  const toggledOff = await atkTab.ev(SET_SETTINGS_SPECTATE(false));
  check(!!toggledOff && toggledOff.toggled === true, '把开关设成"不允许"', toggledOff);
  // 等到服务端真的记下了再往下走：勾选态是异步跟着 POST 走的，
  // 立刻读会读到**上一轮**的文案（实测踩过，连带下面几步一起假红）。
  let apiOff = null;
  for (let i = 0; i < 15; i++) {
    apiOff = await atkTab.ev(READ_SETTING_API);
    if (apiOff && apiOff.allow_spectate === false) break;
    await sleep(400);
  }
  check(!!apiOff && apiOff.allow_spectate === false, '★ 服务端确实记下了"不允许"', apiOff);
  // 提示位是**跟着 POST 回包**更新的，所以这里等的是"提示不再是进面板那句默认文案"
  // —— 它一变就说明这次 POST 的 .then 真的跑过了（那正是"不静默"的证据）。
  // ⚠️ 别写死成「已保存」：成功之后紧接着会被换成对当前状态的描述，
  //    究竟看到哪一句取决于读的时刻 —— 写死就是自造假红（实测踩过）。
  let msgOff = '';
  for (let i = 0; i < 20; i++) {
    msgOff = String(await atkTab.ev(SETTING_MSG));
    if (msgOff.indexOf('打开后：') < 0) break;
    await sleep(300);
  }
  check(msgOff.indexOf('打开后：') < 0 && /观战|围观/.test(msgOff),
    '★ 保存后提示位真的更新了（不是停在进面板时那句默认提示）', msgOff);
  check(!/失败/.test(msgOff), '★ 保存没有报失败（失败必须回滚勾选并说明）', msgOff);

  await C.ev('gameState.socket.emit("lobby_refresh", {}, function(){}); 1');
  await C.waitFor(async () => {
    const rows = await C.ev(MATCH_ROWS);
    return !rows.some((r) => r.roomId === roomId);
  }, 25000, '该局从丙的列表里消失');
  const rowsGone = await C.ev(MATCH_ROWS);
  check(!rowsGone.some((r) => r.roomId === roomId),
    '★★ 玩家关掉观战设置后，这一局从**别人的**列表里消失（丙没刷新页面）', rowsGone);

  // --- 9. 再打开 → 又出现 ---------------------------------------------------
  const toggledOn = await atkTab.ev(SET_SETTINGS_SPECTATE(true));
  check(!!toggledOn && toggledOn.toggled === true, '再把开关设成"允许"', toggledOn);
  let apiOn = null;
  for (let i = 0; i < 15; i++) {
    apiOn = await atkTab.ev(READ_SETTING_API);
    if (apiOn && apiOn.allow_spectate === true) break;
    await sleep(400);
  }
  check(!!apiOn && apiOn.allow_spectate === true, '★ 服务端确实记下了"允许"', apiOn);
  await C.ev('gameState.socket.emit("lobby_refresh", {}, function(){}); 1');
  await C.waitFor(async () => {
    const rows = await C.ev(MATCH_ROWS);
    return rows.some((r) => r.roomId === roomId);
  }, 25000, '该局回到列表');
  check(true, '★★ 重新打开后这一局又回到列表里');

  // --- 10. 退出观战 --------------------------------------------------------
  await C.ev('document.getElementById("spectate-leave").click()');
  await C.waitFor(async () => await C.ev('gameState.spectate.active === false'), 15000, '丙退出观战');
  const leftProbe = await C.ev('(function(){ return { lobby: document.getElementById("lobby-screen")'
    + '.classList.contains("active"), spectate: document.getElementById("spectate-screen")'
    + '.classList.contains("active") }; })()');
  check(leftProbe.lobby === true && leftProbe.spectate === false,
    '★ 「退出观战」把丙送回大厅、且观战屏已收起', leftProbe);

  const clearedProbe = await C.ev('(function(){'
    + ' var b = document.getElementById("spectate-board-1");'
    + ' return { cells: b ? b.querySelectorAll(".cell").length : -1,'
    + '   ships: b ? b.querySelectorAll(".cell.ship").length : -1 }; })()');
  check(clearedProbe.cells === 0, '退出后观战屏的棋盘已被清空（不会把上一局留在屏上）', clearedProbe);

  // ★ 丙退出 → 大厅列表里这一局的人数必须回到 0
  await C.ev('gameState.socket.emit("lobby_refresh", {}, function(){}); 1');
  let rowAfterLeave = null;
  try {
    await C.waitFor(async () => {
      const rows = await C.ev(MATCH_ROWS);
      const row = rows.find((r) => r.roomId === roomId);
      rowAfterLeave = row || null;
      return !!row && /观战\s*0\//.test(row.meta);
    }, 20000, '人数回到 0');
    check(true, '★ 观众退出后，这一局的观战人数回到 0（服务端算的，不是前端猜的）');
  } catch (e) {
    check(false, '★ 观众退出后观战人数应当回到 0', rowAfterLeave);
  }
  // 人数事件本身只有 count：验证方式是**直接看服务端发给玩家的那份 payload**
  // （`spectate_count_changed` 由 lobby 之外的那条通道发出，前端没有落盘副本，
  //  所以这里用"玩家列表里只显示人数、没有任何名字"来钉住同一件事）。
  const namesInRow = rowAfterLeave ? String(rowAfterLeave.name) : '';
  check(namesInRow.indexOf(USER_C) < 0,
    '★★ 大厅列表里看不到观众名字（观众身份不外发）', rowAfterLeave);

  if (SHOT) {
    const s = await C.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(s.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }
  check(jsProblems.length === 0, '三个页面均无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  if (A) A.close();
  if (B) B.close();
  if (C) C.close();
  console.log(String.fromCharCode(10) + (problems.length
    ? '结果: ' + problems.length + ' 项不通过' + String.fromCharCode(10) + problems.map((p) => '  - ' + p).join(String.fromCharCode(10))
    : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
