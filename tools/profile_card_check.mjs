#!/usr/bin/env node
/**
 * 个人信息名片 / 界面设置改版 回归检查（无头 Edge + CDP）
 *
 * 依据：`docs/PROFILE_CARD_2026_09_17.md`（设计稿）与 `docs/PROFILE_CARD_2026_09_17_PLAN.md`（契约）。
 *
 * 为什么工具要**真的注册登录**：本次改版的核心链路是「登录 → 编辑 → 保存 → 落库 → 重新渲染」，
 * 桩掉接口就只能测到「请求长什么样」，测不到「保存到底有没有生效」。所以：
 *   · `/api/profile` 与 `/api/profile/card` 走**真实服务端 + 真实库**（本机跑时库是隔离的）
 *   · 只桩掉 `/user_stats` 与 `/api/leaderboard`（别人主页的数据要确定性，
 *     否则断言会依赖本机库里恰好有多少条战绩）
 *
 * 用法：
 *   node tools/profile_card_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 *
 * ⚠️ 会在目标服务端注册两个一次性账号（`cardcheck*`），不要指向生产。
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9349;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(HERE, '..', '.tmp', 'profile_card_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过个人信息名片检查'); process.exit(0); }

// 预清理：上一次运行若没退干净（browser.kill() 只杀父进程），会有残留的无头 Edge
// 占着调试端口 + 锁住 profile 目录 → 新的浏览器静默起不来，工具连上的是**旧实例**，
// 表现为「等待超时：页面加载」这种查不出所以然的假红。所以先按 profile 路径清理。
try {
  execSync('powershell -NoProfile -Command "' +
    'Get-CimInstance Win32_Process -Filter \\"Name=\'msedge.exe\'\\" | ' +
    'Where-Object { $_.CommandLine -like \'*profile_card_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没有残留进程就够了，清理失败不影响后面的断言 */ }

const SUFFIX = String(Date.now()).slice(-6);
const ME = 'cardcheck' + SUFFIX;
const OTHER = 'cardcheck_other' + SUFFIX;
const PW = 'check123456';

let browser = null, ws = null, seq = 0;
const pending = new Map();
const problems = [];
const jsProblems = [];

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

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// 注入到页面最前面：只桩掉「别人主页」的数据源，其余 fetch 一律放行（真实服务端）。
// 另外记录 /api/profile/card 的请求体，供断言「8 个字段是否都发了」。
const STUB = `
(function () {
  window.__cardPosts = [];
  var orig = window.fetch;
  var mk = function (obj, status) {
    return Promise.resolve({ ok: (status || 200) < 400, status: status || 200,
      json: function () { return Promise.resolve(obj); },
      text: function () { return Promise.resolve(JSON.stringify(obj)); } });
  };
  window.fetch = function (url, opts) {
    var u = String(url);
    opts = opts || {};
    if (u.indexOf('/api/profile/card') === 0) {
      try { window.__cardPosts.push(JSON.parse(opts.body || '{}')); } catch (e) { window.__cardPosts.push({ __parse_error: String(opts.body) }); }
      return orig.apply(this, arguments);
    }
    if (u.indexOf('/user_stats') === 0) {
      if (u.indexOf('bravo_u') >= 0) {
        // 别人：三个 show_* 全关 → 战绩亮点 / 最爱用的卡 / 对局历史 三块都不该出现。
        // （show_stats / show_fav_cards 是 2026-09-17 补进契约的：只下发 show_history 时，
        //   前端读不到这两个开关 → 默认显示 → 开关形同虚设。）
        return mk({ stats: { id: 'u_other', username: 'bravo_u', wins: 7, losses: 9,
          current_streak: 0, longest_streak: 3, signature: '今天也要赢一局',
          avatar: '/static/avatars/default.png', rank: 7, title_id: 'sailor', title_name: '老水手',
          tags: ['steady', 'turtle'], status_text: '免战中', frame_id: 'silver', card_bg_id: 'graphite',
          fav_cards: [{ name: '仁王之盾', speed: 2, uses: 38 }, { name: '疗愈', speed: 1, uses: 22 }],
          show_history: 0, show_stats: 0, show_fav_cards: 0 }, history: [] });
      }
      var me = window.__USERNAME || '';
      return mk({ stats: { id: 'u_me', username: me, wins: 12, losses: 4, current_streak: 3,
        longest_streak: 6, signature: '我来也', avatar: '/static/avatars/default.png', rank: 3,
        title_id: 'hunter', title_name: '深海猎手', tags: ['aggressive', 'fast'],
        status_text: '找队友', frame_id: 'gold', card_bg_id: 'cyber',
        fav_cards: [{ name: '失灵！', speed: 3, uses: 41 }, { name: '神威！', speed: 3, uses: 33 },
                    { name: '越战越勇', speed: 2, uses: 27 }],
        show_history: 1, show_stats: 1, show_fav_cards: 1 },
        history: [ { match_id: 1, winner_id: 'u_me', loser_id: 'u_other', winner_name: me,
                     loser_name: 'bravo_u', timestamp: 1789201720, logs: [{ ts: 1789201800, text: '第一回合' }] },
                   { match_id: 2, winner_id: 'u_other', loser_id: 'u_me', winner_name: 'bravo_u',
                     loser_name: me, timestamp: 1789200000, logs: [] } ] });
    }
    if (u.indexOf('/api/leaderboard') === 0) {
      return mk([{ id: 'u_me', username: window.__USERNAME || '', wins: 12, losses: 4,
        current_streak: 3, longest_streak: 6, avatar: null }]);
    }
    return orig.apply(this, arguments);
  };
  return 'stubbed';
})()`;

// 一次性账号：先试登录，登录不上再注册（/register 会自动登录）
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

async function goto(url) {
  await send('Page.navigate', { url });
  // ⚠️ `Page.navigate` 返回后，有一小段时间 `document.readyState` 仍是**旧文档**的 complete，
  // 于是"等 readyState 就算加载完"会立刻通过、后续断言全打在上一页上（实测过一次假红）。
  // 所以要求「地址真的变成目标地址」+「新文档加载完成」两件事同时成立。
  const want = url.replace(/\/$/, '');
  await waitFor(async () => {
    const st = await ev('({ href: location.href.replace(/\\/$/, ""), ready: document.readyState })');
    return st && st.ready === 'complete' && st.href === want;
  }, 30000, '页面加载 ' + url);
  await sleep(500);
}

const MODAL = (id) => `(function(){ var m = document.getElementById(${JSON.stringify(id)}); return m ? !m.classList.contains('hidden') : 'missing'; })()`;

// 两态的真实入口：页头「个人信息」→ 查看态名片 → 名片上的「编辑资料」→ 编辑面。
// （设计稿要求「打开即干净名片」，所以页头不再直接摊开表单。）
const OPEN_EDITOR = `(async function () {
  var btn = document.getElementById('show-profile');
  if (btn) btn.click();
  for (var i = 0; i < 60; i++) {
    var b = document.querySelector('#profile-edit-btn');
    if (b) { b.click(); return 'clicked'; }
    await new Promise(function (r) { setTimeout(r, 150); });
  }
  return 'no-edit-btn';
})()`;

try {
  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank'], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^(https?|about|file):/.test(t.url || '')) || list.find((t) => t.type === 'page');
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

  // ---------- 0. 真实登录 ----------
  await goto(APP + 'register');
  const auth = await ev(AUTH);
  check(typeof auth === 'string' && /ok$/.test(auth), 'A0 真实注册/登录一次性账号（保存链路要真落库）', auth);
  await goto(APP);
  const me = await ev('window.__USERNAME');
  check(me === ME, 'A1 页面认得当前登录用户（window.__USERNAME）', me);
  check(await ev("typeof window.showUserProfile") === 'function', 'A2 showUserProfile 在 init 阶段就已可用（早期点击不再 ReferenceError）');

  // ---------- 1. 查看态 → 编辑态 ----------
  await ev('(function(){ document.getElementById("show-profile").click(); return true; })()');
  await waitFor(async () => (await ev(MODAL('opponent-stats-modal'))) === true, 12000, '查看态打开');
  // ⚠️ **弹窗可见 ≠ 内容就绪**：名片先渲染「加载中…」再异步取数。本地服务端快到看不出差别，
  // 但接口一变重（第 2 批给 /user_stats 多带了徽章数据）就会读到加载态 →
  // E1/E2 变成「名片没渲染」这种**假红**（生产探针也踩过同一个坑）。
  // 所以这里必须等到 `#profile-view` 真的出现。
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'),
    20000, '查看态渲染完成');
  const viewFirst = await ev(`(function(){
    var c = document.getElementById('opponent-stats-content');
    return { card: !!c.querySelector('#profile-view'),
      editBtn: !!c.querySelector('#profile-edit-btn'),
      formVisible: !document.getElementById('profile-modal').classList.contains('hidden') }; })()`);
  check(viewFirst && viewFirst.card === true, '★ E1 页头「个人信息」打开的是查看态名片（不再一上来就摊开表单）', viewFirst);
  check(viewFirst && viewFirst.formVisible === false, '★ E1b 此时编辑面还没有被摊开（改版的主要目的）', viewFirst && viewFirst.formVisible);
  check(viewFirst && viewFirst.editBtn === true, 'E2 自己的名片上有「编辑资料」入口', viewFirst && viewFirst.editBtn);

  const opened = await ev(OPEN_EDITOR);
  await waitFor(async () => (await ev(MODAL('profile-modal'))) === true, 12000, '编辑面打开');
  check(opened === 'clicked', '★ E3 名片上的「编辑资料」打开编辑面 #profile-modal', opened);
  // ★ 作者 2026-09-17 实测：「点编辑资料，编辑面开在个人信息窗口**下面**，得先手动关掉查看面」。
  // 根因是所有 .modal-overlay 共用 z-index 10000、DOM 里靠后的赢。这里把「查看面必须已关闭」
  // 与「编辑面确实在最上面（点得到）」两条都钉死 —— 只断言"编辑面存在"是抓不到这个 bug 的。
  const stack = await ev(`(function(){
    var view = document.getElementById('opponent-stats-modal');
    var editor = document.getElementById('profile-modal');
    var btn = document.getElementById('profile-card-save');
    var r = btn ? btn.getBoundingClientRect() : null;
    var top = null;
    if (r) { var el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); top = el ? (el.id || el.className) : null; }
    return { viewHidden: view ? view.classList.contains('hidden') : null,
      editorHidden: editor ? editor.classList.contains('hidden') : null,
      saveClickable: !!r && r.width > 0 && r.height > 0,
      topElementId: top }; })()`);
  check(stack && stack.viewHidden === true, '★ E3b 打开编辑面时查看面必须已经关掉（不再被压在下面）', stack);
  check(stack && stack.editorHidden === false && stack.saveClickable === true,
    '★ E3c 编辑面的「保存」真的在最上面、点得到（没有别的浮层挡着）', stack);
  check(await ev('!!document.getElementById("profile-edit")'), 'E4 编辑面里是 #profile-edit 编辑器');
  const nav = await ev(`(function(){
    var items = [].slice.call(document.querySelectorAll('.pf-editor-nav-item'));
    return { n: items.length, panes: items.map(function (i) { return i.dataset.pane; }) }; })()`);
  check(nav && nav.n === 4, 'E5 编辑面有 4 个分区导航（名片/头像/称号/账号）', nav);
  let navOk = true, navDetail = [];
  for (const p of ['card', 'avatar', 'title', 'account']) {
    await ev(`(function(){ var it = document.querySelector('.pf-editor-nav-item[data-pane="${p}"]'); if (it) it.click(); return true; })()`);
    await sleep(200);
    const v = await ev(`(function(){
      var shown = [].slice.call(document.querySelectorAll('.pf-pane')).filter(function (x) { return x.offsetHeight > 0; });
      return { n: shown.length, pane: shown[0] && shown[0].dataset.pane }; })()`);
    if (!(v && v.n === 1 && v.pane === p)) { navOk = false; navDetail.push({ want: p, got: v }); }
  }
  check(navOk, 'E6 点任一分区只显示那一块', navDetail);

  // 未解锁项必须灰掉并写明解锁条件（服务端才是最终裁决，前端只是不给选）
  const locked = await ev(`(function(){
    var all = [].slice.call(document.querySelectorAll('#profile-title-list .pf-opt'));
    var dis = all.filter(function (b) { return b.disabled; });
    var sample = dis[0];
    return { total: all.length, disabled: dis.length,
      hint: sample ? (sample.getAttribute('title') || '') : '',
      enabledClickable: all.filter(function (b) { return !b.disabled; }).length }; })()`);
  check(locked && locked.total >= 7, 'E7 称号池渲染出全部 7 个选项', locked && locked.total);
  check(locked && locked.disabled >= 1, '★ E8 未解锁称号是灰的（disabled）', locked && locked.disabled);
  check(locked && /≥|满|累计|无门槛/.test(locked.hint || ''), '★ E9 未解锁项写明了解锁条件', locked && locked.hint);

  // 标签限流：点满 4 个只允许 3 个。
  // ⚠️ 不要靠「猜选中态类名」来断言（第一版猜 on/active/aria-pressed，结果一个都没匹配到 →
  // 断言空过、看着是绿的）。真正的判据是**应用自己渲染的计数文案**与**最终发出去的数组**。
  const tags = await ev(`(function(){
    var btns = [].slice.call(document.querySelectorAll('#profile-tag-list .pf-opt'));
    var count = function () { var e = document.getElementById('profile-tag-count'); return e ? e.textContent.trim() : ''; };
    var before = count();
    btns.slice(0, 4).forEach(function (b) { b.click(); });
    var after4 = count();
    if (btns[4]) btns[4].click();          // 再点第 5 个也不该超过 3
    var after5 = count();
    return { n: btns.length, before: before, after4: after4, after5: after5 }; })()`);
  check(tags && /\/\s*3/.test(tags.after4 || '') && /3\s*\/\s*3/.test(tags.after4 || ''),
    '★ E10 点 4 个标签后计数仍停在 3（前端限流生效）', tags);
  check(tags && tags.after5 === tags.after4, '★ E10b 再点第 5 个标签也不越界', tags && { after4: tags.after4, after5: tags.after5 });

  // 状态文案 + 保存（真实 POST）
  const statusText = '回归检查 ' + SUFFIX;
  await ev(`(function(){ var el = document.getElementById('profile-edit-status'); if (!el) return 'no-el';
    el.value = ${JSON.stringify(statusText)};
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return 'set'; })()`);
  await sleep(200);
  await ev('(function(){ var b = document.getElementById("profile-card-save"); if (b) b.click(); return true; })()');
  await sleep(1500);
  const posts = await ev('window.__cardPosts || []');
  const post = posts && posts[0];
  const need = ['title_id', 'tags', 'status_text', 'frame_id', 'card_bg_id', 'show_stats', 'show_fav_cards', 'show_history'];
  check(!!post && need.every((k) => k in post), '★ E12 保存请求带齐全部 8 个字段（缺一个服务端就整次拒绝）',
    post ? { miss: need.filter((k) => !(k in post)) } : 'no-post');
  check(!!post && post.status_text === statusText, 'E13 状态文案随请求发出', post && post.status_text);
  check(!!post && Array.isArray(post.tags) && post.tags.length === 3,
    '★ E13b 发出去的标签确实只有 3 个（前端限流的最终判据）', post && post.tags);
  const saveMsg = await ev('(function(){ var m = document.getElementById("profile-save-msg"); return m ? m.textContent.trim() : null; })()');
  check(!!saveMsg && !/失败|错误|未登录/.test(saveMsg), 'E14 保存没有报错', saveMsg);

  // 持久化：刷新后仍在（真实库往返，不是只改了内存）
  await goto(APP);
  await ev(OPEN_EDITOR);
  await waitFor(async () => (await ev(MODAL('profile-modal'))) === true, 12000, '重新打开编辑面');
  const persisted = await ev('(function(){ var el = document.getElementById("profile-edit-status"); return el ? el.value : null; })()');
  check(persisted === statusText, '★ E15 刷新后状态文案仍在（真的落库了）', persisted);
  const persistedTags = await ev(`(function(){
    var r = fetch('/api/profile').then(function (x) { return x.json(); });
    return r.then(function (d) { var p = (d && d.profile) || {}; return { tags: p.tags, show_history: p.show_history, n: (p.catalog && p.catalog.tags || []).length }; }); })()`);
  check(persistedTags && persistedTags.tags && persistedTags.tags.length === 3, '★ E16 标签也落库了（3 个）', persistedTags);
  check(persistedTags && persistedTags.n === 12, 'E17 catalog 给出完整标签池（12 个）', persistedTags && persistedTags.n);
  await ev('(function(){ var m = document.getElementById("profile-modal"); if (m) m.classList.add("hidden"); return true; })()');

  // ---------- 2. 查看面（自己） ----------
  await ev(`(function(){ window.showUserProfile(${JSON.stringify(ME)}); return true; })()`);
  await waitFor(async () => (await ev(MODAL('opponent-stats-modal'))) === true, 12000, '查看面打开');
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'), 20000, '自己视角渲染完成');
  const mine = await ev(`(function(){
    var c = document.getElementById('opponent-stats-content');
    var q = function (s) { return c.querySelector(s); };
    var v = function (s) { var e = q(s); return e ? e.textContent.trim() : null; };
    return {
      card: !!q('#profile-view'),
      name: v('#profile-view-name'),
      title: v('#profile-view-title'),
      status: v('#profile-view-status'),
      tags: c.querySelectorAll('#profile-view-tags .tag').length,
      stats: [].slice.call(c.querySelectorAll('#profile-view-stats .stat')).map(function (s) { return s.dataset.stat + '=' + s.textContent.replace(/\\s+/g, ' ').trim(); }),
      favs: c.querySelectorAll('#profile-view-favcards .fav').length,
      history: c.querySelectorAll('#profile-view-history .match-history-btn').length,
      hasEdit: !!q('#profile-edit-btn')
    }; })()`);
  check(mine && mine.card === true, 'V1 查看面渲染出 #profile-view 名片', mine && mine.card);
  // 称号 chip 就嵌在名字行里（视觉上是「名字 [称号]」一行），所以只要求包含用户名；
  // 称号本身由 V3 单独断言 —— 断言写得比实现还死就会变成假红。
  check(mine && (mine.name || '').indexOf(ME) >= 0, 'V2 显示用户名', mine && mine.name);
  check(mine && mine.title === '深海猎手', '★ V3 显示称号（服务端给的中文名）', mine && mine.title);
  check(mine && mine.status === '找队友', 'V4 显示一句话状态', mine && mine.status);
  check(mine && mine.tags === 2, 'V5 显示标签 chip', mine && mine.tags);
  check(mine && mine.stats.length === 3, 'V6 三块战绩亮点（连胜/胜率/场次）', mine && mine.stats);
  check(mine && !/undefined|NaN/.test((mine.stats || []).join('')), '★ V6b 三块数字里没有 undefined/NaN', mine && mine.stats);
  check(mine && mine.favs === 3, 'V7 显示最爱用的卡 3 张', mine && mine.favs);
  check(mine && mine.history === 2, 'V8 自己能看到对局历史（本人视角永远完整）', mine && mine.history);
  check(mine && mine.hasEdit === true, '★ V9 看自己时有「编辑资料」按钮', mine && mine.hasEdit);

  // ---------- 3. 查看面（别人）+ 隐私 ----------
  await ev('(function(){ var m = document.getElementById("opponent-stats-modal"); if (m) m.classList.add("hidden"); return true; })()');
  await sleep(200);
  await ev('(function(){ window.showUserProfile("bravo_u"); return true; })()');
  await waitFor(async () => (await ev(MODAL('opponent-stats-modal'))) === true, 12000, '查看别人');
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'), 20000, '别人视角渲染完成');
  const other = await ev(`(function(){
    var c = document.getElementById('opponent-stats-content');
    var e = c.querySelector('#profile-history-empty');
    // 契约要求这两个 id 始终存在（T3 实现：容器渲染但加 hidden 且清空内容）。
    // 所以断言「存在 + 不可见 + 里面没有子项」——只查"看不见"会放过"id 干脆没了"。
    var probe = function (sel, childSel) {
      var x = c.querySelector(sel);
      return { exists: !!x, visible: x ? x.offsetHeight > 0 : null,
        children: x ? x.querySelectorAll(childSel).length : null };
    };
    return { card: !!c.querySelector('#profile-view'),
      hasEdit: !!c.querySelector('#profile-edit-btn'),
      historyRows: c.querySelectorAll('#profile-view-history .match-history-btn').length,
      empty: e ? { visible: e.offsetHeight > 0, text: e.textContent.trim() } : null,
      stats: probe('#profile-view-stats', '.stat'),
      favs: probe('#profile-view-favcards', '.fav'),
      title: (c.querySelector('#profile-view-title') || {}).textContent }; })()`);
  check(other && other.card === true, 'V10 看别人时用同一张名片', other && other.card);
  check(other && other.hasEdit === false, '★ V11 看别人时没有「编辑资料」按钮', other && other.hasEdit);
  check(other && other.historyRows === 0, '★ V12 别人未公开时不下发历史行', other && other.historyRows);
  check(other && other.empty && other.empty.visible === true, '★ V13 未公开时显示占位（不是留白）', other && other.empty);
  check(other && /未公开|不公开/.test((other.empty || {}).text || ''), '★ V14 占位文案说明是「未公开」', other && other.empty);
  // ★ 这两个开关以前是假控件：接口不下发 → 前端默认显示 → 关掉也没用。
  check(other && other.stats.exists === true && other.stats.visible === false && other.stats.children === 0,
    '★ V15 别人关掉「显示战绩亮点」后：块还在（契约 id 不消失）但不可见且无内容', other && other.stats);
  check(other && other.favs.exists === true && other.favs.visible === false && other.favs.children === 0,
    '★ V16 别人关掉「显示最爱用的卡」后：块还在但不可见且无内容', other && other.favs);

  // ---------- 4. 设置面：主题预设 + 左导航 ----------
  await ev('(function(){ var m = document.getElementById("opponent-stats-modal"); if (m) m.classList.add("hidden"); return true; })()');
  await ev('(function(){ document.getElementById("settings-btn").click(); return true; })()');
  await waitFor(async () => (await ev(MODAL('settings-modal'))) === true, 12000, '设置面打开');
  // ⚠️ 无头浏览器用的是**持久 profile**，上一轮跑完已经把预设存在 localStorage 里了。
  // 所以先切到「深海」把状态归零，再点「熔岩」——否则 before/after 会是同一个值，
  // 这条断言在第二次运行时必然假红（CLAUDE.md 第 12.13 条记的就是这个坑）。
  await ev('(function(){ var b = document.querySelector("#theme-preset-grid .theme-card[data-preset=\\"deep\\"]"); if (b) b.click(); return true; })()');
  await sleep(400);
  const before = await ev(`getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()`);
  await ev('(function(){ var b = document.querySelector("#theme-preset-grid .theme-card[data-preset=\\"lava\\"]"); if (b) b.click(); return true; })()');
  await sleep(400);
  const after = await ev(`getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()`);
  const presetAttr = await ev('document.documentElement.dataset.themePreset');
  const presetSaved = await ev(`localStorage.getItem('battleship_theme_preset')`);
  check(presetAttr === 'lava', 'T1 选主题预设后 html[data-theme-preset] = lava', presetAttr);
  check(!!before && before !== after, '★ T2 主色真的变了（换的是整套配色，不是只换按钮）', { before, after });
  check(presetSaved === 'lava', 'T3 预设记进 localStorage', presetSaved);

  let setNavOk = true, setNavDetail = [];
  for (const p of ['sound', 'wp', 'acct', 'look']) {
    await ev(`(function(){ var it = document.querySelector('.settings-nav-item[data-pane="${p}"]'); if (it) it.click(); return true; })()`);
    await sleep(220);
    const v = await ev(`(function(){
      var shown = [].slice.call(document.querySelectorAll('.settings-pane')).filter(function (x) { return x.offsetHeight > 0; });
      return { n: shown.length, pane: shown[0] && shown[0].dataset.pane }; })()`);
    if (!(v && v.n === 1 && v.pane === p)) { setNavOk = false; setNavDetail.push({ want: p, got: v }); }
  }
  check(setNavOk, '★ T4 设置面左导航每次只显示一个分类', setNavDetail);
  // 搬了位置的旧控件仍要在（id 不能丢）
  const movers = await ev(`(function(){
    var ids = ['wp-section','music-volume','music-loop-mode','music-toggle-play','primary-color-picker','change-password-form','settings-save-btn'];
    var miss = ids.filter(function (i) { return !document.getElementById(i); });
    var wp = document.getElementById('wp-section');
    return { miss: miss, wpVisibleInWpPane: !!wp }; })()`);
  check(movers && movers.miss.length === 0, '★ T5 搬进分区的旧控件 id 一个都没丢', movers);

  // ---------- 7. 同文档不得出现两套同名 id（真机链路） ----------
  // ⚠️ 这条必须**点真实入口**去验：直接调 renderUserStatsHTML(..., {}) 只会测到"函数默认值"，
  // 而查出来的问题恰恰在调用方写死了 `ids: true`（首页老容器也会输出 #profile-view-*）。
  // 同一文档里两个容器带同一批 id 时，document.getElementById 只拿得到靠前的那个 ——
  // 表现是「点了没反应」，本项目最难查的一类故障（2026-09-17 实测纠正过第 1 批的误解：
  // 老容器「只出 class 不出 id」那句注释与代码不符）。
  await ev('(function(){ var m = document.getElementById("settings-modal"); if (m) m.classList.add("hidden"); return true; })()');
  await ev('(function(){ var m = document.getElementById("opponent-stats-modal"); if (m) m.classList.add("hidden"); return true; })()');
  await ev('(function(){ var a = document.getElementById("show-user-stats"); if (a) a.click(); return true; })()');
  await sleep(1800);
  const dupIds = await ev(`(function(){
    var home = document.getElementById('user-stats-content');
    var view = document.getElementById('opponent-stats-content');
    var n = function (el) { return el ? el.querySelectorAll('[id^="profile-view"]').length : null; };
    var txt = home ? home.innerText.replace(/\\s+/g, '') : '';
    return { homeIds: n(home), viewIds: n(view),
      homeRendered: txt.length > 0 && txt.indexOf('加载中') === -1 }; })()`);
  check(dupIds && dupIds.homeIds === 0,
    '★ D1 首页「个人战绩」老容器**不输出** #profile-view-* 那套 id（同文档不许撞 id）', dupIds);
  check(dupIds && dupIds.homeRendered === true,
    'D1b 该断言不是假绿：老容器确实渲染出内容了（只是不带那套 id）', dupIds && dupIds.homeRendered);
  await ev('(function(){ var m = document.getElementById("user-stats-modal"); if (m) m.classList.add("hidden"); return true; })()');

  // ★ 入口按钮必须落在**对应分区**上：设置页重排后，「点了按钮却看不到那块设置」
  //   是最容易漏的回归（🎬 壁纸 / 🎵 音乐 都会中招：只 remove('hidden') 而不切分区，
  //   玩家看到的是「外观与主题」，目标控件根本不在文档流里）。
  for (const [btn, pane, sel, label] of [
    ['wallpaper-btn', 'wp', '#wp-section', 'T7 🎬 壁纸按钮'],
    ['music-btn', 'sound', '#music-volume', 'T8 🎵 音乐按钮'],
  ]) {
    await ev('(function(){ var m = document.getElementById("settings-modal"); if (m) m.classList.add("hidden"); return true; })()');
    await sleep(200);
    await ev(`(function(){ var b = document.getElementById(${JSON.stringify(btn)}); if (b) b.click(); return true; })()`);
    await sleep(700);
    const landed = await ev(`(function(){
      var m = document.getElementById('settings-modal');
      var panes = [].slice.call(document.querySelectorAll('.settings-pane')).filter(function (x) { return x.offsetHeight > 0; });
      var target = document.querySelector(${JSON.stringify(sel)});
      return { open: m ? !m.classList.contains('hidden') : false,
        visiblePane: panes.length === 1 ? panes[0].dataset.pane : panes.map(function (p) { return p.dataset.pane; }),
        targetVisible: target ? target.offsetHeight > 0 : null }; })()`);
    check(landed && landed.open === true && landed.visiblePane === pane && landed.targetVisible === true,
      `★ ${label}点下去要落在「${pane}」分区、且目标控件真的可见`, landed);
  }
  await ev('(function(){ var m = document.getElementById("settings-modal"); if (m) m.classList.add("hidden"); return true; })()');

  // 刷新后预设仍生效
  await goto(APP);
  const afterReload = await ev('document.documentElement.dataset.themePreset');
  check(afterReload === 'lava', 'T6 刷新后主题预设仍然生效', afterReload);

  // ---------- 5. 窄屏 ----------
  for (const w of [390, 336]) {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(300);
    const o = await ev('(function(){ return { sw: document.scrollingElement.scrollWidth, iw: innerWidth }; })()');
    check(o.sw <= o.iw + 1, `${w}px 宽页面无横向溢出`, o);
    await ev('(function(){ document.getElementById("settings-btn").click(); return true; })()');
    await sleep(400);
    const o2 = await ev('(function(){ var m = document.getElementById("settings-modal"); var c = m && m.querySelector(".modal-content");' +
      ' return { sw: c ? c.scrollWidth : 0, cw: c ? c.clientWidth : 0, open: m ? !m.classList.contains("hidden") : false }; })()');
    check(o2.open === true && o2.sw <= o2.cw + 4, `${w}px 宽设置面没有横向溢出/截断`, o2);
    await ev('(function(){ var m = document.getElementById("settings-modal"); if (m) m.classList.add("hidden"); return true; })()');
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await sleep(300);

  // ---------- 6. 反向自检：工具必须真的看得出「该显示的东西没显示」 ----------
  const neg = await ev(`(function(){
    window.showUserProfile(${JSON.stringify(ME)});
    return true; })()`);
  await sleep(1200);
  const negProbe = await ev(`(function(){
    var c = document.getElementById('opponent-stats-content');
    var fav = c.querySelector('#profile-view-favcards');
    if (!fav) return { skip: 'no-favcards' };
    var before = fav.offsetHeight > 0;
    fav.classList.add('hidden');
    var afterHidden = fav.offsetHeight === 0;
    fav.classList.remove('hidden');
    var restored = fav.offsetHeight > 0;
    return { before: before, afterHidden: afterHidden, restored: restored }; })()`);
  check(negProbe && negProbe.afterHidden === true && negProbe.restored === true,
    '★ N1 探针能看出区块被隐藏（证明上面的断言不是假绿）', negProbe);

  if (SHOT) {
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(png.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }

  check(jsProblems.length === 0, '全程无 JS 异常 / console.error', jsProblems.slice(0, 4));
} catch (err) {
  console.error('检查中断: ' + err.message);
  problems.push('中断: ' + err.message);
} finally {
  try { if (ws) ws.close(); } catch (e) { /* ignore */ }
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
}

console.log('');
console.log(problems.length ? ('✗ ' + problems.length + ' 项未通过: ' + problems.join(' | ')) : '✓ 全部通过');
process.exit(problems.length ? 1 : 0);
