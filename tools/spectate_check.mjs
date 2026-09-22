#!/usr/bin/env node
/**
 * 实时观战**第 3 + 4 批**端到端检查（无头 Edge + CDP，**四浏览器**）
 *
 * 四个真浏览器 = 甲（对局玩家）/ 乙（对局玩家）/ 丙（观众一）/ 丁（观众二）。
 * 依据：docs/LOBBY_2026_09_18.md §1.3（`matches` 契约）、
 *       docs/SPECTATE_BATCH3_2026_09_22.md、第 4 批（观战席名单 + 观战席聊天）。
 *
 * 为什么必须**真浏览器**：前几批测得再全，也测不到"另一个人坐在另一条
 * 连接上看到的东西"。而观战屏最要紧的一条不变量恰恰是**观众侧看不到什么**——
 * 自己给自己发事件是测不出来的（CLAUDE.md 通用教训：工具全绿、线上全坏）。
 *
 * ## 第 4 批为什么又加了**第四个**浏览器
 *
 * 本批两条铁律都是"**谁收不到**"：
 *   ① 观战席**名单**只给观众，对局双方只该收到"人数"；
 *   ② 观战席**聊天**只给观众（对局双方不可见），而玩家之间的聊天**观众要看得到**。
 * 只用一个观众是证明不了"玩家收不到"的 —— 而且**单向断言会空转绿**：
 * 发送路径整个坏掉时，"玩家没收到"照样通过。所以：
 *   · 丙 + 丁 = **两条真观众连接**（对照腿：观众之间确实互相收得到）；
 *   · 丁 同时在甲/乙的页面上装一个**原始收件记录器**（见 `TAP`），
 *     把这两个玩家连接真的收到了哪些事件名记下来 —— 这比"看代码"硬。
 *
 * 覆盖 14 组：
 *   1. 前置：四个**登录账号**真的连上 socket；
 *   2. 甲建房、乙加入 → 双方摆船 + 猜拳 → 真的进入 attacking；
 *   3. ★ 丙在大厅的「进行中的对局」里看到这一局（名字/回合/观战人数）；
 *   4. ★ 丙点「观战」→ 进入**独立的**观战屏（不是对局屏），URL/屏名都对得上；
 *   5. ★★ **观战屏上没有任何一格「船」**（未被打过的船位一个都不出现）；
 *   6. ★ 甲打一炮 → **丙那边不刷新页面**就出现那一格（hit/miss 与 hit 标记一致）；
 *   7. 这一炮在丙的**另一块**棋盘上（甲打出去的格只能出现在乙那块棋盘上）；
 *   8. ★★ **第 4 批**：丁进席 → 丙**不刷新**就多出一个名字；人数变成 2/20；
 *      丁说话 → 丙实时收到；甲发言 → 丙也看得到玩家之间的聊天；
 *      **甲/乙两侧的原始收件记录里都没有观战席聊天与名单**（两条腿都断言）；
 *   9. ★★ **第 4 批**：甲打出一张魔法卡 → 丙**不刷新**就在连锁区看到那张卡；
 *      乙连锁响应「失灵！」→ 丙实时看到第二张（且标着"已被康"）；
 *  10. 观战人数：丙进席后甲收到 `spectate_count_changed`；
 *  11. ★ 甲在**设置面里真的点开关**关掉观战 → 这一局从丙的列表里消失（不刷新）；
 *      再打开 → 又出现；
 *  12. 退出观战；
 *  13. 页面无 JS 异常/报错。
 *
 * 用法：
 *   node tools/spectate_check.mjs --url http://127.0.0.1:5099/ [--shot out.png] [--debug]
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
 *   · **每个实例都要有自己的 `--user-data-dir` 与调试端口**：共用 profile 时后几个会
 *     **静默起不来**，工具会连上第一个实例，"四个人"其实是同一个人。
 *   · 收尾必须按 profile 路径清理（`proc.kill()` 杀不掉孙进程）——否则残留的连接
 *     会以"数据对不上"的形式出现在**下一次**运行里（大厅批踩过）。
 *   · 本工具**跨次运行不稳定**（作者实测 3 次成功 2 次，有一次以
 *     `Inspected target navigated or closed` 提前收场）→ 跑失败先重试一次再下结论，
 *     报告里如实写"跑了几次、成功几次"。
 *   · 玩家侧的"收件记录器"必须**在页面自己建连之前**装好？**不需要** ——
 *     `gameState.socket` 在重载后就存在（`ensureSocket` 在 DOMContentLoaded 里调），
 *     我们只是包一层它的 `onevent`，之后的事件全都能记到。
 *     ⚠️ 但包装必须在**任何断言之前**做（`TAP` 就是干这个的）。
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
// 第 4 批：观战席名单 / 观战席聊天 / "玩家到底收到了什么"
// ---------------------------------------------------------------------------

// ★★ **原始收件记录器**（本批最硬的那条证据）。
//
// 为什么要它：本批两条铁律都是"**谁收不到**"，而"没收到"单独看是**空转绿** ——
// 发送路径整个坏掉时它照样通过。所以既要有对照腿（另一个观众真的收到了），
// 也要有一个**独立于 game.js 的证据**证明"这条连接当时活着、而且在收事件"。
//
// 做法：包一层 `gameState.socket.onevent`（socket.io v2 客户端解析完一帧后调它，
// 参数就是 `data = ['事件名', payload]`），把每个事件名记进 `window.__SPEC_EVENTS`。
// 这是**页面自己**的进站口，比读 `game.js` 的处理函数更接近"真的收到了吗"。
// ⚠️ 只包一次（`__SPEC_TAPPED` 标记）；每次调用会重置记录数组。
const TAP = '(function(){'
  + ' var s = (window.gameState || {}).socket;'
  + ' if (!s || typeof s.onevent !== "function") return { tapped: false, reason: "no socket" };'
  + ' window.__SPEC_EVENTS = [];'
  + ' if (!window.__SPEC_TAPPED) {'
  + '   var orig = s.onevent;'
  + '   s.onevent = function (packet) {'
  + '     try { var d = packet && packet.data;'
  + '       if (d && d.length) window.__SPEC_EVENTS.push(String(d[0])); } catch (e) {}'
  + '     return orig.apply(this, arguments); };'
  + '   window.__SPEC_TAPPED = true;'
  + ' }'
  + ' return { tapped: true }; })()';

// 取记录器里的快照：`{events: {事件名: 次数}, total: n}`
const TAP_DUMP = '(function(){'
  + ' var out = {}, total = 0;'
  + ' (window.__SPEC_EVENTS || []).forEach(function (n) {'
  + '   out[n] = (out[n] || 0) + 1; total++; });'
  + ' return { events: out, total: total }; })()';

// ★ 对照腿：确认这个页面**确实在收事件**（否则"某事件 0 次"可能只是没连上）。
const TAP_ALIVE = '(function(){ return (window.__SPEC_EVENTS || []).length; })()';

// 观战屏的名单 / 聊天体检（第 4 批新增的两块）
const SPECTATE_SOCIAL_PROBE = '(function(){'
  + ' var sp = ((window.gameState || {}).spectate) || {};'
  + ' function txt(id){ var el = document.getElementById(id);'
  + '   return el ? el.textContent.trim() : null; }'
  + ' var items = [];'
  + ' document.querySelectorAll("#spectate-roster .spectate-roster-item").forEach(function(el){'
  + '   items.push({ name: el.textContent.trim(), me: el.classList.contains("spectate-roster-me") }); });'
  + ' var chat = [];'
  + ' document.querySelectorAll("#spectate-chat > div").forEach(function(el){'
  + '   chat.push({ text: el.textContent.trim(),'
  + '     notice: el.classList.contains("spectate-chat-notice"),'
  + '     fromPlayer: el.classList.contains("spectate-chat-from-player"),'
  + '     error: el.classList.contains("spectate-chat-chat-error") }); });'
  + ' return {'
  + '   rosterNames: items.map(function(i){ return i.name; }),'
  + '   meRows: items.filter(function(i){ return i.me; }).map(function(i){ return i.name; }),'
  + '   rosterCount: txt("spectate-roster-count"),'
  + '   topCount: txt("spectate-count"), topLimit: txt("spectate-limit"),'
  + '   chat: chat,'
  + '   me: sp.me || null,'
  + '   rosterState: (sp.roster || []).length,'
  + '   chatInputExists: !!document.getElementById("spectate-chat-input"),'
  + '   sendBtnExists: !!document.getElementById("spectate-chat-send"),'
  + ' }; })()';

// 观战屏上"当前连锁"这一块的文本（第 4 批用它证"打出的牌实时可见"）
const SPECTATE_CHAIN_PROBE = '(function(){'
  + ' var el = document.getElementById("spectate-chain");'
  + ' var items = [];'
  + ' document.querySelectorAll("#spectate-chain .spectate-chain-item").forEach(function(r){'
  + '   items.push({ text: r.textContent.trim(),'
  + '     negated: r.classList.contains("spectate-chain-negated") }); });'
  + ' return { raw: el ? el.textContent.trim() : null, items: items }; })()';

const SPECTATE_LOG_PROBE = '(function(){'
  + ' var out = [];'
  + ' document.querySelectorAll("#spectate-logs .spectate-log-item").forEach(function(r){'
  + '   out.push(r.textContent.trim()); });'
  + ' return out; })()';

// 在观战屏的输入框里打字并按「发送」按钮（**真的点按钮**，顺带验绑没绑上）
const SEND_SPECTATE_CHAT = (text) => '(function(){'
  + ' var box = document.getElementById("spectate-chat-input");'
  + ' var btn = document.getElementById("spectate-chat-send");'
  + ' if (!box || !btn) return { sent: false, reason: "no input/button" };'
  + ' box.value = ' + jsStr(text) + ';'
  + ' btn.click();'
  + ' return { sent: true }; })()';

// 玩家侧发言（对局屏里的聊天框：`#in-game-chat-input` + `#in-game-chat-send`）
const SEND_PLAYER_CHAT = (text, roomId) => '(function(){'
  + ' var box = document.getElementById("in-game-chat-input");'
  + ' if (!box) return { sent: false, reason: "no #in-game-chat-input" };'
  + ' box.value = ' + jsStr(text) + ';'
  + ' if (window.gameState) window.gameState.roomId = ' + jsStr(roomId) + ';'
  + ' var btn = document.getElementById("in-game-chat-send");'
  + ' if (btn) { btn.click(); return { sent: true, via: "button" }; }'
  + ' return { sent: false, reason: "no #in-game-chat-send" }; })()';

// 玩家对局屏上"对方说的话"有没有出现（对照腿：证明玩家的聊天路径没被我改坏）
const PLAYER_CHAT_PROBE = '(function(){'
  + ' var out = [];'
  + ' document.querySelectorAll("#in-game-chat-messages .in-game-chat-message").forEach(function(el){'
  + '   out.push({ text: el.textContent.trim(),'
  + '     mine: el.classList.contains("me") }); });'
  + ' return out; })()';

// 甲往自己手牌里塞一张指定卡（**测试事件**，需要 ENABLE_TEST_EVENTS=1）。
const ADD_CARD = (roomId, pid, name) => 'new Promise(function(res){'
  + ' gameState.socket.emit("test_add_specific_magic_card", { room_id: ' + jsStr(roomId)
  + ', player_id: ' + jsStr(pid) + ', card_name: ' + jsStr(name) + ' },'
  + ' function(r){ res(r); }); })';

// 打出一张魔法卡（真事件 `use_magic_card`）。本脚本选的卡**不需要任何目标**，
// 所以不带 targets。
const PLAY_CARD = (roomId, pid, name, speed) => 'new Promise(function(res){'
  + ' gameState.socket.emit("use_magic_card", { room_id: ' + jsStr(roomId)
  + ', player_id: ' + jsStr(pid) + ', card: { name: ' + jsStr(name)
  + ', speed: ' + speed + ' }, targets: [] }, function(r){ res(r); }); })';

// 连锁响应（真事件 `chain_response`）——同样不需要目标。
const CHAIN_RESPOND = (roomId, pid, name, speed) => 'new Promise(function(res){'
  + ' gameState.socket.emit("chain_response", { room_id: ' + jsStr(roomId)
  + ', player_id: ' + jsStr(pid) + ', chain: true, card: { name: ' + jsStr(name)
  + ', speed: ' + speed + ' }, targets: [] }, function(r){ res(r); }); })';

// 读服务端真相：当前连锁栈里有哪几张卡（**玩家侧**接口，用来把期望值钉死）
//
// ⚠️ `test_get_game_state` 把 `ChainItem` 序列化成 `{'player_id','card','targets',…}`，
//    而 `card` 是 `MagicCard` **实例** —— 它进了 JSON 之后字段名是 `name`/`speed`，
//    但**键名/嵌套形状随实现而变**，拿它当断言就会变成"断言序列化细节"。
//    所以这里**只取条数**（与观众侧条数对齐），卡名由**观众那一侧**（连锁区的文本）
//    来断言 —— 那正是本批要证的东西。
const READ_CHAIN = (roomId) => 'new Promise(function(res){'
  + ' gameState.socket.emit("test_get_game_state", { room_id: ' + jsStr(roomId) + ' },'
  + ' function(x){ var g = x && x.game_state;'
  + '   res(g ? { chain_len: (g.chain || []).length, state: g.state,'
  + '     seats: (g.chain || []).map(function(c){ return c && c.player_id ? "p" : "?"; }) }'
  + '     : x); }); })';

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
/** 每一步都打一行进度：这个工具最贵的失败是"只印了一条就中断"—— 
 *  从输出里看不出卡在哪一步（实测踩过两次，两次的根因完全不同）。 */
function step(text) { console.log('---- ' + text); }

let A = null, B = null, C = null, D = null;
const stamp = Date.now().toString(36);
const USER_A = 'specA' + stamp;
const USER_B = 'specB' + stamp;
const USER_C = 'specC' + stamp;
const USER_D = 'specD' + stamp;
const PASS = 'spec-pass-1234';

try {
  step('启动四个无头浏览器（甲/乙 玩家 · 丙/丁 观众）');
  A = await launch('spectate_check_a_profile', 9370);
  B = await launch('spectate_check_b_profile', 9371);
  C = await launch('spectate_check_c_profile', 9372);
  D = await launch('spectate_check_d_profile', 9373);
  for (const br of [A, B, C, D]) {
    await br.send('Page.enable');
    await br.send('Runtime.enable');
    await br.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    br.navigate('Page.navigate', { url: APP }, 1500);
  }
  for (const br of [A, B, C, D]) {
    const ready = await br.awaitReady(30000);
    check(ready === true, '（前提）' + br.tag + ' 页面加载完成', ready);
  }

  // --- 1. 前置：四个登录账号 -----------------------------------------------
  step('注册并登录四个账号');
  for (const [br, user] of [[A, USER_A], [B, USER_B], [C, USER_C], [D, USER_D]]) {
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
  step('重载四个页面并等 socket');
  for (const br of [A, B, C, D]) {
    br.navigate('Page.reload', {}, 1500);
  }
  for (const br of [A, B, C, D]) {
    const ready = await br.awaitReady(30000);
    check(ready === true, '（前提）' + br.tag + ' 重载后页面就绪', ready);
    let ok = false;
    for (let i = 0; i < 3 && !ok; i++) {
      ok = (await br.ev(SOCKET_READY, 30000)) === true;
      if (!ok) await sleep(1500);
    }
    check(ok === true, '（前提）' + br.tag + ' 的 socket 已连接', ok);
  }
  for (const [br, user] of [[A, USER_A], [B, USER_B], [C, USER_C], [D, USER_D]]) {
    const api = await br.ev(READ_SETTING_API);
    check(!!api && api.success === true && api.allow_spectate === true,
      '（前提）' + br.tag + '（' + user + '）默认允许被观战', api);
  }

  // ★★ 在**两个玩家**的页面上装原始收件记录器。
  //    这是本批"玩家收不到观战席聊天/名单"那条断言的**独立证据**：
  //    它记的是这条连接真的收到了哪些事件（不是"我们看代码觉得它收不到"）。
  for (const br of [A, B]) {
    const t = await br.ev(TAP, 15000);
    check(!!t && t.tapped === true, '（前提）' + br.tag + '（玩家）装了原始收件记录器', t);
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

  // =========================================================================
  // ★★ 第 4 批 A：观战席名单 + 观战席聊天（**两侧都要断言**）
  // =========================================================================
  // 这一段刻意排在"设置面开关"之前 —— 开关那一段会把玩家从观战列表里摘掉，
  // 而本段要的是"三个人都在正常状态"。
  step('第 4 批：丁进席 → 丙实时看到名单；观战席聊天与玩家聊天的可见范围');
  await D.ev(ENTER_LOBBY);
  await D.waitFor(async () => await D.ev('gameState.lobbySubscribed === true && !!gameState.lobbyKey'),
    15000, '丁订阅大厅');
  await D.waitFor(async () => {
    const rows = await D.ev(MATCH_ROWS);
    return Array.isArray(rows) && rows.some((r) => r.roomId === roomId);
  }, 25000, '丁的「进行中的对局」里出现这一局');
  // ⚠️ 必须**点真按钮**（走 `joinSpectate`），不能只 emit `spectate_join` ——
  //    后者只把服务端席位坐下来，页面侧的 `gameState.spectate.active` 永远是 false，
  //    于是 `spectateActive()` 门禁把观众侧全部事件挡在门外（实测踩过一次：
  //    症状是"服务端 ack 成功、页面毫无反应"，看起来像服务端没发）。
  const dClicked = await D.ev('(function(){'
    + ' var rows = document.querySelectorAll("#lobby-matches-list .lobby-match");'
    + ' for (var i = 0; i < rows.length; i++) {'
    + '   var b = rows[i].querySelector(".lobby-match-spectate");'
    + '   if (b && b.dataset.room === ' + jsStr(roomId) + ') { b.click(); return true; }'
    + ' } return false; })()');
  check(dClicked === true, '丁点到了那一局的「观战」按钮', dClicked);
  await D.waitFor(async () => await D.ev('!!(gameState.spectate && gameState.spectate.active)'),
    20000, '丁进席');

  // ★ 丙**不刷新页面**，名单里就该多出丁的名字
  let social = null;
  try {
    await C.waitFor(async () => {
      const p = await C.ev(SPECTATE_SOCIAL_PROBE);
      return p.rosterNames.indexOf(USER_D) >= 0;
    }, 15000, '丙的名单里出现丁');
    social = await C.ev(SPECTATE_SOCIAL_PROBE);
    check(true, '★★ 丁进席后，丙**不刷新页面**就在名单里看到了丁的名字', social.rosterNames);
  } catch (e) {
    social = await C.ev(SPECTATE_SOCIAL_PROBE);
    check(false, '★★ 丁进席后，丙的观战席名单里应当实时出现丁的名字', social);
  }
  check(!!social && social.rosterNames.indexOf(USER_C) >= 0
    && social.rosterNames.indexOf(USER_D) >= 0,
    '★ 名单里同时有两位观众（顺序 = 入席顺序）', social && social.rosterNames);
  check(!!social && social.rosterCount === '(2/20)' && social.topCount === '2'
    && social.topLimit === '20',
    '★ 名单区与顶栏的人数都是 2/20（上限来自服务端）', social);
  check(!!social && social.me === USER_C && social.meRows.length === 1
    && social.meRows[0] === USER_C,
    '★ 名单里"哪一行是我"标在自己那一行上（显示名来自服务端的 spectate_you）',
    social && { me: social.me, meRows: social.meRows });
  check(!!social && social.chatInputExists === true && social.sendBtnExists === true,
    '★ 观战屏上有聊天输入框与发送按钮（id 与 index.html 对得上）', social);

  // --- 观战席聊天：丁说话 → 丙收到 ---
  const CHAT_D = '丁在观战席说的话';
  const sentD = await D.ev(SEND_SPECTATE_CHAT(CHAT_D));
  check(!!sentD && sentD.sent === true, '丁点了观战屏上的「发送」（真按钮）', sentD);
  let chatSeen = false;
  try {
    await C.waitFor(async () => {
      const p = await C.ev(SPECTATE_SOCIAL_PROBE);
      return p.chat.some((m) => m.text.indexOf(CHAT_D) >= 0 && !m.notice);
    }, 15000, '丙收到丁的观战席发言');
    chatSeen = true;
  } catch (e) { /* 下面统一报 */ }
  check(chatSeen === true, '★★ 丁的观战席发言实时出现在丙的聊天区（不刷新页面）');

  // --- 玩家之间的聊天：观众**看得到**（第 1 批就登记好的承诺）---
  const CHAT_A = '甲在对局里说的话';
  const sentA = await A.ev(SEND_PLAYER_CHAT(CHAT_A, roomId));
  check(!!sentA && sentA.sent === true, '甲在对局屏的聊天框里发了言（真按钮）', sentA);
  let playerChatSeen = false;
  try {
    await C.waitFor(async () => {
      const p = await C.ev(SPECTATE_SOCIAL_PROBE);
      return p.chat.some((m) => m.text.indexOf(CHAT_A) >= 0 && m.fromPlayer === true);
    }, 15000, '丙看到玩家之间的聊天');
    playerChatSeen = true;
  } catch (e) { /* 下面统一报 */ }
  check(playerChatSeen === true,
    '★★ 玩家在对局里说的话**观众看得到**（这是第 4 批修掉的真缺陷：原本 to=sid 单发，观众一个字节都收不到）');

  // --- 对照腿：乙自己也收得到甲的发言（证明玩家那条路径没被改坏）---
  let bSawChat = false;
  try {
    await B.waitFor(async () => {
      const rowsB = await B.ev(PLAYER_CHAT_PROBE);
      return rowsB.some((m) => m.text.indexOf(CHAT_A) >= 0);
    }, 10000, '乙收到甲的聊天');
    bSawChat = true;
  } catch (e) { /* 下面统一报 */ }
  check(bSawChat === true, '（对照腿）乙（另一个玩家）也收到了甲的聊天 —— 玩家路径没被改坏');
  const bChatRows = await B.ev(PLAYER_CHAT_PROBE);
  check(bChatRows.filter((m) => m.text.indexOf(CHAT_A) >= 0).length === 1,
    '（对照腿）乙**只收到一条**（双发会在聊天区出现重复行）',
    bChatRows.filter((m) => m.text.indexOf(CHAT_A) >= 0));
  check(bChatRows.every((m) => m.mine === false || m.text.indexOf(CHAT_A) < 0),
    '★ 乙那边甲的话不是"我说的"（isMe 由前端按名字判，没被服务端广播写坏）', bChatRows);

  // --- ★★ 主断言：**两个玩家都收不到观战席聊天**（用原始收件记录器，独立证据）---
  for (const br of [A, B]) {
    const dump = await br.ev(TAP_DUMP);
    const who = br === A ? '甲' : '乙';
    check(!!dump && dump.total > 0,
      '（对照腿）' + who + ' 的收件记录器**真的在记东西**（total=' + (dump && dump.total) + '）',
      dump && { total: dump.total, sample: Object.keys(dump.events).slice(0, 8) });
    check(!!dump && !dump.events['spectate_chat'],
      '★★ ' + who + '（对局玩家）**一次都没收到** spectate_chat',
      dump && dump.events);
    check(!!dump && !dump.events['spectate_roster'],
      '★★ ' + who + '（对局玩家）**一次都没收到** spectate_roster（名单）',
      dump && dump.events);
    check(!!dump && !dump.events['spectate_joined'] && !dump.events['spectate_left'],
      '★★ ' + who + '（对局玩家）也没收到观众进出的播报',
      dump && dump.events);
    check(!!dump && !!dump.events['spectate_count_changed'],
      '★ ' + who + '（对局玩家）**只**收到人数变化（这是他该看到的）',
      dump && dump.events);
  }

  // =========================================================================
  // ★★ 第 4 批 B：两条动作流 —— **打出的牌** 与 **连锁响应** 实时可见
  // =========================================================================
  // 为什么专门补这一节：第 3 批的 E2E 只覆盖了「开炮」，而作者最看重的
  // 「所有动作都看得到」里，"打出的牌 / 连锁响应"正是最典型的动作。
  // 第 3 批只读了代码（`magic_chain_updated` 在 `SPECTATE_EVENTS` 表里），没有实测。
  step('第 4 批：打出魔法卡 → 观众实时看到；连锁响应 → 观众实时看到');

  // 用**测试事件**把手牌钉死，避免"开局抽到什么牌"这种随机性让断言飘。
  // ⚠️ 这是调试事件（需要 ENABLE_TEST_EVENTS=1），只在工具里用。
  const addA = await atkTab.ev(ADD_CARD(roomId, atkPid, '无中生有'));
  check(!!addA && addA.status === 'success', '（前提）给攻击方塞了一张「无中生有」', addA);
  const defTab = atkTab === A ? B : A;
  const defPid = atkTab === A ? bPid : aPid;
  const addB = await defTab.ev(ADD_CARD(roomId, defPid, '失灵！'));
  check(!!addB && addB.status === 'success', '（前提）给防守方塞了一张「失灵！」', addB);

  const chainBefore = await C.ev(SPECTATE_CHAIN_PROBE);
  const logsBefore = await C.ev(SPECTATE_LOG_PROBE);

  const played = await atkTab.ev(PLAY_CARD(roomId, atkPid, '无中生有', 1));
  check(!!played && played.status === 'success', '攻击方打出了一张魔法卡「无中生有」', played);

  // ★ 丙**不刷新页面**，连锁区就该出现这张卡
  let chainAfterPlay = null;
  try {
    await C.waitFor(async () => {
      const p = await C.ev(SPECTATE_CHAIN_PROBE);
      return Array.isArray(p.items) && p.items.some((i) => i.text.indexOf('无中生有') >= 0);
    }, 15000, '丙的连锁区出现这张卡');
    chainAfterPlay = await C.ev(SPECTATE_CHAIN_PROBE);
    check(true, '★★ 打出一张魔法卡后，丙**不刷新页面**就在连锁区看到了它',
      chainAfterPlay.items);
  } catch (e) {
    chainAfterPlay = await C.ev(SPECTATE_CHAIN_PROBE);
    check(false, '★★ 打出的魔法卡应当实时出现在观众的连锁区', chainAfterPlay);
  }
  check(!!chainAfterPlay && chainAfterPlay.items.some((i) => i.text.indexOf(USER_A) >= 0
    || i.text.indexOf(USER_B) >= 0),
    '★ 连锁项上写着**是谁**打出的（座位标签映射到玩家名，不是原始 sid）',
    chainAfterPlay && chainAfterPlay.items);
  const afterPlayLogs = await C.ev(SPECTATE_LOG_PROBE);
  // ⚠️ 这里**不**断言"出牌那一刻日志就多一条"：`add_game_log` 只在**连锁结算**
  //    （`log_magic`）时才写，出牌本身不写日志。写死它 = 自己造一条假红
  //    （实测踩过一次）。出牌的可观测证据在**上面那条连锁区断言**里。
  check(afterPlayLogs.length === logsBefore.length,
    '（记录）出牌那一刻日志条数不变（日志是在连锁**结算**时才写的）',
    { before: logsBefore.length, after: afterPlayLogs.length });

  // --- 连锁响应：另一个玩家的响应也要实时可见 ---
  const serverChain = await atkTab.ev(READ_CHAIN(roomId));
  check(!!serverChain && serverChain.chain_len === 1,
    '（前提）服务端连锁栈里确实有 1 张（观众看到的不是幻觉）', serverChain);

  const responded = await defTab.ev(CHAIN_RESPOND(roomId, defPid, '失灵！', 3));
  check(!!responded && responded.status === 'success', '防守方连锁响应「失灵！」', responded);

  let chainAfterResp = null;
  try {
    await C.waitFor(async () => {
      const p = await C.ev(SPECTATE_CHAIN_PROBE);
      return Array.isArray(p.items) && p.items.length >= 2
        && p.items.some((i) => i.text.indexOf('失灵') >= 0);
    }, 15000, '丙的连锁区出现第二张');
    chainAfterResp = await C.ev(SPECTATE_CHAIN_PROBE);
    check(true, '★★ 连锁响应后，丙**不刷新页面**就在连锁区看到了第二张（失灵！）',
      chainAfterResp.items);
  } catch (e) {
    chainAfterResp = await C.ev(SPECTATE_CHAIN_PROBE);
    check(false, '★★ 连锁响应应当实时出现在观众的连锁区', chainAfterResp);
  }
  const chainServer2 = await atkTab.ev(READ_CHAIN(roomId));
  check(!!chainAfterResp && !!chainServer2
    && chainAfterResp.items.length === chainServer2.chain_len,
    '★ 观众看到的连锁条数 == 服务端连锁栈的条数（不是本地瞎编的）',
    { spectator: chainAfterResp && chainAfterResp.items.length,
      server: chainServer2 && chainServer2.chain_len });

  // ⚠️ 这里**不**断言"已康"（negated）—— 那是**结算之后**才置的标记
  //    （`resolve_chain` 里把栈顶标成 negated_by）。连锁窗口有 10 秒超时，
  //    窗口内读到的本来就是"还没结算"的那一帧，写死断言 = 自造假红。
  //    本段要证的是"连锁响应这个**动作**观众实时看得到"，这一点上面已经钉住。
  const chainSeats = (chainAfterResp && chainAfterResp.items) || [];
  check(chainSeats.length === 2
    && chainSeats.map((i) => i.text).join(' | ').indexOf('失灵') >= 0
    && chainSeats.map((i) => i.text).join(' | ').indexOf('无中生有') >= 0,
    '★ 观众看到的正是那两张卡（无中生有 + 失灵！），且各带一位玩家的名字',
    chainSeats.map((i) => i.text));
  const twoPlayers = new Set(chainSeats.map((i) => {
    const m = i.text.match(/^第\d+张 · ([^：]+)：/);
    return m ? m[1] : '';
  }));
  check(twoPlayers.size === 2 && ![...twoPlayers].some((n) => !n),
    '★ 两张连锁分别挂在**两个不同的玩家**名下（座位标签映射正确，不是原始 sid）',
    [...twoPlayers]);

  // 收尾：把甲的手牌/场上效果清干净，别让这一段影响后面的开关断言
  // （无中生有会让本回合双方都摸不到牌，与后面的步骤没有关系，但清一下更干净）。
  await atkTab.ev('new Promise(function(res){ gameState.socket.emit("test_clear_all_effects",'
    + ' { room_id: ' + jsStr(roomId) + ' }, function(r){ res(r); }); })');

  // --- 丁退出 → 丙的名单里也要实时少一个人 -------------------------------
  await D.ev('(function(){ var b = document.getElementById("spectate-leave");'
    + ' if (b) b.click(); return 1; })()');
  let rosterAfterLeave = null;
  try {
    await C.waitFor(async () => {
      const p = await C.ev(SPECTATE_SOCIAL_PROBE);
      return p.rosterNames.indexOf(USER_D) < 0;
    }, 15000, '丙的名单里丁消失');
    rosterAfterLeave = await C.ev(SPECTATE_SOCIAL_PROBE);
    check(true, '★ 丁退出后，丙的名单**实时**少了丁（名单不是静态的）',
      rosterAfterLeave.rosterNames);
  } catch (e) {
    rosterAfterLeave = await C.ev(SPECTATE_SOCIAL_PROBE);
    check(false, '★ 观众退出后名单应当实时更新', rosterAfterLeave);
  }
  check(!!rosterAfterLeave && rosterAfterLeave.rosterNames.length === 1
    && rosterAfterLeave.rosterNames[0] === USER_C,
    '★ 退出后名单只剩丙，人数回到 1/20', rosterAfterLeave);

  // --- 玩家侧：断线/退出**不**该给玩家带来任何名单信息（再确认一次）---
  for (const br of [A, B]) {
    const dump = await br.ev(TAP_DUMP);
    const who = br === A ? '甲' : '乙';
    check(!!dump && !dump.events['spectate_roster'] && !dump.events['spectate_left'],
      '★★ ' + who + ' 在整段名单变化期间**始终没有**收到名单/进出播报',
      dump && dump.events);
  }

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

  // --- 9. ★ 设置面里真的关掉观战 → 列表里消失 ------------------------------
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

  // --- 10. 再打开 → 又出现 --------------------------------------------------
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

  // --- 11. 退出观战 --------------------------------------------------------
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
  check(jsProblems.length === 0, '四个页面均无 JS 异常/报错', jsProblems);
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
