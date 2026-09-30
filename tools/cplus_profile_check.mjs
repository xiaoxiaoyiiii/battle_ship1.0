#!/usr/bin/env node
/**
 * C+ 档案屏 · **查看面的宽屏两栏**定向检查（W3）
 *
 * 任务书 §4.1「必须补」第 4 条：「档案把**查看面**在宽屏扩成名片 + 数据／徽章／历史两栏，
 * 手机回单栏」。这条是纯布局，靠"看一眼截图"容易自欺（"看着像两栏"），
 * 所以这里量的是**几何事实**：
 *   · 宽屏：查看面是 grid、两列；头像那张卡（.pf-hero）在**左**、数据/徽章/历史在**右**
 *     （用 x 坐标比，不是看类名）；弹窗比原来的 560px 窄名片宽。
 *   · 窄屏（390）：回到**单栏**（非 grid 或只有一列），hero 与数据块**竖着排**（x 相同、y 递增）。
 *
 * 为什么要真登录：查看面是异步取数后才渲染的（先「加载中…」再出 `#profile-view`），
 * 而且三个 `show_*` 开关与徽章墙都依赖真实账号数据。未登录时查看面根本不渲染 ——
 * 那样量到的"两栏"是空气。这里走真实注册。
 *
 * 用法：node tools/cplus_profile_check.mjs --url http://127.0.0.1:5097/ [--shots <dir>]
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
const PORT = Number(argOf('--port', '9377'));
const SHOTS = argOf('--shots', '');
const KNOWN_BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const EDGE = KNOWN_BROWSERS.find((p) => fs.existsSync(p));
const PROFILE = argOf('--profile', path.join(REPO, '.tmp', 'cplus-profile', 'profile'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const ME = 'cprof' + String(Date.now() % 1000000);
const PW = 'cplusprof123456';

if (!EDGE) {
  console.log('SKIP  没有找到可用的 Edge/Chrome —— 这**不是通过**，是未验收。');
  process.exit(2);
}
fs.mkdirSync(PROFILE, { recursive: true });
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

/* 注册/登录一次。⚠️ 用**表单编码**打 `/login` 与 `/register`（不是 JSON API）——
   这两个是 Flask 的表单路由，返回的是重定向后的 HTML。第一版按 `/api/register` 发 JSON，
   拿到 `login:401`，看着像"账号建不出来"，其实是打错了端点。
   手法与 tools/profile_card_check.mjs 一致。 */
const AUTH = `
(async function () {
  var post = function (url) {
    return fetch(url, { method: 'POST', redirect: 'follow',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: ${JSON.stringify(ME)}, password: ${JSON.stringify(PW)} }).toString() });
  };
  var r1 = await post('/login');
  var t1 = await r1.text();
  if (t1.indexOf('登录成功') >= 0) return 'login-ok';
  var r2 = await post('/register');
  var t2 = await r2.text();
  if (t2.indexOf('注册成功') >= 0) return 'register-ok';
  return 'auth-failed: ' + t2.replace(/\\s+/g, ' ').slice(0, 120);
})()`;

const MEASURE = `(function(){
  var card = document.querySelector('#opponent-stats-content .pf-card');
  if (!card) return { noCard: true };
  var g = getComputedStyle(card);
  function R(sel){ var e = card.querySelector(sel); if (!e) return null; var b = e.getBoundingClientRect();
    return { x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) }; }
  var modal = document.querySelector('.pf-view-modal');
  return {
    display: g.display,
    colCount: g.gridTemplateColumns.split(' ').filter(function (v) { return v && v !== '0px'; }).length,
    cardW: Math.round(card.getBoundingClientRect().width),
    modalW: modal ? Math.round(modal.getBoundingClientRect().width) : null,
    hero: R('.pf-hero'), stats: R('.pf-stats'), badges: R('.pf-badges'),
    history: R('.pf-history'), favcards: R('.pf-favcards'), cover: R('.pf-cover'),
    override: (document.getElementById('opponent-stats-modal') || {}).classList
      ? !document.getElementById('opponent-stats-modal').classList.contains('hidden') : null,
    pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
})()`;

console.log('== C+ 档案查看面 · 宽屏两栏定向检查（W3）==');
console.log('   目标 ' + APP);

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
  '--user-data-dir=' + PROFILE, 'about:blank'], { stdio: 'ignore' });

let ws = null;
let exitCode = 0;
try {
  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还没起来 */ }
    await sleep(500);
  }
  if (!target) { console.error('无法连接无头浏览器调试端口 ' + PORT); process.exit(3); }
  ws = new WebSocket(target.webSocketDebuggerUrl);
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
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
    }
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
    while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(150); }
    return false;
  };
  await send('Page.enable');
  await send('Runtime.enable');

  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000);
  const auth = await ev(AUTH);
  // AUTH 返回 'login-ok' / 'register-ok' / 'auth-failed: …'（见上面那段注释）
  check(typeof auth === 'string' && /-ok$/.test(auth),
    'A0 真实注册/登录一次性账号（查看面依赖真实账号数据）', auth);

  const openView = `(function(){
    var n = window.__USERNAME || '';
    if (!n) return 'no-username';
    if (typeof window.showUserProfile === 'function') window.showUserProfile(n);
    return n;
  })()`;

  for (const [vlabel, w, h, wide] of [['1440x900', 1440, 900, true], ['1280x720', 1280, 720, true], ['390x844', 390, 844, false]]) {
    console.log('');
    console.log('-- 视口 ' + vlabel + ' --');
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: !wide });
    await send('Page.navigate', { url: APP });
    await waitFor(async () => await ev('document.readyState === "complete" && typeof window.gameState === "object"'), 20000);
    await sleep(600);
    await ev(openView);
    const ready = await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'), 20000);
    check(ready === true, '[' + vlabel + '] 查看面渲染出真实名片（不是"加载中…"）');
    if (!ready) continue;
    await sleep(400);
    const m = await ev(MEASURE);
    if (m && m.__exc) { check(false, '[' + vlabel + '] 量几何', m); continue; }
    check(m && m.noCard !== true, '[' + vlabel + '] 查看面的 .pf-card 在页面里', m && { noCard: m.noCard });
    if (!m || m.noCard) continue;

    if (wide) {
      check(m.display === 'grid' && m.colCount === 2,
        '[' + vlabel + '] 查看面是**两栏**（display:grid + 两列）', { display: m.display, colCount: m.colCount });
      check(!!m.hero && !!m.stats && m.hero.x < m.stats.x,
        '[' + vlabel + '] 名片在**左**、数据在**右**（按 x 坐标比，不看类名）',
        m && { heroX: m.hero && m.hero.x, statsX: m.stats && m.stats.x });
      check(!!m.stats && !!m.badges && m.stats.x === m.badges.x,
        '[' + vlabel + '] 数据与徽章墙在**同一栏**（x 相同）',
        m && { statsX: m.stats && m.stats.x, badgesX: m.badges && m.badges.x });
      check(!!m.cover && !!m.hero && m.cover.x <= m.hero.x && m.cover.w >= m.hero.w,
        '[' + vlabel + '] 封面横跨两栏（比名片那一栏宽）',
        m && { cover: m.cover, hero: m.hero });
      check(m.modalW > 560, '[' + vlabel + '] 弹窗比原来的 560px 窄名片宽（两栏排得开）', { modalW: m.modalW });
    } else {
      const single = m.display !== 'grid' || m.colCount <= 1;
      check(single, '[' + vlabel + '] 窄屏回到**单栏**（不是 grid 两列）',
        { display: m.display, colCount: m.colCount });
      check(!!m.hero && !!m.stats && Math.abs(m.hero.x - m.stats.x) <= 2 && m.stats.y > m.hero.y,
        '[' + vlabel + '] 窄屏下名片与数据块竖着排（x 相同、数据在下方）',
        m && { hero: m.hero, stats: m.stats });
    }
    check(m.pageOverflow <= 1, '[' + vlabel + '] 档案屏没有横向溢出', { overflow: m.pageOverflow });

    if (SHOTS) {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(SHOTS, 'profile-' + vlabel + '.png'), Buffer.from(shot.data, 'base64'));
    }
  }

  check(jsProblems.length === 0, '全程零 JS 异常', jsProblems.slice(0, 4));
  console.log('');
  if (problems.length) {
    console.log('✗ ' + problems.length + ' 项未通过：');
    problems.slice(0, 30).forEach((p) => console.log('   · ' + p));
    exitCode = 1;
  } else {
    console.log('✓ 全部通过');
  }
} finally {
  try { if (ws) ws.close(); } catch (e) { /* 已断 */ }
  try { browser.kill(); } catch (e) { /* 已经退了 */ }
}
process.exit(exitCode);
