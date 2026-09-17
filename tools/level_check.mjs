#!/usr/bin/env node
/**
 * 等级 / 经验 / 匹配成功界面 的端到端回归检查（无头 Edge + CDP，两个**独立浏览器**）。
 *
 * 覆盖作者 2026-09-17 提的三件事：
 *   1. **匹配成功的 5 秒等待界面**要能看到对手的**称号 / 标签 / 等级**；
 *   2. **等级 + 经验条**：首页能看到自己的等级与经验；
 *   3. **结算经验动画**：显示本局获得多少经验，条子滚动加上去，
 *      **升级时条子清空重来再继续加**（并闪一下"升级！Lv.N → Lv.N+1"）。
 *   另外顺带验：持 `level_101` 特权的账号上限是 **101**（别人在等待界面就能看到他 Lv.101）。
 *
 * ⚠️ 前置（本地服务端 + 同一个库）：
 *      python .tmp/seed_level_users.py
 *    · `perkvip` → Lv.101（持全部特权）——扮演"对手"，也是等待界面里被看的那个
 *    · `levela`  → Lv.1（经验 30，离升级只差 5 点）——扮演"我"，用来触发升级动画
 *   ⚠️ 等级曲线与"这一局加多少经验"都在服务端（`leveling.py`），本工具**不重算**，
 *      只断言"界面上显示的东西与接口下发的一致"。
 *
 * 用法：
 *   node tools/level_check.mjs --url http://127.0.0.1:5011/ [--size 1600x1000]
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5011/');
const ME = argOf('--me', 'levela');
const FOE = argOf('--foe', 'perkvip');
const PASS = argOf('--pass', 'check123456');
const SIZE = (argOf('--size', '1600x1000') || '1600x1000').split('x').map((n) => parseInt(n, 10));
const PORT = 9412;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROF_A = path.join(HERE, '..', '.tmp', 'level_check_profile_me');
const PROF_B = path.join(HERE, '..', '.tmp', 'level_check_profile_foe');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

try {
  execSync('powershell -NoProfile -Command "' +
    'Get-CimInstance Win32_Process -Filter \\"Name=\'msedge.exe\'\\" | ' +
    'Where-Object { $_.CommandLine -like \'*level_check_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没残留就够了 */ }

const problems = [];
const jsProblems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

let brA = null, brB = null;

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

const AUTH = (user) => `
(async function () {
  var r = await fetch('/login', { method: 'POST', redirect: 'follow',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: ${JSON.stringify(user)}, password: ${JSON.stringify(PASS)} }).toString() });
  var t = await r.text();
  return t.indexOf('登录成功') >= 0 ? 'login-ok' : ('login-failed: ' + t.replace(/\\s+/g, ' ').slice(0, 80));
})()`;

const STRIP_STATE = `(function () {
  var s = document.getElementById('my-level-strip');
  if (!s) return { missing: true };
  var fill = document.getElementById('mls-fill');
  return { visible: !s.classList.contains('hidden'),
    level: (document.getElementById('mls-level') || {}).textContent || '',
    text: (document.getElementById('mls-text') || {}).textContent || '',
    fillPct: fill ? (fill.style.width || '') : '' }; })()`;

const XP_PANEL = `(function () {
  var p = document.getElementById('xp-gain-panel');
  if (!p) return { missing: true };
  var r = p.getBoundingClientRect();
  var fill = document.getElementById('xp-bar-fill');
  return { visible: !p.classList.contains('hidden') && r.width > 0,
    delta: (document.getElementById('xp-delta') || {}).textContent || '',
    levelNow: (document.getElementById('xp-level-now') || {}).textContent || '',
    progress: (document.getElementById('xp-progress-text') || {}).textContent || '',
    breakdown: (document.getElementById('xp-breakdown') || {}).textContent || '',
    fillPct: fill ? (fill.style.width || '') : '',
    levelUpShown: (function () { var u = document.getElementById('xp-levelup');
      return !!u && !u.classList.contains('hidden'); })(),
    levelUpText: (function () { var u = document.getElementById('xp-levelup');
      return u ? (u.textContent || '').replace(/\\s+/g, ' ').trim() : ''; })() }; })()`;

try {
  const launch = (port, dir) => spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run',
    '--no-default-browser-check', '--mute-audio', '--remote-debugging-port=' + port,
    '--user-data-dir=' + dir, '--window-size=' + SIZE[0] + ',' + SIZE[1], 'about:blank'], { stdio: 'ignore' });
  brA = launch(PORT, PROF_A);
  brB = launch(PORT + 1, PROF_B);
  await sleep(4500);

  const A = await openTab(PORT, APP);          // 我（levela，Lv.1，离升级 5 点）
  const B = await openTab(PORT + 1, APP);      // 对手（perkvip，Lv.101）
  check(await A.ready() && await B.ready(), '0 两个客户端就绪（两个独立浏览器 profile）');

  // ---------- 登录（登录后必须重载，socket 才带登录身份） ----------
  check(await A.ev(AUTH(ME)) === 'login-ok', '1 我登录 ' + ME);
  await goto(A, APP); check(await A.ready(), '1b 我重载页面');
  check(await B.ev(AUTH(FOE)) === 'login-ok', '2 对手登录 ' + FOE);
  await goto(B, APP); check(await B.ready(), '2b 对手重载页面');

  // ---------- 对手先给自己挂上称号与标签（它有全解锁特权，随便选） ----------
  const saved = await B.ev(`fetch('/api/profile/card', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title_id: 'immortal', tags: ['aggressive', 'nightowl'], status_text: '等你来打',
      frame_id: 'crimson', card_bg_id: 'aurora', show_stats: 1, show_fav_cards: 1, show_history: 0, show_guestbook: 1 }) })
    .then(r => r.json()).catch(e => ({ __err: String(e) }))`);
  check(saved && saved.success === true, '3 对手设置称号 + 两个标签', saved && (saved.success || saved.error));

  const foeStats = await A.ev(`fetch('/user_stats?username=' + encodeURIComponent(${JSON.stringify(FOE)}))
    .then(r => r.json()).catch(e => ({}))`);
  const foeLevel = foeStats && foeStats.stats && foeStats.stats.level_info && foeStats.stats.level_info.level;
  check(foeLevel === 101, '★ 4 对手是 Lv.101（持 level_101 特权，普通账号封顶 100）', foeLevel);

  // ---------- 1. 首页的等级条（我） ----------
  const strip0 = await A.ev(STRIP_STATE);
  check(strip0 && strip0.visible === true, '★ 5 首页显示我的等级条', strip0);
  check(strip0 && strip0.level === '1', '★ 6 我的等级是 Lv.1', strip0 && strip0.level);
  check(strip0 && /^\d+ \/ \d+$/.test(strip0.text || ''), '★ 7 等级条上写着本级进度（x / y）', strip0 && strip0.text);

  // ---------- 2. 匹配成功界面：对手的等级 / 称号 / 标签 ----------
  const created = await B.ev(`new Promise(function(res){ ensureSocket(); gameState.playerName = ${JSON.stringify(FOE)};
    gameState.socket.emit('create_room', { player_name: ${JSON.stringify(FOE)} }, function(r){ res(r); }); })`);
  const roomId = created && created.room_id;
  check(!!roomId, '8 对手建房', created);
  const profA = await A.ev(`fetch('/api/profile').then(r => r.json()).catch(() => ({}))`);
  const myUid = (profA && profA.profile && profA.profile.id) || '';
  check(!!myUid, '8b 拿到我的 uid（自定义房座位 key = 自己的 uid）', myUid);
  const profB = await B.ev(`fetch('/api/profile').then(r => r.json()).catch(() => ({}))`);
  const foeUid = (profB && profB.profile && profB.profile.id) || '';
  check(!!foeUid && foeUid !== myUid, '8c 拿到对手的 uid（两边必须是不同账号）', { foeUid, myUid });
  const joined = await A.ev(`new Promise(function(res){ ensureSocket(); gameState.playerName = ${JSON.stringify(ME)};
    gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name: ${JSON.stringify(ME)} }, function(r){ res(r); }); })`);
  check(!!(joined && joined.player_id), '9 我入座', joined && joined.player_id);
  await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; gameState.playerId = ${JSON.stringify(myUid)}; true`);
  // ⚠️ 对手的座位 key 是**它自己的** uid（不是我的）——第一版这里写成了 myUid，
  //    那样"投降"会以我的身份发、结算双方都错位。
  await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; gameState.playerId = ${JSON.stringify(foeUid)}; true`);

  // 双方入座 → 服务端把状态推进到 placing_ships → 客户端弹"匹配成功"5 秒界面
  let successShown = false;
  for (let i = 0; i < 40 && !successShown; i++) {
    successShown = await A.ev(`(function () { var s = document.getElementById('match-success-screen');
      return !!(s && s.classList.contains('active')); })()`);
    if (!successShown) await sleep(250);
  }
  check(successShown === true, '★ 10 我这边出现「匹配成功」5 秒等待界面', successShown);
  let chips = null;
  for (let i = 0; i < 40; i++) {
    chips = await A.ev(`(function () {
      var box = document.getElementById('opponent-chips');
      var oppEl = document.getElementById('opponent-info');
      return { gameOppName: (window.gameState && window.gameState.opponentName) || '',
        oppInfoText: oppEl ? (oppEl.textContent || '').trim() : 'no-el',
        missing: !box,
        text: box ? (box.textContent || '').replace(/\\s+/g, ' ').trim() : '',
        lv: (function () { var e = box && box.querySelector('.match-chip.lv'); return e ? e.textContent.trim() : null; })(),
        title: (function () { var e = box && box.querySelector('.match-chip.title'); return e ? e.textContent.trim() : null; })(),
        tags: box ? [].slice.call(box.querySelectorAll('.match-chip.tag')).map(function (e) { return e.textContent.trim(); }) : [] }; })()`);
    if (chips && chips.lv) break;
    await sleep(250);
  }
  check(chips && chips.lv === 'Lv.101', '★ 11 等待界面显示对手等级 Lv.101', chips);
  check(chips && !!chips.title, '★ 12 显示对手的称号', chips && chips.title);
  check(chips && chips.tags && chips.tags.length === 2, '★ 13 显示对手的两个标签', chips && chips.tags);
  // 名字在上方那行「你的对手是：X」里（`#opponent-info`），浮块里只放等级/称号/标签 ——
  // 别在浮块里找名字（第一版就是这么写错的）。
  check(chips && chips.oppInfoText === FOE, '13b 等待界面那行写着对手名字', chips && chips.oppInfoText);

  // ---------- 3. 结算：我（Lv.1，差 5 点）赢下 → 升级动画 ----------
  // 对手投降 → 我获胜 → 走真实结算收口（_finalize_match → _grant_match_xp）
  const sur = await B.ev(`new Promise(function(res){ gameState.socket.emit('surrender', { room_id: gameState.roomId,
    player_id: gameState.playerId }, function(r){ res(r); }); })`);
  check(!!sur, '14 对手投降（真实结算入口）', sur && (sur.status || Object.keys(sur).join(',')));

  await A.front();
  let panel = null, sawRolling = false, sawLevelUp = false, prevPct = null;
  for (let i = 0; i < 100; i++) {
    const st = await A.ev(XP_PANEL);
    if (st && st.visible) {
      panel = st;
      if (st.levelUpShown) { sawLevelUp = true; panel.levelUpTextWhenShown = st.levelUpText; }
      if (prevPct !== null && st.fillPct !== prevPct) sawRolling = true;
      prevPct = st.fillPct;
      // 动画结束后会停在最终等级上
      if (sawLevelUp && st.levelNow === '2') break;
    }
    await sleep(120);
  }
  check(panel && panel.visible === true, '★ 15 结算界面出现「本局获得经验」面板', panel && { visible: panel.visible, delta: panel.delta });
  check(panel && /^\+\d+$/.test(panel.delta || ''), '★ 16 显示本局获得多少经验', panel && panel.delta);
  check(panel && (panel.breakdown || '').indexOf('+') >= 0, '17 经验明细也列出来了（哪来的经验）', panel && panel.breakdown);
  check(sawRolling === true, '★ 18 经验条是**滚动**加上去的（宽度在变）', { sawRolling, lastPct: panel && panel.fillPct });
  check(sawLevelUp === true, '★★ 19 升级时出现了「升级！」提示', panel && panel.levelUpTextWhenShown);
  check(panel && panel.levelNow === '2', '★★ 20 动画结束后等级是 Lv.2（条子清空重来后继续加完）', panel && { level: panel.levelNow, progress: panel.progress });

  // ---------- 4. 首页等级条也跟着更新 ----------
  await sleep(600);
  const stripAfter = await A.ev(STRIP_STATE);
  check(stripAfter && stripAfter.level === '2', '★ 21 首页等级条更新成 Lv.2', stripAfter && { level: stripAfter.level, text: stripAfter.text });

  // ---------- 5. 接口真值：经验确实加上了 ----------
  const after = await A.ev(`fetch('/api/profile').then(r => r.json()).catch(() => ({}))`);
  const li = after && after.profile && after.profile.level_info;
  check(li && li.level === 2, '★ 22 接口真值：我的等级是 2', li && { level: li.level, xp: li.xp });
  check(li && li.xp >= 35, '23 经验也真的加到库里了（xp ≥ 35）', li && li.xp);

  check(jsProblems.length === 0, 'Z1 全程零 JS 异常 / 零 console.error', jsProblems.slice(0, 4));
} catch (e) {
  check(false, '工具执行异常', e.message);
} finally {
  try { if (brA) brA.kill(); } catch (e) {}
  try { if (brB) brB.kill(); } catch (e) {}
}

console.log('');
if (problems.length) {
  console.log('LEVEL CHECK FAILED (' + problems.length + '): ' + problems.join(' | '));
  process.exit(1);
}
console.log('LEVEL CHECK PASSED');
process.exit(0);
