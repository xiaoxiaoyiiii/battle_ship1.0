#!/usr/bin/env node
/**
 * 第 3 批「点赞 / 送花 / 留言板」端到端回归检查（无头 Edge + CDP）
 *
 * 依据：`docs/BATCH_2_3_4_PLAN.md` §3（数据 / 接口契约 §3.3 / 隐私 §3.4 / DOM 契约 §3.5）。
 *
 * 为什么必须真注册、真发请求、真切换账号：
 *   · 这一批的核心链路是「B 看 A 的名片 → 互动 → 落库 → A 自己那边改隐私 → B 再看」，
 *     桩掉接口就只能测到"请求长什么样"，测不到**保存到底有没有生效**。
 *     实施中就踩过：`save_user_profile_extra` 的 INSERT 漏了 `show_guestbook` 列，
 *     值被静默丢弃 —— 只断言"点了保存按钮"是**看不出**这个 bug 的。
 *   · 所以本工具对**每个关键动作都回头读一次服务端真值**（`/user_stats`、
 *     `/api/profile/messages`、`/api/profile`），DOM 断言与库里的值必须一致。
 *
 * 会话怎么分：**A（页面主人）的会话握在 Node 手里**（cookie jar，走真实 HTTP 接口），
 * **B（访客）的会话在浏览器里**（走真实 UI 点击）。两边互不干扰，浏览器里来回切账号
 * 只切 B/A 的登录态，Node 那份 A 的 cookie 一直有效。
 *
 * 用法：
 *   node tools/social_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 *
 * ⚠️ 会在目标服务端注册两个一次性账号（`socown*` / `socvis*`），**不要指向生产**。
 *    本地跑法（隔离库）：
 *      $env:BATTLESHIP_DB_PATH="$PWD\.tmp\social_check.db"; python server.py
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9355;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(HERE, '..', '.tmp', 'social_check_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过社交互动检查'); process.exit(0); }

// 预清理：上一次运行残留的无头 Edge 会占着调试端口 + 锁住 profile 目录，
// 新的浏览器**静默起不来**、工具连上旧实例 → 表现为「等待超时：页面加载」这种假红。
try {
  execSync('powershell -NoProfile -Command "' +
    'Get-CimInstance Win32_Process -Filter \\"Name=\'msedge.exe\'\\" | ' +
    'Where-Object { $_.CommandLine -like \'*social_check_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没有残留就够了，清理失败不影响后面的断言 */ }

const SUFFIX = String(Date.now()).slice(-6);
const OWNER = 'socown' + SUFFIX;     // A：页面主人
const VISITOR = 'socvis' + SUFFIX;   // B：访客
const PW = 'check123456';
const MSG = '第 3 批回归检查的留言';
const MSG2 = '关掉留言板之前留下的那条';

const problems = [];
const jsProblems = [];

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// ---------------------------------------------------------------------------
// Node 侧的 HTTP（带 cookie jar）—— A 的会话
// ---------------------------------------------------------------------------
function newJar() {
  let cookie = '';
  return async function call(pathname, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    if (cookie) headers.Cookie = cookie;
    let body;
    if (opts.form) {
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
      body = new URLSearchParams(opts.form).toString();
    } else if (opts.json) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.json);
    }
    const res = await fetch(APP.replace(/\/$/, '') + pathname,
      { method: opts.method || (body === undefined ? 'GET' : 'POST'), headers, body, redirect: opts.raw ? 'manual' : 'follow' });
    // 只要 session 那一条（`Set-Cookie` 可能有多条；Node 的 getSetCookie 不是所有版本都有）
    const raw = res.headers.get('set-cookie') || '';
    const m = /(session=[^;,\s]+)/.exec(raw);
    if (m) cookie = m[1];
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
    return { status: res.status, data, text };
  };
}

const owner = newJar();
// 访客 B 的会话也留一份在 Node 手里：**「别人视角」的服务端真值只有以别人的身份才读得到**
// （契约 §3.4：本人视角永远完整 —— 拿 A 的 cookie 去读 `guestbook_private` 永远是 false，
//   那是这条契约**正确**的表现，不是 bug。本工具第一版就是在这里假红的。）
const visitor = newJar();

// ---------------------------------------------------------------------------
// 浏览器侧
// ---------------------------------------------------------------------------
let browser = null, ws = null, seq = 0;
const pending = new Map();

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 25000);
  });
}

async function ev(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('页面异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await fn()) return true; } catch (e) { /* 继续轮询 */ }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label);
}

async function goto(url, expect) {
  await send('Page.navigate', { url });
  // ⚠️ `Page.navigate` 一返回，`document.readyState` 可能仍是**旧文档**的 complete
  // → "等 readyState" 立刻通过、后面的断言全打在上一页上。要求地址真的变了。
  // `expect` 用于会跳转的入口（`/logout` 是 302 跳到首页，最终地址不是 /logout）。
  const want = (expect || url).replace(/\/$/, '');
  await waitFor(async () => {
    const st = await ev('({ href: location.href.replace(/\\/$/, ""), ready: document.readyState })');
    return st && st.ready === 'complete' && st.href === want;
  }, 30000, '页面加载 ' + url);
  await sleep(400);
}

// 只记录，不打桩：本次要验的就是真实链路，fetch 一律放行。记录两样东西：
//   · `__cardPosts` —— 编辑面保存时到底发了哪几个字段（静默丢弃那类 bug 藏在这里）；
//   · `__likeCalls` —— 点赞/送花的请求体与响应码。**这不只是取证**：点赞是「乐观预演」
//     的（点下去界面立刻变），所以"界面变了"不等于"请求回来了"；请求没回来就点第二下
//     会被 `profileLikePending` 拦掉（连点只算一次），断言就等在那儿超时（实测踩过）。
const STUB = `
(function () {
  window.__cardPosts = [];
  window.__likeCalls = [];
  var orig = window.fetch;
  window.fetch = function (url, opts) {
    var u = String(url); opts = opts || {};
    if (u.indexOf('/api/profile/card') === 0) {
      try { window.__cardPosts.push(JSON.parse(opts.body || '{}')); }
      catch (e) { window.__cardPosts.push({ __parse_error: String(opts.body) }); }
    }
    if (u.indexOf('/api/profile/like') === 0) {
      var p = orig.apply(this, arguments);
      if (p && typeof p.then === 'function') {
        p.then(function (r) {
          var body = {};
          try { body = JSON.parse(opts.body || '{}'); } catch (e) { body = { __parse_error: String(opts.body) }; }
          window.__likeCalls.push({ body: body, status: r.status });
        }, function () { window.__likeCalls.push({ body: null, status: 0 }); });
      }
      return p;
    }
    return orig.apply(this, arguments);
  };
  return 'recording';
})()`;

// 浏览器里的登录（先试登录，登录不上再注册；两个都是真实表单 POST）
const AUTH = (name) => `
(async function () {
  var post = function (url) {
    return fetch(url, { method: 'POST', redirect: 'follow',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: ${JSON.stringify(name)}, password: ${JSON.stringify(PW)} }).toString() });
  };
  var r1 = await post('/login');
  var t1 = await r1.text();
  if (t1.indexOf('登录成功') >= 0) return 'login-ok';
  var r2 = await post('/register');
  var t2 = await r2.text();
  if (t2.indexOf('注册成功') >= 0) return 'register-ok';
  return 'auth-failed: ' + t2.replace(/\\s+/g, ' ').slice(0, 120);
})()`;

// 打开别人的名片（真实入口：与排行榜 / 局内头像同一个 showUserProfile）
const OPEN_PROFILE = (name) => `(async function () {
  if (typeof window.showUserProfile !== 'function') return 'no-fn';
  window.showUserProfile(${JSON.stringify(name)});
  for (var i = 0; i < 80; i++) {
    var v = document.querySelector('#opponent-stats-content #profile-view');
    if (v) return 'ok';
    await new Promise(function (r) { setTimeout(r, 150); });
  }
  return 'no-view';
})()`;

const CLOSE_PROFILE = `(function () {
  var b = document.getElementById('opponent-stats-modal-close');
  if (b) b.click();
  return true; })()`;

// 打开自己的编辑面（页头「个人信息」→ 名片上的「编辑资料」）
const OPEN_EDITOR = `(async function () {
  var btn = document.getElementById('show-profile');
  if (btn) btn.click();
  for (var i = 0; i < 60; i++) {
    var b = document.querySelector('#profile-edit-btn');
    if (b) { b.click(); break; }
    await new Promise(function (r) { setTimeout(r, 150); });
  }
  for (var j = 0; j < 60; j++) {
    if (document.getElementById('profile-show-guestbook')) return 'ok';
    await new Promise(function (r) { setTimeout(r, 150); });
  }
  return 'no-toggle';
})()`;

// 名片查看面里跟互动相关的读数（一次读全，少来回）
const VIEW_STATE = `(function () {
  var box = document.getElementById('opponent-stats-content');
  if (!box) return { missing: true };
  var txt = function (sel) { var e = box.querySelector(sel); return e ? e.textContent.trim() : null; };
  var el = function (sel) { return box.querySelector(sel); };
  var like = el('#profile-like'), flower = el('#profile-flower');
  var form = box.querySelector('.guestbook-form');
  var priv = el('#guestbook-private');
  return {
    likeCount: txt('#profile-like-count'),
    flowerCount: txt('#profile-flower-count'),
    likeOn: like ? like.classList.contains('on') : null,
    flowerOn: flower ? flower.classList.contains('on') : null,
    likeDisabled: like ? like.disabled : null,
    flowerDisabled: flower ? flower.disabled : null,
    likeTitle: like ? (like.getAttribute('title') || '') : null,
    items: box.querySelectorAll('.guestbook-item').length,
    firstText: txt('.guestbook-item .guestbook-text'),
    delButtons: box.querySelectorAll('.guestbook-del').length,
    emptyHidden: el('#guestbook-empty') ? el('#guestbook-empty').classList.contains('hidden') : null,
    formHidden: form ? form.classList.contains('hidden') : (form === null ? 'no-form' : null),
    inputMax: (function () { var i = el('#guestbook-input'); return i ? i.getAttribute('maxlength') : null; })(),
    countText: txt('#guestbook-count'),
    privHidden: priv ? priv.classList.contains('hidden') : null,
    privText: priv ? priv.textContent.replace(/\\s+/g, ' ').trim().slice(0, 40) : null,
    selfHintHidden: el('#guestbook-self-hint') ? el('#guestbook-self-hint').classList.contains('hidden') : null,
    msgText: txt('#guestbook-msg')
  };
})()`;

// 在输入框里真的敲字（原生 DOM 绑的是 'input' 事件，必须派发；
// 只赋值不派发的话字数计不会更新 —— 那正是这里要验的东西）
const TYPE_MESSAGE = (text) => `(function () {
  var i = document.getElementById('guestbook-input');
  if (!i) return 'no-input';
  i.focus();
  i.value = ${JSON.stringify(text)};
  i.dispatchEvent(new Event('input', { bubbles: true }));
  return i.value.length;
})()`;

const CLICK = (sel) => `(function () { var e = document.querySelector(${JSON.stringify(sel)}); if (!e) return 'missing'; e.click(); return 'clicked'; })()`;

// ---------------------------------------------------------------------------
// 跑
// ---------------------------------------------------------------------------
try {
  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank'], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      // ⚠️ 无头 Edge 自带一个 edge://sync-confirmation-dialog 页面且稳定排在第一位，
      // 只认 http/https 的页面（老工具在这里连错过页，症状是"读不到 gameState"的假红）。
      target = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 浏览器还在启动 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: STUB });
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });

  // ---------- 0. 两个一次性真实账号 ----------
  // `/register` 是表单 POST → 302（成功与否都是 302，靠 flash 文案区分），而 Node 的 fetch
  // **不会**在跨跳转时带上 cookie，flash 页读不到 —— 所以这里不跟跳转，改用更硬的证据：
  // 「注册完之后能不能以这个身份读到自己」。
  const regA = await owner('/register', { form: { username: OWNER, password: PW }, raw: true });
  const meA = await owner('/api/profile');
  check(regA.status === 302 && meA.status === 200 && meA.data && meA.data.profile
    && meA.data.profile.username === OWNER,
    'A0 主页主人账号真实注册成功（A 的会话在 Node 手里）',
    { register: regA.status, profile: meA.status, who: meA.data && meA.data.profile && meA.data.profile.username });

  // 访客 B 的账号也在 Node 这边建好（浏览器里随后就是「登录」而不是「注册」），
  // 这样第 5 阶段能以一个**真正的别人**去读服务端真值。
  const regB = await visitor('/register', { form: { username: VISITOR, password: PW }, raw: true });
  const meB = await visitor('/api/profile');
  check(regB.status === 302 && meB.status === 200 && meB.data && meB.data.profile
    && meB.data.profile.username === VISITOR,
    'A0b 访客 B 账号真实注册成功（Node 也留了一份 B 的会话）',
    { register: regB.status, who: meB.data && meB.data.profile && meB.data.profile.username });

  await goto(APP + 'register');
  const authB = await ev(AUTH(VISITOR));
  check(typeof authB === 'string' && /ok$/.test(authB), 'A1 访客 B 在浏览器里真实登录', authB);
  await goto(APP);
  const whoB = await ev('window.__USERNAME');
  check(whoB === VISITOR, 'A2 页面认得当前登录用户是 B', whoB);

  // ---------- 1. B 看 A 的名片 ----------
  const opened = await ev(OPEN_PROFILE(OWNER));
  check(opened === 'ok', '★ 1 B 打开 A 的名片（查看面渲染出 #profile-view）', opened);

  const s0 = await ev(VIEW_STATE);
  check(s0 && s0.likeCount === '0' && s0.flowerCount === '0', '★ 2 互动条初始计数 0 / 0', s0 && { like: s0.likeCount, flower: s0.flowerCount });
  check(s0 && s0.likeOn === false && s0.flowerOn === false, '3 初始未点亮（没有误显示成"我赞过"）', s0 && { likeOn: s0.likeOn, flowerOn: s0.flowerOn });
  check(s0 && s0.likeDisabled === false && s0.flowerDisabled === false, '4 看别人时点赞/送花可点（不是被禁用的）', s0 && { like: s0.likeDisabled, flower: s0.flowerDisabled });
  check(s0 && s0.inputMax === '100', '★ 5 留言框 maxlength = 100（契约 §3.2 第 2 条）', s0 && s0.inputMax);
  check(s0 && /^0\s*\/\s*100$/.test(s0.countText || ''), '6 字数计初始显示 0/100', s0 && s0.countText);

  // ---------- 2. 点赞：DOM + 服务端真值 ----------
  // ⚠️ 顺序很重要：点赞是乐观预演，界面立刻变；但**请求没回来之前再点第二下会被
  // `profileLikePending` 当成连点忽略掉**。所以每次点完都要等到「这一发请求真的 settle」，
  // 而不是"等到界面上的数字变了"（实测就是这么超时的）。
  const likeCallCount = async () => (await ev('(window.__likeCalls || []).length')) || 0;
  const waitLike = (n) => waitFor(async () => (await likeCallCount()) >= n, 20000, '点赞请求 settle #' + n);

  await ev(CLICK('#profile-like'));
  await waitLike(1);
  await waitFor(async () => (await ev(VIEW_STATE)).likeCount === '1', 20000, '点赞计数变 1');
  const s1 = await ev(VIEW_STATE);
  check(s1.likeCount === '1' && s1.likeOn === true, '★ 7 点赞后计数 1 且按钮点亮', { c: s1.likeCount, on: s1.likeOn, title: s1.likeTitle });
  check(s1.likeTitle === '取消', '8 点亮后 title 变成「取消」（再点能取消）', s1.likeTitle);
  const likeCalls = await ev('window.__likeCalls');
  check(likeCalls[0] && likeCalls[0].status === 200 && likeCalls[0].body.kind === 'like'
    && likeCalls[0].body.on === true && likeCalls[0].body.username === OWNER,
    '★ 9 点下去真发了一发 POST /api/profile/like（契约 §3.3 的请求体）', likeCalls[0]);
  const truth1 = await owner('/user_stats?username=' + OWNER);
  check(truth1.data && truth1.data.stats && truth1.data.stats.counts && truth1.data.stats.counts.like === 1,
    '★ 10 服务端真值：A 的点赞数确实是 1（不是只改了界面）',
    truth1.data && truth1.data.stats && truth1.data.stats.counts);

  await ev(CLICK('#profile-like'));
  await waitLike(2);
  await waitFor(async () => (await ev(VIEW_STATE)).likeCount === '0', 20000, '取消点赞');
  const truth2 = await owner('/user_stats?username=' + OWNER);
  const cancelCall = (await ev('window.__likeCalls'))[1];
  check(truth2.data && truth2.data.stats.counts.like === 0, '★ 11 取消点赞后服务端真值回到 0（幂等可撤销）',
    { counts: truth2.data && truth2.data.stats.counts, sent: cancelCall && cancelCall.body });

  await ev(CLICK('#profile-flower'));
  await waitLike(3);
  await waitFor(async () => (await ev(VIEW_STATE)).flowerCount === '1', 20000, '送花计数变 1');
  const truth3 = await owner('/user_stats?username=' + OWNER);
  check(truth3.data && truth3.data.stats.counts.flower === 1 && truth3.data.stats.counts.like === 0,
    '★ 12 送花与点赞各自独立计数', truth3.data && truth3.data.stats.counts);

  // ---------- 3. 留言 ----------
  const typed = await ev(TYPE_MESSAGE(MSG));
  check(typed === MSG.length, '13 在留言框里真的敲进了 ' + MSG.length + ' 个字', typed);
  const s2 = await ev(VIEW_STATE);
  check(s2.countText === MSG.length + '/100', '★ 14 字数计实时跟着走（' + MSG.length + '/100）', s2.countText);

  await ev(CLICK('#guestbook-send'));
  await waitFor(async () => (await ev(VIEW_STATE)).items === 1, 20000, '留言出现在列表里');
  const s3 = await ev(VIEW_STATE);
  check(s3.items === 1 && s3.firstText === MSG, '★ 15 留言出现在留言板里且文案一致', { n: s3.items, text: s3.firstText });
  check(s3.emptyHidden === true, '16 有留言后「还没有留言」占位消失', s3.emptyHidden);
  check(s3.delButtons === 1, '★ 17 自己的留言渲染出删除按钮（can_delete 由服务端算）', s3.delButtons);

  const truth4 = await owner('/api/profile/messages?username=' + OWNER + '&limit=20');
  const msgs = (truth4.data && truth4.data.messages) || [];
  check(truth4.data && truth4.data.total === 1 && msgs.length === 1 && msgs[0].content === MSG,
    '★ 18 服务端真值：留言真的落库了（1 条，文案一致）',
    truth4.data && { total: truth4.data.total, first: msgs[0] && msgs[0].content });
  check(msgs[0] && msgs[0].can_delete === true, '19 服务端把 can_delete 算成 true（本人可删）', msgs[0] && msgs[0].can_delete);

  await ev(CLICK('.guestbook-del'));
  await waitFor(async () => (await ev(VIEW_STATE)).items === 0, 20000, '留言被删掉');
  const s4 = await ev(VIEW_STATE);
  check(s4.items === 0 && s4.emptyHidden === false, '★ 20 删除后该条消失、「还没有留言」占位回来', { n: s4.items, emptyHidden: s4.emptyHidden });
  const truth5 = await owner('/api/profile/messages?username=' + OWNER + '&limit=20');
  check(truth5.data && truth5.data.total === 0, '★ 21 服务端真值：删除后 total 回到 0（软删不再出现）',
    truth5.data && truth5.data.total);

  // 再留一条**不被删掉**的留言：第 5 阶段要验「关掉留言板之后内容确实看不见」，
  // 空板上验不出"藏起来"和"本来就没有"的区别（那正是假绿）。
  const typed2 = await ev(TYPE_MESSAGE(MSG2));
  check(typed2 === MSG2.length, '21b 再写一条留言用于隐私验证', typed2);
  await ev(CLICK('#guestbook-send'));
  await waitFor(async () => (await ev(VIEW_STATE)).items === 1, 20000, '第二条留言出现');
  const truth5b = await owner('/api/profile/messages?username=' + OWNER + '&limit=20');
  check(truth5b.data && truth5b.data.total === 1 && (truth5b.data.messages || [])[0].content === MSG2,
    '★ 21c 服务端真值：这条留言真的在库里（后面才验得出"被藏起来"）',
    truth5b.data && { total: truth5b.data.total, first: (truth5b.data.messages || [])[0] && truth5b.data.messages[0].content });

  // ---------- 4. A 看自己：不能给自己点赞 / 不能给自己留言 ----------
  await goto(APP + 'logout', APP);
  await goto(APP + 'register');
  const authA = await ev(AUTH(OWNER));
  check(typeof authA === 'string' && /ok$/.test(authA), '22 浏览器切到主页主人 A（同一套真实登录表单）', authA);
  await goto(APP);
  const openedA = await ev(OPEN_PROFILE(OWNER));
  check(openedA === 'ok', '23 A 打开自己的名片', openedA);
  const s5 = await ev(VIEW_STATE);
  check(s5.likeDisabled === true && s5.flowerDisabled === true, '★ 24 看自己时点赞/送花按钮是禁用的', { like: s5.likeDisabled, flower: s5.flowerDisabled });
  check(/不能给自己点赞/.test(s5.likeTitle || ''), '★ 25 禁用原因写在 title 里（不是灰着不解释）', s5.likeTitle);
  check(s5.formHidden === true, '★ 26 看自己时留言输入区收起', s5.formHidden);
  check(s5.flowerCount === '1', '27 自己看自己，人气计数照常显示（送花 1）', s5.flowerCount);

  await ev(CLOSE_PROFILE);
  const editor = await ev(OPEN_EDITOR);
  check(editor === 'ok', '★ 28 编辑面里有第 4 个展示开关 #profile-show-guestbook', editor);
  const toggle = await ev(`(function () {
    var box = document.getElementById('profile-show-guestbook');
    if (!box) return { missing: true };
    var pane = box.closest('.pf-pane');
    var toggles = box.closest('.pf-toggles');
    return { checked: box.checked, pane: pane ? pane.dataset.pane : null,
      sameGroup: toggles ? toggles.querySelectorAll('input[type=checkbox]').length : 0 }; })()`);
  check(toggle && toggle.checked === true, '29 默认是勾选（开放留言板，与表默认值一致）', toggle);
  check(toggle && toggle.pane === 'card', '★ 30 它与另外三个展示开关同在一个「名片」分区的 .pf-toggles 里', toggle);
  // ⚠️ 段位批把展示开关从 4 个加到 5 个（多了 `#profile-show-rank`「段位公开」），
  //    所以"同组正好 N 个"这个数要跟着涨；它真正守的是"同一组、别处没有再放一份"。
  check(toggle && toggle.sameGroup === 5, '★ 31 同一组里正好 5 个开关（没有在设置页再放一份）', toggle && toggle.sameGroup);

  // 关掉留言板 + 保存（真实 POST）
  await ev(`(function () {
    var b = document.getElementById('profile-show-guestbook');
    if (!b) return 'missing';
    if (b.checked) b.click();
    return b.checked; })()`);
  await ev(CLICK('#profile-card-save'));
  await waitFor(async () => {
    const n = await ev('(window.__cardPosts || []).length');
    return n >= 1;
  }, 12000, '保存请求发出');
  const posts = await ev('window.__cardPosts');
  const lastPost = posts[posts.length - 1] || {};
  const keys = Object.keys(lastPost).sort();
  check(keys.length === 10, '★ 32 保存时确实发了 10 个字段（含 show_guestbook / show_rank；缺一个服务端就 400）', keys);
  check(lastPost.show_guestbook === 0, '★ 33 请求体里 show_guestbook = 0（关掉了）', lastPost.show_guestbook);

  // 保存是异步的：等它真落库（别拿"点了按钮"当证据）
  let saved = {};
  await waitFor(async () => {
    const r = await owner('/api/profile');
    saved = (r.data && r.data.profile) || {};
    return Number(saved.show_guestbook) === 0;
  }, 15000, 'show_guestbook 落库').catch(() => {});
  check(Number(saved.show_guestbook) === 0,
    '★ 34 服务端真值：重新读出 show_guestbook = 0（保存真的生效，没被静默丢弃）',
    { show_guestbook: saved.show_guestbook, keys: Object.keys(saved).length });

  // 契约 §3.4 的另一半：**本人视角永远完整** —— 主人自己仍要能看到自己的留言板，
  // 否则「我的留言板」这个功能就作废了。这一步必须用 A 的会话读。
  const mineAfter = await owner('/api/profile/messages?username=' + OWNER + '&limit=20');
  check(mineAfter.data && mineAfter.data.guestbook_private === false
    && (mineAfter.data.messages || []).length === 1
    && mineAfter.data.messages[0].content === MSG2,
    '★ 34b 关掉开关后，主人自己仍然看得到那条留言（本人视角不受隐私开关影响）',
    mineAfter.data && { private: mineAfter.data.guestbook_private, n: (mineAfter.data.messages || []).length });

  // ---------- 5. B 再看 A：隐私占位 + 计数照旧 ----------
  await goto(APP + 'logout', APP);
  await goto(APP + 'register');
  const authB2 = await ev(AUTH(VISITOR));
  check(typeof authB2 === 'string' && /ok$/.test(authB2), '35 浏览器切回访客 B', authB2);
  await goto(APP);
  const opened2 = await ev(OPEN_PROFILE(OWNER));
  check(opened2 === 'ok', '36 B 重新打开 A 的名片', opened2);
  const s6 = await ev(VIEW_STATE);
  check(s6.privHidden === false, '★ 37 关掉留言板后，别人看到的是「未开放留言板」占位（不是留白）', { hidden: s6.privHidden, text: s6.privText });
  check(s6.items === 0, '★ 38 别人看不到任何留言', s6.items);
  check(s6.formHidden === true, '★ 39 别人不能给已关闭留言板的主人留言（输入区收起）', s6.formHidden);
  check(s6.flowerCount === '1' && s6.likeCount === '0',
    '★ 40 关的是「内容」不是「人气」：点赞/送花计数始终可见', { like: s6.likeCount, flower: s6.flowerCount });

  const truth6 = await visitor('/api/profile/messages?username=' + OWNER + '&limit=20');
  check(truth6.data && truth6.data.guestbook_private === true && (truth6.data.messages || []).length === 0,
    '★ 41 服务端真值（以 B 的身份读）：messages=[] 且 guestbook_private=true —— 库里那条被藏住了',
    truth6.data && { private: truth6.data.guestbook_private, n: (truth6.data.messages || []).length });
  check(truth6.data && truth6.data.counts && truth6.data.counts.flower === 1,
    '★ 42 隐私开关不影响计数下发', truth6.data && truth6.data.counts);
  const asOwner = await owner('/api/profile/messages?username=' + OWNER + '&limit=20');
  // ⚠️ 必须**两侧都断言**。只断言"主人看得到 1 条"是抓不到"过滤没生效"的
  // （红基线实测：把服务端的隐私分支关掉，只断言主人那一侧的版本照样全绿）。
  const ownerSees = (asOwner.data && asOwner.data.messages || []).length;
  const visitorSees = (truth6.data && truth6.data.messages || []).length;
  check(ownerSees === 1 && visitorSees === 0,
    '★ 43 同一条留言：别人看不到、主人看得到（两个视角真的分开）',
    { ownerSees: ownerSees, visitorSees: visitorSees });

  check(jsProblems.length === 0, 'Z1 全程零 JS 异常 / 零 console.error', jsProblems.slice(0, 4));

  if (SHOT) {
    try {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
      console.log('截图已保存: ' + SHOT);
    } catch (e) { console.log('截图失败: ' + e.message); }
  }
} catch (e) {
  check(false, '工具执行异常', e.message);
} finally {
  try { if (ws) ws.close(); } catch (e) {}
  try { if (browser) browser.kill(); } catch (e) {}
}

console.log('');
if (problems.length) {
  console.log('SOCIAL CHECK FAILED (' + problems.length + '): ' + problems.join(' | '));
  process.exit(1);
}
console.log('SOCIAL CHECK PASSED');
process.exit(0);
