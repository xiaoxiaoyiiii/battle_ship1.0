#!/usr/bin/env node
/**
 * 特权威外观 + 「本局刚解锁」结算提示的端到端回归检查（无头 Edge + CDP）。
 *
 * 覆盖三件事（都是作者 2026-09-17 点名要的）：
 *   1. **结算提示**：一局结束、真解锁了徽章时，**本人**在结算界面看到
 *      「本局刚解锁 …」；对手看不到（那条事件是单发给本人的）。
 *   2. **外观全解锁**：持有 `unlock_all_cosmetics` 的账号，编辑面里
 *      称号 / 头像框 / 名片底色**没有一个是灰的**（接口也该全 unlocked）。
 *   3. **彩虹名字**：`rainbow_name` 账号的名字在任何地方都是彩虹渐变，
 *      而且**别人打开他的名片/排行榜也看得到** —— 这里用"另一个客户端"真的去看一眼，
 *      而不是只断言自己那面（第 3 批的教训：只验自己那面会假绿）。
 *
 * ⚠️ 前置：本地服务端必须带 `ENABLE_TEST_EVENTS=1`，且库里已有一个**特权账号**
 *    （特权故意没有自助接口 —— 别人不能拥有彩虹名字，所以只能在库里授予）：
 *      python .tmp/seed_perk_user.py
 *    ⚠️ 种子脚本要在**服务端用的同一个库**上跑（同一个 BATTLESHIP_DB_PATH）。
 *
 * 用法：
 *   node tools/unlock_notice_check.mjs --url http://127.0.0.1:5011/ \
 *        --user perkvip --pass check123456
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5011/');
const USER = argOf('--user', 'perkvip');
const PASS = argOf('--pass', 'check123456');
const SIZE = (argOf('--size', '1600x1000') || '1600x1000').split('x').map((n) => parseInt(n, 10));
const PORT = 9402;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(HERE, '..', '.tmp', 'unlock_notice_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

try {
  execSync('powershell -NoProfile -Command "' +
    'Get-CimInstance Win32_Process -Filter \\"Name=\'msedge.exe\'\\" | ' +
    'Where-Object { $_.CommandLine -like \'*unlock_notice_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没残留就够了 */ }

const problems = [];
const jsProblems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

let browser = null;
let browserB = null;

async function openTab(port, url) {
  await sleep(300);
  const t = await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let seq = 0; const pend = new Map();
  ws.onmessage = (m) => {
    const x = JSON.parse(m.data);
    if (x.id && pend.has(x.id)) { const { res, rej } = pend.get(x.id); pend.delete(x.id); x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result); return; }
    if (x.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(x.params.exceptionDetails).slice(0, 160));
    if (x.method === 'Runtime.consoleAPICalled' && x.params.type === 'error') {
      jsProblems.push('console.error: ' + x.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 140));
    }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const id = ++seq; pend.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
  });
  await send('Runtime.enable'); await send('Page.enable');
  const ev = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 250) };
    return r.result && r.result.value;
  };
  const front = async () => { try { await send('Page.bringToFront'); } catch (e) {} await sleep(200); };
  return {
    ev, send, front,
    ready: async () => {
      const t0 = Date.now();
      while (Date.now() - t0 < 25000) {
        if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true;
        await sleep(250);
      }
      return false;
    },
  };
}

async function goto(tab, url, expect) {
  await tab.send('Page.navigate', { url });
  const want = (expect || url).replace(/\/$/, '');
  const t0 = Date.now();
  while (Date.now() - t0 < 30000) {
    const st = await tab.ev('({ href: location.href.replace(/\\/$/, ""), ready: document.readyState })');
    if (st && st.ready === 'complete' && st.href === want) break;
    await sleep(200);
  }
  await sleep(400);
}

const AUTH = (user, pass) => `
(async function () {
  var r = await fetch('/login', { method: 'POST', redirect: 'follow',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: ${JSON.stringify(user)}, password: ${JSON.stringify(pass)} }).toString() });
  var t = await r.text();
  return t.indexOf('登录成功') >= 0 ? 'login-ok' : ('login-failed: ' + t.replace(/\\s+/g, ' ').slice(0, 90));
})()`;

const OPEN_PROFILE = (name) => `(async function () {
  if (typeof window.showUserProfile !== 'function') return 'no-fn';
  window.showUserProfile(${JSON.stringify(name)});
  for (var i = 0; i < 80; i++) {
    if (document.querySelector('#opponent-stats-content #profile-view')) return 'ok';
    await new Promise(function (r) { setTimeout(r, 200); });
  }
  return 'no-view'; })()`;

// 名字是否**真的**渲染成渐变：不能只看有没有那个类，
// 要看计算后的 background-image 里有没有 gradient（类加了但样式没生效 = 假绿）
const NAME_STYLE = `(function () {
  var el = document.querySelector('#opponent-stats-content #profile-view-name');
  if (!el) return { missing: true };
  var cs = getComputedStyle(el);
  return { cls: el.className, text: (el.textContent || '').trim().slice(0, 20),
    bg: (cs.backgroundImage || '').slice(0, 60),
    isGradient: /gradient/i.test(cs.backgroundImage || '') }; })()`;

try {
  // ⚠️ **两个独立的浏览器进程**，不是同一个浏览器的两个标签页。
  //    同一个浏览器 profile 里**所有标签页共享 cookie** —— B 那个"游客"标签页
  //    实际上带着 A 的登录态（第一次跑就是这样：B 入座返回的 player_id 居然是 A 的 uid，
  //    房间因此塌成一个人，后面全部超时）。要造"别人视角"就必须隔离 profile。
  const launch = (port, dir) => spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run',
    '--no-default-browser-check', '--mute-audio', '--remote-debugging-port=' + port,
    '--user-data-dir=' + dir, '--window-size=' + SIZE[0] + ',' + SIZE[1], 'about:blank'], { stdio: 'ignore' });
  browser = launch(PORT, PROFILE_DIR);
  browserB = launch(PORT + 1, PROFILE_DIR + '_other');
  await sleep(4500);

  const A = await openTab(PORT, APP);          // 特权账号（已登录）
  const B = await openTab(PORT + 1, APP);      // 真正的游客（独立 profile，没有登录态）
  check(await A.ready() && await B.ready(), '0 两个客户端就绪（两个独立浏览器 profile）');

  // ---------- 1. 登录 + 接口层：catalog 全解锁、name_style 下发 ----------
  const auth = await A.ev(AUTH(USER, PASS));
  check(typeof auth === 'string' && auth === 'login-ok', '1 特权账号登录', auth);
  // ⚠️ 登录是 fetch 做的，**必须重新加载页面**：
  //     socket 的身份是「连接握手那一刻的 session」，不刷新的话这条连接仍然是**游客**，
  //     于是结算时服务端拿不到 user_id → 不给这个账号记徽章（这正是我第一次跑时
  //     卡在摆船那一步、以及"结算没反应"的根因）。
  await goto(A, APP);
  check(await A.ready(), '1b 登录后重载页面（socket 才会带上登录身份）');
  const prof = await A.ev(`fetch('/api/profile').then(r => r.json()).catch(e => ({ __err: String(e) }))`);
  const p = (prof && prof.profile) || {};
  check(p.username === USER, '2 /api/profile 是本人', p.username);
  check(String(p.name_style || '') === 'rainbow', '★ 3 接口下发 name_style=rainbow', p.name_style);
  const cat = p.catalog || {};
  const lockedCounts = {
    titles: (cat.titles || []).filter((x) => x.unlocked === false).length,
    frames: (cat.frames || []).filter((x) => x.unlocked === false).length,
    bgs: (cat.card_bgs || []).filter((x) => x.unlocked === false).length,
  };
  check(lockedCounts.titles === 0 && lockedCounts.frames === 0 && lockedCounts.bgs === 0,
    '★ 4 接口层：称号 / 头像框 / 底色**一个都没锁着**', { lockedCounts, n: {
      t: (cat.titles || []).length, f: (cat.frames || []).length, b: (cat.card_bgs || []).length } });

  // ---------- 2. 自己名片：名字真是彩虹 ----------
  check(await A.ev(OPEN_PROFILE(USER)) === 'ok', '5 打开自己的名片');
  const mine = await A.ev(NAME_STYLE);
  check(mine && mine.cls && mine.cls.indexOf('name-rainbow') >= 0,
    '★ 6 自己名片上的名字带 name-rainbow', mine && mine.cls);
  check(mine && mine.isGradient === true, '★ 7 而且**真的**渲染成渐变（computed background-image 里有 gradient）', mine && mine.bg);

  // ---------- 3. 别人视角：彩虹名字也看得到 ----------
  await B.front();
  check(await B.ev(OPEN_PROFILE(USER)) === 'ok', '8 游客打开同一个人的名片（别人视角）');
  const other = await B.ev(NAME_STYLE);
  check(other && other.cls && other.cls.indexOf('name-rainbow') >= 0 && other.isGradient === true,
    '★★ 9 别人眼中**也能看到**彩虹名字（不是只给自己看）', other && { cls: other.cls, bg: other.bg });

  // ---------- 4. 编辑面：没有任何灰掉的选项 ----------
  await A.front();
  const editor = await A.ev(`(async function () {
    var b = document.getElementById('show-profile'); if (b) b.click();
    for (var i = 0; i < 60; i++) { var e = document.querySelector('#profile-edit-btn'); if (e) { e.click(); break; }
      await new Promise(function (r) { setTimeout(r, 150); }); }
    // ⚠️ 等到**选项真的填进去**为止：#profile-title-list 这个容器在编辑面渲染出来时
    //    就已经存在，但里面的按钮是数据到位后才 innerHTML 填的 —— 只等容器会让
    //    "数一数有几个灰的"数出 0 个（看着像"全解锁"，其实是一个都没渲染）。
    //    （注释里不要用反引号：这段是模板字符串，反引号会提前把它闭合掉。）
    for (var j = 0; j < 80; j++) {
      var n = document.querySelectorAll('#profile-title-list .pf-opt').length;
      var f = document.querySelectorAll('#profile-frame-row .pf-frame').length;
      if (n > 0 && f > 0) return 'ok';
      await new Promise(function (r) { setTimeout(r, 150); });
    }
    return 'no-options'; })()`);
  check(editor === 'ok', '10 打开编辑面', editor);
  const opts = await A.ev(`(function () {
    var count = function (sel) { var all = [].slice.call(document.querySelectorAll(sel));
      return { total: all.length, locked: all.filter(function (b) { return b.disabled || b.classList.contains('locked'); }).length }; };
    return { titles: count('#profile-title-list .pf-opt'),
             frames: count('#profile-frame-row .pf-frame'),
             bgs: count('#profile-bg-row .pf-bg') }; })()`);
  check(opts && opts.titles.total > 0 && opts.titles.locked === 0,
    '★ 11 编辑面里没有灰掉的称号（全解锁）', opts && opts.titles);
  check(opts && opts.frames.locked === 0, '★ 12 编辑面里没有灰掉的头像框', opts && opts.frames);
  check(opts && opts.bgs.locked === 0, '★ 13 编辑面里没有灰掉的名片底色', opts && opts.bgs);
  await A.ev(`(function () { var b = document.getElementById('profile-modal-close'); if (b) b.click(); return true; })()`);

  // ---------- 5. 结算提示：真打一局（对手投降 → 本人获胜 → 解锁首胜） ----------
  const created = await A.ev(`new Promise(function(res){ ensureSocket(); gameState.playerName = ${JSON.stringify(USER)};
    gameState.socket.emit('create_room', { player_name: ${JSON.stringify(USER)} }, function(r){ res(r); }); })`);
  const roomId = created && created.room_id;
  check(!!roomId, '14 建房成功', created);
  const joined = await B.ev(`new Promise(function(res){ ensureSocket(); gameState.playerName = 'PerkB';
    gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name: 'PerkB' }, function(r){ res(r); }); })`);
  const bPid = joined && joined.player_id;
  check(!!bPid, '15 对手（游客）入座', bPid);
  // ⚠️ `create_room` 的 ack **不返回 player_id**（只有 room_id）。自定义房里登录玩家的座位 key
  //    就是 `session['user_id']`（CLAUDE.md §6），所以 A 的 player_id 就是自己的 uid —— 从
  //    /api/profile 拿。
  //    第一版用了 `created.player_id`（undefined）→ 摆船的 payload 里没有 player_id
  //    → 服务端 `data['player_id']` KeyError → **不回 ack** → 工具在 Runtime.evaluate 上超时。
  //    症状像"浏览器卡住"，真凶在服务端日志里（`.tmp/perk_tool_server.log`）。
  const aPid = String(p.id || '');
  check(!!aPid, '15b 本人座位 key（自定义房 = 自己的 uid）', aPid);
  await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; gameState.playerId = ${JSON.stringify(aPid)}; true`);
  await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; gameState.playerId = ${JSON.stringify(bPid)}; true`);
  const ships = (seed) => Array.from({ length: 6 }, (_, i) => ({ positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [] }));
  await A.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: gameState.roomId,
    player_id: gameState.playerId, ships: ${JSON.stringify(ships(0))} }, function(r){ res(r); }); })`);
  await B.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: gameState.roomId,
    player_id: gameState.playerId, ships: ${JSON.stringify(ships(1))} }, function(r){ res(r); }); })`);
  // 游客投降 → 特权账号获胜 → 走 _finalize_match（真实结算路径）
  const sur = await B.ev(`new Promise(function(res){ gameState.socket.emit('surrender', { room_id: gameState.roomId,
    player_id: gameState.playerId }, function(r){ res(r); }); })`);
  check(!!sur, '16 对手投降（真实结算入口）', sur && (sur.status || Object.keys(sur).join(',')));
  await sleep(1800);

  await A.front();
  const panel = await A.ev(`(function () {
    var el = document.getElementById('achievement-unlock-panel');
    if (!el) return 'missing';
    var r = el.getBoundingClientRect();
    return { visible: !el.classList.contains('hidden') && r.width > 0 && r.height > 0,
      text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
      items: el.querySelectorAll('.au-item').length }; })()`);
  check(panel && panel !== 'missing' && panel.visible === true,
    '★★ 17 本人结算界面出现「本局刚解锁」面板', panel);
  check(panel && /本局刚解锁/.test(panel.text || '') && /首胜/.test(panel.text || ''),
    '★★ 18 面板文案写明本局解锁了哪几枚（含首胜）', panel && panel.text);
  const logA = await A.ev(`(function () { var b = document.getElementById('game-logs');
    return b ? (b.textContent || '').indexOf('本局解锁了新徽章') >= 0 : 'no-log'; })()`);
  check(logA === true, '19 对局日志里也留了一行（本局解锁了新徽章）', logA);

  await B.front();
  const panelB = await B.ev(`(function () { var el = document.getElementById('achievement-unlock-panel');
    if (!el) return 'missing';
    var r = el.getBoundingClientRect();
    return { visible: !el.classList.contains('hidden') && r.width > 0 && r.height > 0,
      items: el.querySelectorAll('.au-item').length }; })()`);
  check(panelB && panelB !== 'missing' && panelB.visible === false,
    '★ 20 对手**看不到**本人的结算提示（那条事件是单发的）', panelB);

  // ---------- 6. 排行榜：别人也能看到彩虹名字 ----------
  const board = await B.ev(`fetch('/api/leaderboard?limit=100').then(r => r.json()).catch(e => [])`);
  const row = (board || []).find((x) => String(x.username) === USER);
  check(!!row, '21 排行榜里有这个账号', row && row.username);
  check(row && String(row.name_style || '') === 'rainbow',
    '★★ 22 排行榜接口逐行下发 name_style（别人看榜也看得到）', row && row.name_style);
  check(row && Number(row.wins) >= 1, '23 这一局真的记进战绩了（wins ≥ 1）', row && row.wins);

  check(jsProblems.length === 0, 'Z1 全程零 JS 异常 / 零 console.error', jsProblems.slice(0, 4));
} catch (e) {
  check(false, '工具执行异常', e.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) {}
  try { if (browserB) browserB.kill(); } catch (e) {}
}

console.log('');
if (problems.length) {
  console.log('UNLOCK NOTICE CHECK FAILED (' + problems.length + '): ' + problems.join(' | '));
  process.exit(1);
}
console.log('UNLOCK NOTICE CHECK PASSED');
process.exit(0);
