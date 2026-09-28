#!/usr/bin/env node
/**
 * 更新公告 UI 回归检查（无头 Edge + CDP + 真接口，全部断言真实 DOM / 真实响应）。
 *
 * 契约：`changelog.py`（唯一真源）、`GET /api/changelog`、`static/game.js` 末尾「更新公告」一节。
 *
 * ---------------------------------------------------------------------------
 * 为什么必须有这个工具（而不是只跑 pytest）
 * ---------------------------------------------------------------------------
 * 公告这个功能的**全部价值**都在浏览器那一边：
 *   · "有没有新公告"是拿 `localStorage` 里存的时间跟接口的 `latest` 比出来的；
 *   · "自动弹一次"是 `setTimeout(…, 900)` 的异步决定，还要看登录态 / 有没有别的浮层开着；
 *   · 渲染是"先清空再填"，而空面板**看起来跟正常面板一模一样**。
 * 这四件事的失败形状全是**静默**的：`getElementById` 拿 null 被 `if (el)` 兜掉、
 * `.hidden` 被作者样式的 display 压过去、`localStorage` 键名写错一个字 ——
 * 玩家眼里只是"公告永远不弹"或者"每次进站都烦我一次"，而 pytest 一条都不会红。
 *
 * ---------------------------------------------------------------------------
 * 覆盖（每一条都刻意做成**能区分假绿**的形状）
 * ---------------------------------------------------------------------------
 *   D1  接口契约：`status=ok` / `latest` 非空 / `entries` 非空且每条有 `date`+`items`；
 *       `entries[0].date === latest`（红点判据认的就是 `latest`，两者不一致就是"每次进站都弹"）；
 *       `limit` 的夹取（1 / 0 / 999 / 非数字）与"默认就是前 10 条"（跟 limit=20 的头部逐条比）。
 *   D2  入口：`#changelog-btn` 存在且**真的可见可点**（有盒子、在视口内、没被遮挡）；
 *       `#changelog-dot` **初始就是隐藏的**（默认亮着 = 永远消不掉的红点，比不加还烦人）。
 *   D3  **游客也能看**：点入口 → 面板可见 → 面板内容与接口**逐条逐字**比对
 *       （`.changelog-date` 文本 == 接口 date；`.changelog-items li` 文本数组 == 接口 items）。
 *       ⚠️ 断言里**一个公告字面量都没有** —— 抄进工具就等于第二份实现，以后每次改公告都要改工具。
 *   D4  自动提示（已登录）：清 `seen` 后刷新 → 自动弹出 + 写回 `latest`；
 *       再刷新 → **不再弹**（"看过就不烦人"）；把 `seen` 改成 2000 年的旧值 → **又弹**
 *       （"每次新更新都显示这一条的时间和内容"）。
 *   D5  **游客不自动弹**：清 localStorage 后以游客刷新 → 等过那个 900ms 决定，面板始终不弹；
 *       但**入口仍可点、面板照常满**，而且 `#changelog-dot` 此时**应当亮着**（有没看过的更新）。
 *   D6  浮层互斥，**两个方向都验**：先开帮助再点公告 → 帮助被 `hidden`；
 *       先开公告再点帮助 → 公告被 `hidden`。
 *   D7  有别的浮层开着时**不抢屏**：帮助开着 + 有没看过的更新 → 自动提示不许把帮助盖掉，
 *       红点留着（这是"公告绝不挡路"的产品承诺）。
 *   D8  窄屏（390x844）：文档与面板都不横向溢出，条目文字不伸出视口。
 *   D9  零 JS 异常 / 零应用级 console.error（全程）；
 *       并且用 CDP `Fetch` 域把 `/api/changelog` 伪造成 **500** 后刷新 ——
 *       页面必须**静默**：不弹错误、不报异常、入口照样点得开（面板空着）。
 *
 * ---------------------------------------------------------------------------
 * 用法
 * ---------------------------------------------------------------------------
 *   服务端（工具**不会**自己起）：
 *     $env:PORT='5120'; $env:CORS_ORIGINS='http://127.0.0.1:5120';
 *     $env:BATTLESHIP_DB_PATH='.tmp\changelog_ui.db'; python server.py
 *   （⚠️ `CORS_ORIGINS` 少了 socket.io 会**静默连不上**，页面无报错。）
 *
 *   node tools/changelog_check.mjs [--url http://127.0.0.1:5120/] [--db .tmp/changelog_ui.db] [--shot out.png]
 *
 * ---------------------------------------------------------------------------
 * 踩过的坑（写在这里，别下次再踩）
 * ---------------------------------------------------------------------------
 * 1. ⚠️ **`seen` 那个键的名字不许抄**：产品里叫 `battleship_seen_changelog`（`CHANGELOG_SEEN_KEY`）。
 *    本工具跑之前拿到的说明里写的是"`battleship_active_game`"那种形状，但产品里**对局记录**的键
 *    其实叫 `battle_active_game`（没有 ship）—— 键名写错一个字的症状是"清了等于没清"，
 *    断言全成假红，而红的原因看着像产品没实现清 localStorage。所以这里**两件事都做了**：
 *    ① 默认值照产品抄一遍；② 用不上时**在页面里把它找出来**（看哪个 localStorage 键的值
 *    恰好等于接口的 `latest`），找得到就用找到的那个 —— 以后产品换键名，工具跟着走；
 *    两个都找不到才判红，并明确说"这不是产品的错，是工具没跟上"。
 * 2. ⚠️ **残留无头进程是第一大假红来源**：`proc.kill()` 在 Windows 上杀不掉 Edge 的孙进程，
 *    残留实例会占着调试端口 + 锁住 profile，新浏览器**静默起不来**，你连上的是上一轮的旧页面。
 *    所以开头按 **profile 路径**匹配命令行、用 `Stop-Process -Force` 全清（不是 kill pid）。
 * 3. ⚠️ **持久 profile 带着上一轮的 cookie**：游客那几条断言（D3/D5）之前必须
 *    `Network.clearBrowserCookies`，否则"游客"其实是上一轮登录过的那个人。
 * 4. ⚠️ **`.hidden` 只有一个类名、没有 `hidden` 属性**：`.changelog-dot` 自带
 *    `display: inline-block`，浏览器对 `[hidden]` 的默认样式**压不住**它 —— 所以判"亮不亮"
 *    一律看 `getComputedStyle().display`，不看 `el.hidden`（那个字段在这里恒为 false，会假绿）。
 * 5. ⚠️ **"自动弹"是个异步决定**：`setTimeout(…, 900)` 之后才去判断，直接取样会 race。
 *    本工具的做法是：先把"还没弹"这条**证据**钉住（红点没亮 + 面板没开 = 那个决定还没做完），
 *    再手动叫一次 `maybeAnnounceChangelog()` 并把这次决定到面板出现的时间量出来。
 * 6. ⚠️ 伪造 500 用 CDP 的 `Fetch` 域，**必须 await `Fetch.fulfillRequest`**：
 *    忘了 await 会让请求一直悬着（页面看着像卡死，其实是工具自己没回话）。
 *    而且 `Fetch.enable` 用的 `requestStage: 'Request'` —— 在请求阶段就答，页面一个字节都不出去。
 * 7. ⚠️ 浏览器自己会因为 500 打一条 `console` 消息（"Failed to load resource"），
 *    那是**网络层**的、不是应用代码报的错 —— 跟 `Runtime.exceptionThrown`（真异常）分开记，
 *    否则"接口 500 时页面静默"这条永远假红。
 * 8. ⚠️ `#changelog-btn` 带着 `hide-in-game` 类（进对局后隐藏），首页上是**可见**的；
 *    但"可见"不能只看类名 —— 一律量盒子（宽高非 0 + 落在一屏内 + 没有被别的元素盖住）。
 */

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

// ---------- 参数 ----------
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5120/').replace(/\/?$/, '/');
const SHOT = argOf('--shot', '');
const DB = argOf('--db', '');

let HERE;
try { HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')); }
catch (e) { HERE = process.cwd(); }
const ROOT = path.resolve(HERE, '..');
const TMP = path.join(ROOT, '.tmp');

const PORT = 9391;                       // ⚠️ 别用 9361/9362/9371/9372/9381（别的工具占着）
const PROFILE_DIR = path.join(TMP, 'changelog_check_profile');
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过更新公告检查'); process.exit(0); }
fs.mkdirSync(TMP, { recursive: true });

// ---------- 预清理：按 profile 路径杀残留（见文件头「坑 2」） ----------
// 不看 pid、不看父进程：命令行里带本 profile 路径的所有 msedge（含孙进程）一律清掉。
try {
  spawnSync('powershell', ['-NoProfile', '-Command',
    'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
    'Where-Object { $_.CommandLine -like \'*changelog_check_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'],
    { stdio: 'ignore', timeout: 25000 });
} catch (e) { /* 没有残留就够 */ }
await sleep(400);

// ---------- 断言账本 ----------
const passes = [];
const failures = [];
const appProblems = [];      // 页面里的**真** JS 异常（Runtime.exceptionThrown）
const consoleErrors = [];    // console.error（应用 + 浏览器）
const browserNoise = [];     // 浏览器因为网络失败自己打的 console 消息（不算应用报错）

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label +
    (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (ok) passes.push(label); else failures.push(label);
}

// ---------- Node 侧账号（注册 + 登录 + cookie） ----------
// ⚠️ `/register` 与 `/login` 各有**同 IP 60 秒 10 次**限流（api.py `_rate_limited`）：
//    超限后是 302 + flash「操作过于频繁」（`/register` 不种 session），而症状是
//    "账号没登进去" —— 看着像 cookie 传坏了。所以**先 register**（成功时它直接把 session 种好，
//    一次登录都不用发，省配额），失败再走 login 重试，并且只在**认出限流**时才等窗口。
const SUFFIX = String(Date.now()).slice(-6);
const PW = 'check123456';
const U = 'chgchk_' + SUFFIX;

function readCookie(resp) {
  const raw = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [resp.headers.get('set-cookie')].filter(Boolean);
  const pairs = raw.map((c) => String(c).split(';')[0]).filter(Boolean);
  return pairs.length ? pairs.join('; ') : '';
}
const LIMIT_RE = /操作过于频繁/;

async function nodeAuth(username) {
  const verify = async (cookie) => {
    if (!cookie) return '';
    try {
      const r = await fetch(APP + 'api/profile', { headers: { Accept: 'application/json', Cookie: cookie } });
      if (!r.ok) return '';
      const body = await r.json();
      const me = body && body.profile ? String(body.profile.username || '') : '';
      return me === username ? cookie : '';
    } catch (e) { return ''; }
  };
  const post = (p) => fetch(APP + p, {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: username, password: PW }).toString()
  });
  const reg = await post('register');
  let cookie = await verify(readCookie(reg));
  if (cookie) return cookie;
  for (let i = 0; i < 8; i++) {
    await sleep(6000);                       // 60 秒窗口：被限流就等它滑过去
    const a = await post('login');
    const text = await a.text().catch(() => '');
    cookie = await verify(readCookie(a));
    if (cookie) return cookie;
    if (!LIMIT_RE.test(text)) break;         // 不是限流就别死等
  }
  return '';
}

// ---------- CDP ----------
let browser = null, ws = null, seq = 0;
const pending = new Map();
let eventHook = null;                        // 需要 await 的事件处理（Fetch 域）挂在这里

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
    try { last = await fn(); if (last) return last; } catch (e) { last = 'err:' + e.message; }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label + '  (最后 ' + JSON.stringify(last) + ')');
}
async function goto(url) {
  await send('Page.navigate', { url });
  const want = url.replace(/\/$/, '');
  await waitFor(async () => {
    const st = await ev('({ href: location.href.replace(/\\/$/, ""), ready: document.readyState })');
    return st && st.ready === 'complete' && st.href === want;
  }, 30000, '页面加载 ' + url);
  await sleep(400);
}
async function clickJs(selectorExpr) {
  const r = await ev('(function(){ var el = ' + selectorExpr + '; if (!el) return {ok:false,why:"not-found"};'
    + ' el.click(); return {ok:true}; })()');
  if (!r || !r.ok) throw new Error('点击失败 ' + selectorExpr + ' -> ' + JSON.stringify(r));
  return r;
}
async function setCookie(c) {
  const u = new URL(APP);
  for (const p of String(c).split(';').map((s) => s.trim()).filter(Boolean)) {
    const i = p.indexOf('=');
    if (i < 0) continue;
    await send('Network.setCookie', { name: p.slice(0, i), value: p.slice(i + 1), domain: u.hostname, path: '/', url: APP });
  }
}

// ---------- 页面探针 ----------
// 一次把「入口 / 红点 / 面板 / 条目」取全 —— 分多次取样会把中间态判进去（假红）
const PROBE = `(function(){
  function vis(el){
    if (!el) return { exists:false, visible:false };
    var cs = getComputedStyle(el);
    var r = el.getBoundingClientRect();
    return {
      exists: true,
      display: cs.display,
      visibility: cs.visibility,
      opacity: cs.opacity,
      w: Math.round(r.width), h: Math.round(r.height),
      visible: cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0.05
               && r.width > 0 && r.height > 0,
      hasHiddenClass: el.classList.contains('hidden'),
      inView: r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0 && r.left < innerWidth && r.right > 0
    };
  }
  var btn = document.getElementById('changelog-btn');
  var dot = document.getElementById('changelog-dot');
  var modal = document.getElementById('changelog-modal');
  var list = document.getElementById('changelog-list');
  var entries = [].slice.call(document.querySelectorAll('#changelog-list .changelog-entry'));
  var btnR = btn ? btn.getBoundingClientRect() : null;
  // 入口中心点上"最上面那个元素是不是它自己"（被别的浮层盖住 = 点不到）
  var topAtCenter = null;
  if (btnR && btnR.width > 0) {
    var hit = document.elementFromPoint(Math.round(btnR.left + btnR.width / 2), Math.round(btnR.top + btnR.height / 2));
    topAtCenter = hit ? (hit.id || hit.className || hit.tagName) : null;
  }
  return {
    user: window.__USERNAME || null,
    hasOpenChangelogFn: typeof window.openChangelog === 'function',
    hasAnnounceFn: typeof window.maybeAnnounceChangelog === 'function',
    btn: vis(btn),
    btnTopAtCenter: topAtCenter,
    dot: vis(dot),
    modal: vis(modal),
    modalOverlayClass: modal ? modal.className : null,
    listText: list ? list.textContent.slice(0, 60) : null,
    entryCount: entries.length,
    dates: entries.map(function(e){
      var d = e.querySelector('.changelog-date');
      return d ? d.textContent : null;
    }),
    items: entries.map(function(e){
      return [].slice.call(e.querySelectorAll('.changelog-items li')).map(function(li){ return li.textContent; });
    }),
    openOverlays: [].slice.call(document.querySelectorAll('.modal-overlay:not(.hidden)'))
      .map(function(el){ return el.id; })
  };
})()`;

// 某个元素此刻的盒子（窄屏溢出断言用）
const BOXES = `(function(){
  var out = {};
  out.vw = innerWidth;
  out.de = document.documentElement;
  var modal = document.getElementById('changelog-modal');
  var list = document.getElementById('changelog-list');
  out.docScrollW = out.de.scrollWidth;
  out.bodyScrollW = document.body.scrollWidth;
  function box(el){
    if (!el) return null;
    var r = el.getBoundingClientRect();
    return { left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width),
             scrollW: el.scrollWidth, clientW: el.clientWidth };
  }
  out.modal = box(modal);
  out.list = box(list);
  out.entries = [].slice.call(document.querySelectorAll('#changelog-list .changelog-entry')).map(box);
  out.overs = [].slice.call(document.querySelectorAll('#changelog-list .changelog-date, #changelog-list .changelog-items li'))
    .filter(function(el){ return el.getBoundingClientRect().right > innerWidth + 1; }).length;
  return out;
})()`;

// ---------- 键名解析（见文件头「坑 1」） ----------
// 产品的两个键：公告"看过"的键照抄默认值；对局键只用于"清干净"，找不到也不算错。
const SEEN_KEY_DEFAULT = 'battleship_seen_changelog';
let SEEN_KEY = SEEN_KEY_DEFAULT;             // 解析成功后会被换成页面里真正在用的那个
// 对局键只用来"清干净现场"，**D4x 那条断言不认这个默认值**（它从 static/game.js 里现场取）
const ACTIVE_GAME_KEY = 'battle_active_game';

async function resolveSeenKey(latest) {
  // ① 默认键名在页面里存着 `latest` → 就是它
  const direct = await ev(`(function(){ try { return localStorage.getItem(${JSON.stringify(SEEN_KEY_DEFAULT)}); } catch(e){ return null; } })()`);
  if (direct === latest) return SEEN_KEY_DEFAULT;
  // ② 否则把页面里所有"值恰好等于 latest"的键翻出来（产品改名后工具自己跟上）
  const found = await ev(`(function(){
    try {
      var hits = [];
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (localStorage.getItem(k) === ${JSON.stringify(String(latest))}) hits.push(k);
      }
      return hits;
    } catch (e) { return []; }
  })()`);
  const pick = (found || []).find((k) => /seen|changelog/i.test(k));
  if (pick) return pick;
  return null;                               // 两个都找不到 → 调用方判红（工具没跟上，不是产品的错）
}

// 清掉"看过"与"进行中的对局"两个键（清不干净时 D4/D5 会假红，所以返回实际结果供断言）
async function clearLocalState() {
  return ev(`(function(){
    var out = { seen: null, active: null, before: localStorage.length };
    try {
      localStorage.removeItem(${JSON.stringify(SEEN_KEY)});
      localStorage.removeItem(${JSON.stringify(ACTIVE_GAME_KEY)});
      out.seen = localStorage.getItem(${JSON.stringify(SEEN_KEY)});
      out.active = localStorage.getItem(${JSON.stringify(ACTIVE_GAME_KEY)});
    } catch (e) { out.error = String(e); }
    return out;
  })()`);
}
async function setSeen(v) {
  return ev(`(function(){ try { localStorage.setItem(${JSON.stringify(SEEN_KEY)}, ${JSON.stringify(String(v))});
    return localStorage.getItem(${JSON.stringify(SEEN_KEY)}); } catch (e) { return 'ERR:' + e; } })()`);
}

// ---------- 主流程 ----------
async function main() {
  console.log('== 更新公告 UI 回归检查 ==');
  console.log('   APP = ' + APP);
  console.log('   DB  = ' + (DB || '(服务端自己的 BATTLESHIP_DB_PATH)'));
  console.log('   账号 = ' + U + '（一次性：只用来验"已登录才自动弹"）');
  console.log('');

  // ---------- D1：接口契约（先把真源拿到手，后面所有 DOM 断言都跟它比） ----------
  const api = async (q) => {
    const r = await fetch(APP + 'api/changelog' + (q || ''), { headers: { Accept: 'application/json' } })
      .catch((e) => ({ status: 0, _err: String(e.message), json: async () => null, text: async () => '' }));
    let body = null;
    try { body = await r.json(); } catch (e) { /* 非 JSON */ }
    return { status: r.status, body: body, err: r._err || null };
  };
  const full = await api('?limit=20');
  if (full.status === 0) throw new Error('服务端连不上（' + APP + '）—— 先起服务再跑本工具');
  check(full.status === 200, '★ D1a /api/changelog 公开可读且 200（不带任何 cookie）', { status: full.status });

  const bodyOk = !!(full.body && full.body.status === 'ok' && !full.body.error);
  check(bodyOk, '★ D1b 响应里有 status=ok（而不是 error/未登录跳转）',
    full.body ? { status: full.body.status, error: full.body.error } : full.body);

  const entries = (full.body && Array.isArray(full.body.entries)) ? full.body.entries : [];
  const latest = full.body ? String(full.body.latest || '') : '';
  const shapeOk = entries.length > 0 && entries.every((e) => e && typeof e.date === 'string' && e.date
    && Array.isArray(e.items) && e.items.length > 0 && e.items.every((x) => typeof x === 'string' && x.length > 0));
  check(shapeOk, '★ D1c latest 非空、entries 非空，且每条都有非空 date + 非空 items（每项都是非空字符串）',
    { latest: latest, entries: entries.length, bad: entries.filter((e) => !e || !e.date || !Array.isArray(e.items) || !e.items.length).length });
  check(latest && entries.length > 0 && String(entries[0].date) === latest,
    '★ D1d entries[0].date === latest（红点判据认的是 latest；两者不一致 = 每次进站都弹一遍）',
    { latest: latest, first: entries.length ? entries[0].date : null });

  const one = await api('?limit=1');
  check(one.status === 200 && one.body && Array.isArray(one.body.entries) && one.body.entries.length === 1,
    '★ D1e limit=1 只回 1 条', one.body ? { status: one.status, n: (one.body.entries || []).length } : one);
  check(one.body && String(one.body.latest) === latest,
    '★ D1f limit=1 时 latest 仍是全局最新（截断不改"最新是哪一条"）', one.body ? one.body.latest : null);

  // limit 的夹取口径（changelog.view：1..20）；非数字回落 10。
  // 只钉"上下界与默认"这三件事，不钉具体条数 —— 公告条数是数据自己的事。
  const z = await api('?limit=0');
  const big = await api('?limit=999');
  const junk = await api('?limit=abc');
  check(z.body && (z.body.entries || []).length === 1, '★ D1g limit=0 被夹到至少 1 条（不是 0 条空面板）',
    z.body ? (z.body.entries || []).length : z);
  check(big.body && (big.body.entries || []).length === Math.min(20, entries.length),
    '★ D1h limit=999 被夹到上限 20（不回整份内部列表）',
    big.body ? { got: (big.body.entries || []).length, want: Math.min(20, entries.length) } : big);
  const defaultN = Math.min(10, entries.length);
  const junkSame = junk.body && Array.isArray(junk.body.entries) && junk.body.entries.length === defaultN
    && (junk.body.entries || []).every((e, i) => String(e.date) === String(entries[i].date)
      && JSON.stringify(e.items) === JSON.stringify(entries[i].items));
  check(!!junkSame, '★ D1i limit 非数字回落默认（就是前 ' + defaultN + ' 条，与 limit=20 的头部逐条一致）',
    junk.body ? (junk.body.entries || []).length : junk);

  if (!shapeOk) throw new Error('接口形状不对，后面的 DOM 比对没有意义 —— 先修接口');

  // ---------- 起浏览器 ----------
  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--no-proxy-server', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=1400,900', '--force-device-scale-factor=1',
    'about:blank'], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^(https?|about|file):/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还在启动 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口 ' + PORT + '（多半是残留进程占着 profile）');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });

  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    // 需要 await 的事件（Fetch 域）单独走，await 完再回话；不 await 会把请求悬住（见文件头「坑 6」）
    if (eventHook) { eventHook(m).catch(() => {}); return; }
    collectEvent(m);
  };

  function collectEvent(m) {
    if (m.method === 'Runtime.exceptionThrown') {
      const ex = m.params.exceptionDetails || {};
      const desc = (ex.exception && (ex.exception.description || ex.exception.value)) || ex.text;
      appProblems.push('JS 异常: ' + String(desc).slice(0, 240));
      console.log('   [异常详情] ' + String(desc).slice(0, 700));
      if (ex.stackTrace && ex.stackTrace.callFrames) {
        console.log('   [调用栈] ' + ex.stackTrace.callFrames.slice(0, 6)
          .map((f) => (f.functionName || '?') + '@' + f.lineNumber).join(' <- '));
      }
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      const txt = m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 240);
      // ⚠️ 500 那条是浏览器网络层自己打的（见文件头「坑 7」），与应用代码报错分开记
      const isNet = /Failed to load resource|net::ERR|the server responded with a status of/i.test(txt);
      (isNet ? browserNoise : consoleErrors).push(txt);
      if (!isNet) console.log('   [console.error] ' + txt);
    }
  }

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  try { await send('Page.bringToFront'); } catch (e) { /* 无头下不支持就算了 */ }

  // ---------- 先按**游客**跑（D2/D3/D5/D6/D7/D8） ----------
  // ⚠️ 持久 profile 会带着上一轮的 cookie：不 clear 的话下面的"游客"其实是已登录的人（见文件头「坑 3」）
  await send('Network.clearBrowserCookies').catch(() => {});
  await goto(APP);
  await ev('(function(){ try { localStorage.clear(); } catch(e){} return true; })()');
  await goto(APP);
  const fresh = await ev(PROBE);
  check(fresh.user === null, '★ D0a 此刻确实是**游客**（没有 __USERNAME；否则后面"游客不自动弹"全是假绿）', fresh.user);

  // ---------- D2：入口与红点 ----------
  const hitId = String(fresh.btnTopAtCenter || '');
  check(fresh.btn.exists && fresh.btn.visible && fresh.btn.inView,
    '★ D2a #changelog-btn 存在、真的可见（有盒子 + 落在一屏内）、display≠none',
    { exists: fresh.btn.exists, visible: fresh.btn.visible, inView: fresh.btn.inView, w: fresh.btn.w, h: fresh.btn.h, hasHiddenClass: fresh.btn.hasHiddenClass });
  check(hitId === 'changelog-btn' || hitId.indexOf('changelog') >= 0,
    '★ D2b 入口没被别的元素盖住（中心点上最顶层的元素是它自己，所以点得到）', { topAtCenter: fresh.btnTopAtCenter });
  // 页刚加载：红点必须是隐藏的（这里看 computed display，不看 .hidden 属性 —— 见文件头「坑 4」）
  check(fresh.dot.exists && fresh.dot.display === 'none' && fresh.dot.hasHiddenClass,
    '★ D2c #changelog-dot 初始是 hidden（red dot 默认亮着 = 永远消不掉的红点）',
    { display: fresh.dot.display, hasHiddenClass: fresh.dot.hasHiddenClass });
  check(fresh.modal.exists && !fresh.modal.visible && fresh.modal.hasHiddenClass,
    '★ D2d #changelog-modal 初始不显示（它是 .modal-overlay，才参与浮层互斥）',
    { visible: fresh.modal.visible, cls: fresh.modalOverlayClass });

  // ---------- D3：游客点开 → 内容与接口逐字一致 ----------
  await clickJs("document.getElementById('changelog-btn')");
  const opened = await waitFor(async () => {
    const p = await ev(PROBE);
    return p.modal.visible && p.entryCount === entries.length ? p : null;
  }, 8000, '游客点开公告面板并渲染出 ' + entries.length + ' 条').catch(async () => await ev(PROBE));
  check(opened.modal.visible, '★ D3a 游客点入口 → #changelog-modal 可见（公告是公开的，不该只有登录用户能看）',
    { visible: opened.modal.visible, cls: opened.modalOverlayClass });
  check(opened.entryCount === entries.length,
    '★ D3b 面板里 .changelog-entry 条数 == 接口 entries.length（不写死数字）',
    { dom: opened.entryCount, api: entries.length });
  const dateMismatch = entries.map((e, i) => ({ i: i, api: String(e.date), dom: opened.dates[i] }))
    .filter((x) => x.dom !== x.api);
  check(dateMismatch.length === 0,
    '★ D3c 每条 .changelog-date 的文本 == 接口第 i 条的 date（时间原样下发，前端不重算格式）',
    dateMismatch.slice(0, 4));
  const itemMismatch = [];
  entries.forEach((e, i) => {
    const dom = opened.items[i] || [];
    const api = e.items.map(String);
    if (JSON.stringify(dom) !== JSON.stringify(api)) itemMismatch.push({ i: i, api: api, dom: dom });
  });
  check(itemMismatch.length === 0,
    '★ D3d 每条 .changelog-items li 的文本数组 == 接口第 i 条的 items（**逐条逐字**，工具里没有任何公告字面量）',
    itemMismatch.slice(0, 2));
  check(opened.listText && opened.listText.trim().length > 0 && String(opened.dates[0]) === latest,
    '★ D3e 面板首条就是 latest（玩家第一眼看到的是"这次改了什么"）',
    { first: opened.dates[0], latest: latest });

  // ---------- 关闭面板（守住 #changelog-close） ----------
  await clickJs("document.getElementById('changelog-close')");
  const closedByX = await waitFor(async () => {
    const p = await ev(PROBE);
    return !p.modal.visible ? p : null;
  }, 4000, '点 × 后面板收起').catch(() => null);
  check(!!closedByX, '★ D3f 点 #changelog-close → 面板收起（关闭入口真的接上了）',
    closedByX ? closedByX.openOverlays : '超时仍开着');

  // ---------- D6：浮层互斥，两个方向 ----------
  // 前置：把"看过"设成最新 → 900ms 那个自动提示不会掺进来（D6/D7 要的是干净的起点）
  await setSeen(latest);
  await goto(APP);
  await ev('(function(){ if (typeof closeOverlaysExcept === "function") closeOverlaysExcept(null); return true; })()');
  const d6pre = await ev(PROBE);
  check(!d6pre.modal.visible && d6pre.dot.display === 'none',
    '★ D6pre 起点干净：seen=latest，红点灭、面板关（后面两条互斥断言才有意义）',
    { modalVisible: d6pre.modal.visible, dotDisplay: d6pre.dot.display });

  await clickJs("document.getElementById('help-btn')");
  await sleep(300);
  const helpOpen = await ev(`(function(){ var h = document.getElementById('help-modal');
    return { visible: !!h && getComputedStyle(h).display !== 'none' }; })()`);
  await clickJs("document.getElementById('changelog-btn')");
  const forForward = await waitFor(async () => {
    const p = await ev(PROBE);
    const h = await ev(`(function(){ var m = document.getElementById('help-modal');
      return { visible: !!m && getComputedStyle(m).display !== 'none', hasHiddenClass: !!m && m.classList.contains('hidden') }; })()`);
    return (p.modal.visible && !h.visible) ? { p: p, help: h } : null;
  }, 6000, '公告压住帮助（帮助被加 hidden）').catch(async () => ({
    p: await ev(PROBE),
    help: await ev(`(function(){ var m = document.getElementById('help-modal');
      return { visible: !!m && getComputedStyle(m).display !== 'none', hasHiddenClass: !!m && m.classList.contains('hidden') }; })()`)
  }));
  check(helpOpen.visible, '★ D6a 前置：点 #help-btn 帮助面板真的开了', helpOpen);
  check(forForward.p.modal.visible && !forForward.help.visible && forForward.help.hasHiddenClass,
    '★ D6b 先开帮助再点公告 → #help-modal 被加 hidden、#changelog-modal 可见（浮层互斥，方向一）',
    { help: forForward.help, changelogVisible: forForward.p.modal.visible });

  // 反向：先开公告，再点帮助 → 公告应被帮助的入口收起（help 的入口自己不调互斥，
  // 所以这一条**大概率**是红的 —— 见交付里的产品缺陷报告，工具只管如实钉住）
  await clickJs("document.getElementById('changelog-btn')");
  await waitFor(async () => (await ev(PROBE)).modal.visible, 5000, '公告面板打开（反向那一条的前置）').catch(() => null);
  await clickJs("document.getElementById('help-btn')");
  await sleep(600);
  // ⚠️ 这条断言**只钉事实**，不替产品做决定：公告与帮助都是 `.modal-overlay`、
  //    z-index 一样（10000，见 style.css），DOM 里帮助在后 → **帮助压在公告上面**。
  //    点帮助的入口不收起公告时，公告虽然"还开着"，但玩家看到的是一层帮助盖着一层公告，
  //    谁也读不了、点不动 —— 所以这里额外量一次"公告中心点上最顶层的元素是谁"，
  //    把症状钉成可复现的证据（否则只有一句"类名没变"，容易被当成口味问题）。
  const reverse = await ev(`(function(){
    var c = document.getElementById('changelog-modal');
    var h = document.getElementById('help-modal');
    function v(el){ return !!el && getComputedStyle(el).display !== 'none'; }
    var cr = c ? c.getBoundingClientRect() : null;
    var topAtChangelogCenter = null;
    if (cr && cr.width > 0) {
      var hit = document.elementFromPoint(Math.round(cr.left + cr.width / 2), Math.round(cr.top + cr.height / 2));
      topAtChangelogCenter = hit ? (hit.id || hit.className || hit.tagName) : null;
    }
    return {
      changelog: v(c), changelogHiddenClass: !!c && c.classList.contains('hidden'), help: v(h),
      openOverlays: [].slice.call(document.querySelectorAll('.modal-overlay:not(.hidden)')).map(function(el){ return el.id; }),
      zChangelog: c ? getComputedStyle(c).zIndex : null,
      zHelp: h ? getComputedStyle(h).zIndex : null,
      topAtChangelogCenter: topAtChangelogCenter
    };
  })()`);
  check(reverse.help && !reverse.changelog,
    '★ D6c 先开公告再点帮助 → 公告收起、帮助可见（浮层互斥，方向二）', reverse);

  // ---------- D5：游客不自动弹，但入口照常、红点应当亮 ----------
  await clickJs("document.getElementById('changelog-close')").catch(() => {});
  await send('Network.clearBrowserCookies').catch(() => {});
  await goto(APP);
  const cleared = await clearLocalState();
  check(cleared.seen === null && cleared.error === undefined,
    '★ D5a 游客侧 localStorage 的"看过"记录清掉了', cleared);
  // 手动叫一次那个自动提示函数（它是模块级函数，页面里取得到）。
  // ⚠️ 这里不是"换个方式验"，而是唯一能**确定性**验"游客不弹"的办法：
  //    setTimeout(…,900) 是异步的，直接取样会和它抢跑（见文件头「坑 5」）。
  const guestAnnounce = await ev(`(function(){
    if (typeof window.maybeAnnounceChangelog !== 'function') return { called: false };
    window.maybeAnnounceChangelog();
    return { called: true };
  })()`);
  check(guestAnnounce.called, '★ D5b 页面里取得到 maybeAnnounceChangelog（模块级函数，没被包进闭包）', guestAnnounce);
  // 等它把接口拉回来、把红点亮起来（红点亮 = 这次决定已经做完了）
  const dotOn = await waitFor(async () => {
    const p = await ev(PROBE);
    return p.dot.visible ? p : null;
  }, 12000, '游客的红点亮起来（= 自动提示这次决定已做完）').catch(async () => await ev(PROBE));
  check(dotOn.dot.visible, '★ D5c 游客也能看到红点：有没看过的更新时 #changelog-dot 亮着（不是只给登录用户亮）',
    { display: dotOn.dot.display, hasHiddenClass: dotOn.dot.hasHiddenClass });
  await sleep(1200);   // 再等一会儿：自动弹要是会发生，这段时间足够发生
  const guestAfter = await ev(PROBE);
  check(!guestAfter.modal.visible && guestAfter.openOverlays.length === 0,
    '★ D5d 游客**不自动弹**（等足自动提示的时间窗后，面板仍关着、没有任何浮层被打开）',
    { modalVisible: guestAfter.modal.visible, openOverlays: guestAfter.openOverlays });

  // 但入口照常：点开就是全部条目
  await clickJs("document.getElementById('changelog-btn')");
  const guestPanel = await waitFor(async () => {
    const p = await ev(PROBE);
    return p.modal.visible && p.entryCount === entries.length ? p : null;
  }, 8000, '游客手点入口后渲染出全部条目').catch(async () => await ev(PROBE));
  check(guestPanel.modal.visible && guestPanel.entryCount === entries.length
    && JSON.stringify(guestPanel.items) === JSON.stringify(entries.map((e) => e.items.map(String))),
    '★ D5e 游客手点入口 → 面板照常显示**全部**条目且内容与接口一致（"不自动弹"不等于"看不到"）',
    { visible: guestPanel.modal.visible, dom: guestPanel.entryCount, api: entries.length });

  // ---------- D7：有别的浮层开着时不抢屏 ----------
  await clickJs("document.getElementById('changelog-close')");
  await setSeen(latest);
  await goto(APP);
  await clickJs("document.getElementById('help-btn')");
  await sleep(300);
  await ev('(function(){ try { localStorage.removeItem(' + JSON.stringify(SEEN_KEY) + '); } catch(e){} return true; })()');
  const d7dot = await waitFor(async () => {
    const p = await ev(PROBE);
    return p.dot.visible ? p : null;
  }, 12000, 'D7 前置：红点亮起来（说明"有没看过的更新"这个判断已做完）').catch(() => null);
  // 自动提示这次决定（此时帮助开着）—— 手叫一次，避免与 900ms 那个 timer 抢跑
  await ev('(function(){ if (typeof window.maybeAnnounceChangelog === "function") window.maybeAnnounceChangelog(); return true; })()');
  await sleep(1500);
  const d7 = await ev(`(function(){
    var h = document.getElementById('help-modal'), c = document.getElementById('changelog-modal');
    function v(el){ return !!el && getComputedStyle(el).display !== 'none'; }
    var dot = document.getElementById('changelog-dot');
    return { help: v(h), changelog: v(c),
             dot: !!dot && getComputedStyle(dot).display !== 'none' }; })()`);
  check(!!d7dot, '★ D7a 前置：红点亮着（清掉"看过"后确实有没看过的更新）', d7dot ? d7dot.dot.display : '红点没亮');
  check(d7.help && !d7.changelog,
    '★ D7b 帮助开着时自动提示**不抢屏**：帮助仍然开着、公告没弹（公告绝不挡路）', d7);
  check(d7.dot, '★ D7c 这种情况下红点留着（"不弹"不等于"当没这回事"）', { dot: d7.dot });

  // ---------- D8：窄屏 390x844 ----------
  await clickJs("document.getElementById('help-modal-close')").catch(() => {});
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
  await sleep(400);
  await clickJs("document.getElementById('changelog-btn')");
  await waitFor(async () => (await ev(PROBE)).entryCount === entries.length, 8000, '窄屏下面板渲染完成').catch(() => null);
  const narrow = await ev(BOXES);
  check(narrow.docScrollW <= narrow.vw + 1 && narrow.bodyScrollW <= narrow.vw + 1,
    '★ D8a 390x844 下文档不横向溢出（scrollWidth <= clientWidth）',
    { vw: narrow.vw, docScrollW: narrow.docScrollW, bodyScrollW: narrow.bodyScrollW });
  const modalOverflow = narrow.modal ? narrow.modal.scrollW - narrow.modal.clientW : 0;
  check(narrow.modal && modalOverflow <= 1,
    '★ D8b 公告面板自己不横向溢出（面板是 fixed 全屏遮罩，溢出会顶出横向滚动条）',
    { modal: narrow.modal, overflow: modalOverflow });
  check(narrow.overs === 0 && narrow.entries.every((b) => b && b.right <= narrow.vw + 1),
    '★ D8c 条目文字不伸出视口（每一条 .changelog-entry 的右边缘都在视口内）',
    { overs: narrow.overs, entries: narrow.entries.slice(0, 3) });
  await send('Emulation.clearDeviceMetricsOverride');
  await sleep(300);

  // ---------- D4：自动提示（已登录） ----------
  const cookieU = await nodeAuth(U);
  check(!!cookieU, '★ D0b 浏览器侧账号 U 已就绪（先 register 后 login；cookie 已拿 /api/profile 反查过 username）',
    cookieU ? cookieU.split('=')[0] + '=…' : '（多半是 /register 或 /login 的 IP 限流：60 秒 10 次，等一分钟再跑）');
  if (!cookieU) throw new Error('账号没登进去，D4 那三条没法验（这是环境/限流问题，不是产品的错）');

  await send('Network.clearBrowserCookies').catch(() => {});
  await setCookie(cookieU);
  await goto(APP);
  const meU = await ev('window.__USERNAME || null');
  check(meU === U, '★ D0c 浏览器页面认得当前登录用户是 U（__USERNAME 有值 = maybeAnnounceChangelog 的第一个门禁过了）', meU);

  // 解析"看过"键名（见文件头「坑 1」）：先清干净，再让自动提示写一次
  await clearLocalState();
  await ev('(function(){ try { localStorage.removeItem(' + JSON.stringify(SEEN_KEY_DEFAULT) + '); } catch(e){} return true; })()');
  await goto(APP);                                    // 刷新：清掉页面内存里的 changelogPayload 缓存
  const preD4 = await ev(PROBE);
  check(preD4.dot.display === 'none' && !preD4.modal.visible,
    '★ D4pre 刷新后**这一瞬间**还没弹（那个 900ms 的自动提示是异步的；顺带钉住"红点此刻也没亮"）',
    { dot: preD4.dot.display, modal: preD4.modal.visible });

  const seenKey = await resolveSeenKey(latest).catch(() => null)
    || await waitFor(async () => {
      const p = await ev(PROBE);
      if (!p.modal.visible) return null;
      return await resolveSeenKey(latest);
    }, 8000, '面板弹出来并写回 seen').catch(() => null);
  check(!!seenKey, '★ D4a0 找到"看过"记录用的 localStorage 键（值是接口的 latest）——找不到说明工具需要更新键名，不是产品的错',
    { resolved: seenKey, default: SEEN_KEY_DEFAULT });
  if (seenKey) SEEN_KEY = seenKey;

  const auto1 = await waitFor(async () => {
    const p = await ev(PROBE);
    return p.modal.visible ? p : null;
  }, 8000, '刷新后自动弹出公告面板').catch(async () => await ev(PROBE));
  check(auto1.modal.visible, '★ D4a 已登录 + 没有"看过"记录 → 刷新后**自动弹** #changelog-modal',
    { visible: auto1.modal.visible, openOverlays: auto1.openOverlays });
  const wroteSeen = await ev(`(function(){ try { return localStorage.getItem(${JSON.stringify(SEEN_KEY)}); } catch(e){ return null; } })()`);
  check(wroteSeen === latest, '★ D4b 打开面板就把 latest 写进 localStorage（"已看过"记的是接口给的时间原文）',
    { stored: wroteSeen, latest: latest });
  check(auto1.entryCount === entries.length, '★ D4c 自动弹出的面板里也是全部条目（不是只有时间）',
    { dom: auto1.entryCount, api: entries.length });
  check(auto1.dot.display === 'none', '★ D4d 打开后红点灭（看过就不该再提示）', { display: auto1.dot.display });

  // 再刷新一次：不该再弹（这条是关键 —— 证明"看过就不烦人"）
  await goto(APP);
  await waitFor(async () => !(await ev(PROBE)).dot.visible, 8000, '第二次刷新后红点保持灭').catch(() => null);
  await ev('(function(){ if (typeof window.maybeAnnounceChangelog === "function") window.maybeAnnounceChangelog(); return true; })()');
  await sleep(2000);
  const auto2 = await ev(PROBE);
  check(!auto2.modal.visible && auto2.openOverlays.length === 0,
    '★ D4e 关掉后再刷新（seen == latest）→ **不再自动弹**（"看过就不烦人"）',
    { modalVisible: auto2.modal.visible, openOverlays: auto2.openOverlays });

  // 把 seen 改成一个旧值：应当又弹（证明"每次新更新都会显示这一次的时间和内容"）
  const oldSeen = '2000-01-01 00:00';
  const setOld = await setSeen(oldSeen);
  check(setOld === oldSeen, '★ D4f 前置：把"看过"改成一个旧值 ' + oldSeen, { stored: setOld });
  await goto(APP);
  const auto3 = await waitFor(async () => {
    const p = await ev(PROBE);
    return p.modal.visible ? p : null;
  }, 8000, '旧 seen 值下刷新后再次自动弹').catch(async () => await ev(PROBE));
  check(auto3.modal.visible, '★ D4g seen 是旧值（有更新）→ 再次自动弹（每次新更新都提示一次）',
    { visible: auto3.modal.visible });
  const wroteSeen3 = await ev(`(function(){ try { return localStorage.getItem(${JSON.stringify(SEEN_KEY)}); } catch(e){ return null; } })()`);
  check(wroteSeen3 === latest, '★ D4h 这次弹出后 seen 被更新成新的 latest（不会下次还弹）',
    { stored: wroteSeen3, latest: latest });

  // ---------- D4x：正在一局里就不打扰（也许是产品代码里那条最容易"看着有、永远不触发"的门禁） ----------
  // `maybeAnnounceChangelog` 有三个门禁：已登录 / 没有进行中的对局 / 有没看过的更新。
  // 第三条已经被 D4e/D4g 从两侧钉死了（等于 latest 不弹、不等于 latest 弹），
  // 但**第二条没有任何别的用例覆盖** —— 而它的失败形状是玩家打到一半被弹窗盖住棋盘。
  // ⚠️ 对局键的名字**从源码里取**（`const ACTIVE_GAME_KEY = '…'`），不在这里再抄一份：
  //    产品换名字时工具要么自己跟上、要么明确报"取不到"，而不是拿一个过期键名假装验过了。
  const activeKeyInSrc = (() => {
    try {
      const src = fs.readFileSync(path.join(ROOT, 'static', 'game.js'), 'utf8');
      const m = src.match(/const\s+ACTIVE_GAME_KEY\s*=\s*'([^']+)'/);
      return m ? m[1] : null;
    } catch (e) { return null; }
  })();
  const ACTIVE_KEY = activeKeyInSrc || ACTIVE_GAME_KEY;
  check(!!activeKeyInSrc, '★ D4x0 从 static/game.js 里取到了"进行中的对局"那个 localStorage 键名（不手抄）',
    { src: activeKeyInSrc, used: ACTIVE_KEY });
  await goto(APP);
  await ev(`(function(){ try {
    localStorage.removeItem(${JSON.stringify(SEEN_KEY)});
    localStorage.setItem(${JSON.stringify(ACTIVE_KEY)}, '{"room":"CHK"}');
    return true; } catch(e){ return false; } })()`);
  await ev('(function(){ if (typeof window.maybeAnnounceChangelog === "function") window.maybeAnnounceChangelog(); return true; })()');
  await sleep(2000);
  const inGame = await ev(PROBE);
  check(!inGame.modal.visible,
    '★ D4x 本地记着"正在进行的一局"时不自动弹（别在对局中途盖住棋盘；入口照旧可点）',
    { modalVisible: inGame.modal.visible, dot: inGame.dot.display });
  await ev(`(function(){ try { localStorage.removeItem(${JSON.stringify(ACTIVE_KEY)}); } catch(e){} return true; })()`);

  // ---------- D9：接口 500 时页面静默 ----------
  // 用 CDP 的 Fetch 域把 /api/changelog **在请求阶段**答成 500（页面一个字节都出不去）。
  const problemsBefore500 = appProblems.length + consoleErrors.length;
  let pausedChangelog = 0;
  eventHook = async (m) => {
    if (m.method === 'Fetch.requestPaused') {
      const p = m.params || {};
      if (String(p.request && p.request.url || '').indexOf('/api/changelog') >= 0) {
        pausedChangelog++;
        await send('Fetch.fulfillRequest', { requestId: p.requestId, responseCode: 500, responsePhrase: 'Internal Server Error' });
      } else {
        await send('Fetch.continueRequest', { requestId: p.requestId });   // 别的请求照常放行
      }
      return;
    }
    collectEvent(m);
  };
  await setSeen(latest);                                  // 保持"看过"=latest，让自动提示这一轮不去点开面板
  await send('Fetch.enable', { patterns: [{ urlPattern: '*/api/changelog*', requestStage: 'Request' }] });
  await goto(APP);                                        // 刷新：页面内存缓存清零，一定会真打这个接口
  const err500 = await waitFor(async () => {
    const p = await ev(PROBE);
    return p.dot.visible ? p : null;                      // 红点亮 = 这次判断做完（拿到了 null）
  }, 12000, '拿到失败的响应后这次判断做完').catch(async () => await ev(PROBE));
  await sleep(800);
  const after500 = await ev(PROBE);
  check(pausedChangelog > 0, '★ D9a CDP 真的拦到了 /api/changelog 并答了 500（拦不到这条就没验到东西）',
    { paused: pausedChangelog });
  check(!after500.modal.visible && after500.openOverlays.length === 0,
    '★ D9b 接口 500 时**不弹错误、不弹空面板**（公告是锦上添花，拉不到就什么都别做）',
    { modalVisible: after500.modal.visible, openOverlays: after500.openOverlays, err500: err500.dot ? err500.dot.display : null });

  await clickJs("document.getElementById('changelog-btn')");
  const click500 = await waitFor(async () => {
    const p = await ev(PROBE);
    return p.modal.visible ? p : null;
  }, 5000, '接口 500 时入口仍能点开').catch(async () => await ev(PROBE));
  check(click500.modal.visible, '★ D9c 接口 500 时入口**照样点得开**（面板空着，而不是点了没反应）',
    { visible: click500.modal.visible, entries: click500.entryCount });
  check(click500.entryCount === 0, '★ D9d 拉不到内容时面板是空的（没有假造/上一帧残留的内容）',
    { entries: click500.entryCount });
  await sleep(500);
  const problemsAfter500 = appProblems.length + consoleErrors.length;
  check(problemsAfter500 === problemsBefore500,
    '★ D9e 接口 500 全程**零 JS 异常、零应用级 console.error**（浏览器网络层那条不计 —— 见文件头「坑 7」）',
    { before: problemsBefore500, after: problemsAfter500, new: appProblems.slice(-3).concat(consoleErrors.slice(-3)) });
  await send('Fetch.disable').catch(() => {});
  eventHook = null;

  // 收尾：把 500 造成的空面板关掉，再确认一切恢复
  await clickJs("document.getElementById('changelog-close')").catch(() => {});
  await sleep(300);

  // ---------- D9f：全程零异常 ----------
  check(appProblems.length === 0, '★ D9f 全程零 JS 异常（window.onerror / 未捕获 promise 都算）',
    appProblems.slice(0, 8));
  check(consoleErrors.length === 0, '★ D9g 全程零应用级 console.error（浏览器自报的网络失败不算）',
    { consoleErrors: consoleErrors.slice(0, 5), browserNetworkNoise: browserNoise.slice(0, 5) });

  if (SHOT) {
    try {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
      console.log('   截图已存 ' + SHOT);
    } catch (e) { console.log('   截图失败: ' + e.message); }
  }
}

// ---------- 收尾 ----------
function killProfileProcesses() {
  // ⚠️ proc.kill() 杀不干净孙进程（本工具假红第一大来源），收尾也按 profile 路径清一遍
  try {
    spawnSync('powershell', ['-NoProfile', '-Command',
      'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
      'Where-Object { $_.CommandLine -like \'*changelog_check_profile*\' } | ' +
      'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'],
      { stdio: 'ignore', timeout: 25000 });
  } catch (e) { /* 已经全退了 */ }
}
async function cleanup() {
  try { ws && ws.close(); } catch (e) { /* 已关 */ }
  try { browser && !browser.killed && browser.kill(); } catch (e) { /* 已退 */ }
  await sleep(300);
  killProfileProcesses();
}

main().catch((err) => {
  console.error('工具自身异常：' + ((err && err.stack) || err));
  failures.push('工具自身异常: ' + (err && err.message));
}).then(async () => {
  await cleanup();
  const total = passes.length + failures.length;
  console.log('');
  console.log('==================== 结果 ====================');
  console.log('通过 ' + passes.length + ' / 失败 ' + failures.length + '（断言总数 ' + total + '）');
  if (failures.length) {
    console.log('失败项：');
    failures.forEach((f) => console.log('   · ' + f));
    process.exit(1);
  }
  console.log('✓ 更新公告 UI 检查通过');
  process.exit(0);
});
