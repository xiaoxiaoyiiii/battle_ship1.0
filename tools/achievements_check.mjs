#!/usr/bin/env node
/**
 * 徽章墙 / 成就系统 回归检查（无头 Edge + CDP）—— 第 2 批 C 票
 *
 * 依据：`docs/BATCH_2_3_4_PLAN.md` §2.3（12 枚徽章与判据）/ §2.4（接口）/ §2.5（前端），
 * 以及第 1 批的 DOM 契约（`docs/PROFILE_CARD_2026_09_17_PLAN.md` §3.1：查看面渲染进
 * `#opponent-stats-content`，`#profile-view-*` 这套 id **只在查看面**输出）。
 *
 * ## 这个工具在测什么（以及为什么这么测）
 *
 * 徽章的数据来源有**两条**，而且它们故意不一样：
 *   · `GET /api/profile`  → 全量 12 枚（含未解锁），**只有自己**能拿
 *   · `GET /user_stats`   → **只下发已解锁的**（别人视角不该看到你的进度）
 * 而查看面（点头像/排行榜名字打开的那张名片）取数走的是 `/user_stats`。
 * 所以「自己看自己时能看到灰掉的未解锁位」这条，靠的是前端**额外拿一份 `/api/profile`**
 * —— 这个工具的核心断言就是钉死这件事：桩数据里 `/user_stats` 只给 3 枚已解锁，
 * 而自己视角必须渲染出 12 枚（其中 9 枚 `.locked`）。
 *
 * ## 桩与真实的分工（两种模式）
 *
 * · **真实**（两种模式都有）：注册/登录一次性账号 —— 保证 `window.__USERNAME`、
 *   `profileIsSelf()` 这些"我是谁"的判断走的是真链路，否则自己/别人的分支根本进不去。
 * · **桩模式（默认）**：只**包一层** `fetch` 往两个接口的响应里**注入 achievements 字段**
 *   （真实响应其余部分原样保留）—— 让「别人已解锁 2 枚」「一枚都没解锁」这些态可确定性复现，
 *   否则断言会依赖本机库里恰好有多少战绩。
 * · **真链路模式（`--no-stub`）**：一个桩都不打，断言改成「**渲染 == 接口说的**」：
 *   自己视角必须等于 `/api/profile` 的全量目录与解锁数，别人视角必须等于 `/user_stats`
 *   下发的那几枚、且**一枚 `.locked` 都不能有**。两种模式共用同一套断言，只是期望值
 *   由接口现算，所以前端一旦把两条数据源接错（比如拿自己那份去补别人），两种模式都会红。
 *
 * 用法：
 *   node tools/achievements_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 *   node tools/achievements_check.mjs --url http://127.0.0.1:5055/ --no-stub [--other <用户名>]
 *
 * ⚠️ 真链路模式要求服务端已经跑着 B 票的新 `api.py`。`python server.py` **不会**自动重载 ——
 * 在改代码之前起的那个进程上跑真链路，会看到「接口里根本没这个字段」（`badge_count: null`），
 * 那不是前端的问题，换一个刚起的服务端再跑。
 *
 * ⚠️ 会在目标服务端注册一次性账号（`badgecheck*`），**不要指向生产**。
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const NO_STUB = argv.indexOf('--no-stub') >= 0;
const OTHER_ARG = argOf('--other', '');
const PORT = 9361;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(HERE, '..', '.tmp', 'achievements_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过徽章检查'); process.exit(0); }

// 预清理：上一次没退干净的无头 Edge 会占着调试端口 + 锁住 profile 目录 →
// 新浏览器**静默起不来**，工具连上的是旧实例，症状是「等待超时：页面加载」这种
// 查不出所以然的假红（第 1 批踩过，见 CLAUDE.md §11 名片改版批的工具假红清单）。
try {
  execSync('powershell -NoProfile -Command "' +
    'Get-CimInstance Win32_Process -Filter \\"Name=\'msedge.exe\'\\" | ' +
    'Where-Object { $_.CommandLine -like \'*achievements_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没有残留就够了 */ }

const SUFFIX = String(Date.now()).slice(-6);
const ME = 'badgecheck' + SUFFIX;
const PW = 'check123456';
// 别人视角看的账号：
//   桩模式 → 固定 'bravo_u'（桩数据里已解锁 2 枚，断言可确定）
//   真链路 → 用 --other 指定的真实账号；没指定就自己再注册一个（新号，0 枚解锁）
const OTHER = NO_STUB
  ? (OTHER_ARG || ('badgeother' + SUFFIX))
  : 'bravo_u';
const REGISTER_OTHER = NO_STUB && !OTHER_ARG;
const ZERO = 'zero_guy';        // 一枚都没解锁（achievements 是空数组）
const NODATA = 'nodata_guy';    // 接口干脆没给 achievements 字段

// 12 枚徽章（与 achievements.py 的 BADGES 逐字段一致；桩数据要像真的一样，
// 否则「title 里有解锁条件」这类断言会变成自证）
const BADGES = [
  { id: 'first_win', name: '首胜', desc: '第一场胜利，海图上从此有了你的航迹', requirement: '赢下 1 场', group: '里程碑' },
  { id: 'veteran10', name: '十场老兵', desc: '甲板上磨出的茧，是十场风浪给的', requirement: '累计对局 10 场', group: '里程碑' },
  { id: 'streak5', name: '五连胜', desc: '连赢五场，对手开始记住你的名字', requirement: '最高连胜 ≥ 5', group: '连胜' },
  { id: 'streak10', name: '十连胜', desc: '十场不败，这条航迹不用解释', requirement: '最高连胜 ≥ 10', group: '连胜' },
  { id: 'sunk50', name: '五十沉', desc: '五十艘沉在你的炮口下', requirement: '累计击沉 ≥ 50', group: '击沉' },
  { id: 'sunk200', name: '两百沉', desc: '两百年沉船，海沟都认得你', requirement: '累计击沉 ≥ 200', group: '击沉' },
  { id: 'flawless', name: '零伤获胜', desc: '一艘没损失，就结束了这一局', requirement: '零伤赢下 1 场', group: '完美' },
  { id: 'flawless5', name: '完美指挥', desc: '五次全身而退，靠的不是运气', requirement: '零伤赢下 5 场', group: '完美' },
  { id: 'speedrun', name: '闪电战', desc: '三分钟内解决战斗', requirement: '最快获胜 ≤ 3 分钟', group: '完美' },
  { id: 'cardmaster', name: '卡牌大师', desc: '手里有整本卡牌的账', requirement: '累计出牌 ≥ 100', group: '卡牌' },
  { id: 'allrounder', name: '全能选手', desc: '二十种牌路，样样都走过', requirement: '用过 ≥ 20 张不同的卡', group: '卡牌' },
  { id: 'rank1', name: '榜首', desc: '第 1 名，只有一个人能站的位置', requirement: '排行榜第 1 名', group: '榜单' }
];
// 自己：已解锁 3 枚（其余 9 枚应当以 .locked 出现）
const SELF_UNLOCKED = ['first_win', 'streak5', 'speedrun'];
// 别人：只有 2 枚已解锁，且**接口不下发未解锁的**
const OTHER_UNLOCKED = ['first_win', 'sunk50'];

const catalogFor = (ids) => BADGES.map((b, i) => ({
  ...b,
  unlocked: ids.indexOf(b.id) >= 0,
  unlocked_at: ids.indexOf(b.id) >= 0 ? (1789000000 + i * 1000) : 0
}));

const SELF_ACH = catalogFor(SELF_UNLOCKED);          // /api/profile 下发：全量 12
const SELF_UNLOCKED_ONLY = catalogFor(SELF_UNLOCKED).filter((b) => b.unlocked);   // /user_stats 下发：只有已解锁
const OTHER_ACH = catalogFor(OTHER_UNLOCKED).filter((b) => b.unlocked);
// 新号的样子：12 枚全未解锁（`?badgezero=1` 时用）。钉死「0 枚解锁也要显示一整墙灰位」。
const ALL_LOCKED = catalogFor([]);

const STUB = `
(function () {
  window.__stubHits = { apiProfile: 0, userStats: 0 };
  var orig = window.fetch;
  var ALL_LOCKED = ${JSON.stringify(ALL_LOCKED)};
  var SELF_ACH = ${JSON.stringify(SELF_ACH)};
  var SELF_ONLY = ${JSON.stringify(SELF_UNLOCKED_ONLY)};
  var OTHER_ACH = ${JSON.stringify(OTHER_ACH)};
  // ?badgezero=1 → 自己视角 12 枚全未解锁（新号）。徽章目录在 init 时就缓存了，
  // 想验"0 枚解锁"这一态必须**换一次文档**（改缓存没用），所以走 URL 开关。
  var ZERO_MODE = String(location.search || '').indexOf('badgezero') >= 0;
  var SELF_ACH_EFF = ZERO_MODE ? ALL_LOCKED : SELF_ACH;
  var SELF_ONLY_EFF = ZERO_MODE ? [] : SELF_ONLY;
  var mk = function (obj) {
    return Promise.resolve({ ok: true, status: 200,
      json: function () { return Promise.resolve(obj); },
      text: function () { return Promise.resolve(JSON.stringify(obj)); } });
  };
  // 真实响应 → 补上 achievements 字段（其余原样保留，这样"我是谁"仍走真链路）
  var patch = function (p, patchFn) {
    return p.then(function (r) {
      if (!r || !r.ok) return r;
      return r.json().then(function (d) { patchFn(d); return mk(d); });
    });
  };
  window.fetch = function (url, opts) {
    var u = String(url);
    // /api/profile/card 与 /api/profile/avatar 要原样放行（前缀会被 /api/profile 吃掉）
    if (u.indexOf('/api/profile/card') === 0 || u.indexOf('/api/profile/avatar') === 0
        || u.indexOf('/api/profile/signature') === 0) {
      return orig.apply(this, arguments);
    }
    if (u.indexOf('/api/profile') === 0) {
      window.__stubHits.apiProfile += 1;
      return patch(orig.apply(this, arguments), function (d) {
        if (d && d.profile) {
          d.profile.achievements = SELF_ACH_EFF;                              // 全量 12（含未解锁）
          d.profile.badge_count = { unlocked: ZERO_MODE ? 0 : ${SELF_UNLOCKED.length}, total: ${BADGES.length} };
        }
      });
    }
    if (u.indexOf('/user_stats') === 0) {
      window.__stubHits.userStats += 1;
      if (u.indexOf(${JSON.stringify(OTHER)}) >= 0) {
        return mk({ stats: { id: 'u_other', username: ${JSON.stringify(OTHER)}, wins: 7, losses: 9,
          current_streak: 0, longest_streak: 3, signature: '今天也要赢一局',
          avatar: '/static/avatars/default.png', rank: 7, title_id: 'sailor', title_name: '老水手',
          tags: ['steady'], status_text: '免战中', frame_id: 'silver', card_bg_id: 'graphite',
          fav_cards: [], show_history: 0, show_stats: 1, show_fav_cards: 1,
          achievements: OTHER_ACH, badge_count: { unlocked: ${OTHER_UNLOCKED.length}, total: ${BADGES.length} } },
          history: [] });
      }
      if (u.indexOf(${JSON.stringify(ZERO)}) >= 0) {
        return mk({ stats: { id: 'u_zero', username: ${JSON.stringify(ZERO)}, wins: 0, losses: 3,
          longest_streak: 0, avatar: '/static/avatars/default.png', rank: 9,
          tags: [], fav_cards: [], show_history: 1, show_stats: 1, show_fav_cards: 1,
          achievements: [], badge_count: { unlocked: 0, total: ${BADGES.length} } }, history: [] });
      }
      if (u.indexOf(${JSON.stringify(NODATA)}) >= 0) {
        // 老接口 / 异常数据：连 achievements 字段都没有 —— 不该抛异常，也不该占位
        return mk({ stats: { id: 'u_nodata', username: ${JSON.stringify(NODATA)}, wins: 2, losses: 1,
          longest_streak: 1, avatar: '/static/avatars/default.png', rank: 5,
          tags: [], fav_cards: [], show_history: 1, show_stats: 1, show_fav_cards: 1 }, history: [] });
      }
      // 自己：按真实契约**只给已解锁的 3 枚** —— 前端必须自己补一份 /api/profile 才能看到灰位
      var me = window.__USERNAME || '';
      return mk({ stats: { id: 'u_me', username: me, wins: 12, losses: 4, current_streak: 3,
        longest_streak: 6, signature: '我来也', avatar: '/static/avatars/default.png', rank: 3,
        title_id: 'hunter', title_name: '深海猎手', tags: ['aggressive'], status_text: '找队友',
        frame_id: 'gold', card_bg_id: 'cyber', fav_cards: [], show_history: 1, show_stats: 1,
        show_fav_cards: 1, achievements: SELF_ONLY_EFF,
        badge_count: { unlocked: ZERO_MODE ? 0 : ${SELF_UNLOCKED.length}, total: ${BADGES.length} } }, history: [] });
    }
    return orig.apply(this, arguments);
  };
  return 'stubbed';
})()`;

// 一次性账号：先试登录，登录不上再注册（/register 会自动登录）
// ⚠️ 注册会**切换 session**，所以"注册别人"必须放在"自己"后面（否则会话变成别人，
//    profileIsSelf 全错、自己视角那条断言会假红）。
const authScript = (name) => `
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
const AUTH = authScript(ME);
const AUTH_OTHER = authScript(OTHER);

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

async function goto(url) {
  await send('Page.navigate', { url });
  // ⚠️ navigate 返回后 readyState 可能还属于**旧文档** → 断言会打在上一页上（假红）。
  // 必须等「地址真的变了」+「新文档加载完成」同时成立。
  const want = url.replace(/\/$/, '');
  await waitFor(async () => {
    const st = await ev('({ href: location.href.replace(/\\/$/, ""), ready: document.readyState })');
    return st && st.ready === 'complete' && st.href === want;
  }, 30000, '页面加载 ' + url);
  await sleep(500);
}

const MODAL = (id) => `(function(){ var m = document.getElementById(${JSON.stringify(id)}); return m ? !m.classList.contains('hidden') : 'missing'; })()`;

// 打开某个人的名片（走真实入口 showUserProfile），并等名片真的渲染完 ——
// ⚠️ 弹窗"可见"不等于"内容就绪"（先渲染「加载中…」再异步取数），线上/慢机器尤其明显。
async function openCard(username) {
  await ev(`(function(){ window.showUserProfile(${JSON.stringify(username)}); return true; })()`);
  await waitFor(async () => (await ev(MODAL('opponent-stats-modal'))) === true, 15000, '名片打开 (' + username + ')');
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'), 20000, '名片渲染完成 (' + username + ')');
}

// 徽章墙探针：只看查看面里的那一个容器
const BADGES_PROBE = `(function(){
  var c = document.getElementById('opponent-stats-content');
  var box = c ? c.querySelector('#profile-view-badges') : null;
  if (!box) return { exists: false };
  var all = [].slice.call(box.querySelectorAll('.badge'));
  var locked = all.filter(function (b) { return b.classList.contains('locked'); });
  var title = box.querySelector('.pf-block-title');
  return {
    exists: true,
    visible: box.offsetHeight > 0,
    total: all.length,
    locked: locked.length,
    unlocked: all.length - locked.length,
    ids: all.map(function (b) { return b.dataset.badge; }),
    lockedIds: locked.map(function (b) { return b.dataset.badge; }),
    lockedTitles: locked.map(function (b) { return b.getAttribute('title') || ''; }),
    lockedGlyphs: locked.map(function (b) { return (b.querySelector('.badge-glyph') || {}).textContent || ''; }),
    headingText: title ? title.textContent.replace(/\\s+/g, ' ').trim() : null,
    childCount: box.children.length,
    countText: (box.querySelector('.pf-badges-count') || {}).textContent || '',
    gridOverflow: (function () {
      var g = box.querySelector('.badge-grid');
      if (!g) return null;
      return g.scrollWidth - g.clientWidth;
    })()
  };
})()`;

try {
  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=1500,950', '--force-device-scale-factor=1',
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
  if (!NO_STUB) await send('Page.addScriptToEvaluateOnNewDocument', { source: STUB });
  await send('Emulation.setDeviceMetricsOverride', { width: 1500, height: 950, deviceScaleFactor: 1, mobile: false });

  // ---------- 0. 真实登录 + 期望值 ----------
  await goto(APP + 'register');
  const auth = await ev(AUTH);
  check(typeof auth === 'string' && /ok$/.test(auth), 'Z0 真实注册/登录一次性账号（"我是谁"的判断走真链路）', auth);
  if (REGISTER_OTHER) {
    // 注册"别人"会切换 session → 注册完必须再登录回自己
    await ev(AUTH_OTHER);
    const back = await ev(AUTH);
    check(/ok$/.test(back), 'Z0b 真链路模式：另注册了一个"别人"账号并切回自己', { other: OTHER, back: back });
  }
  await goto(APP);
  const me = await ev('window.__USERNAME');
  check(me === ME, 'Z1 页面认得当前登录用户', me);

  // 期望值**从接口现算**（两种模式共用）——断言因此变成
  // 「渲染出来的 == 接口说的」，而不是「等于我写死的 3/12」。
  const selfApi = await ev(`(async function(){
    var r = await fetch('/api/profile'); var d = await r.json();
    var p = (d && d.profile) || {}; var items = p.achievements || []; var cnt = p.badge_count || {};
    return { items: items.length, unlocked: Number(cnt.unlocked) || items.filter(function (a) { return a.unlocked; }).length,
      total: Number(cnt.total) || items.length,
      unlockedIds: items.filter(function (a) { return a.unlocked; }).map(function (a) { return a.id; }),
      lockedIds: items.filter(function (a) { return !a.unlocked; }).map(function (a) { return a.id; }) }; })()`);
  if (NO_STUB) {
    check(selfApi && selfApi.items > 0,
      'Z2 真链路：/api/profile 下发了徽章目录（服务端得跑着 B 票的新 api.py，老进程没有这个字段）', selfApi);
  } else {
    const stubHits = await ev('window.__stubHits');
    check(stubHits && stubHits.apiProfile > 0 && selfApi && selfApi.items === BADGES.length,
      'Z2 桩已生效：/api/profile 下发全量 12 枚（含未解锁）', { selfApi: selfApi, hits: stubHits });
  }
  // 等 init 里的 loadSelfIdentity 把这份目录缓存下来（它决定"看自己能不能看到灰位"）
  await sleep(600);

  // ---------- 1. 自己看自己：全量 12 枚，未解锁的灰掉 ----------
  await ev('(function(){ document.getElementById("show-profile").click(); return true; })()');
  await waitFor(async () => (await ev(MODAL('opponent-stats-modal'))) === true, 15000, '自己名片打开');
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'), 20000, '自己名片渲染完成');
  const self = await ev(BADGES_PROBE);
  check(self && self.exists === true, 'B1 查看面渲染出 #profile-view-badges', self && self.exists);
  check(self && self.visible === true, 'B2 有徽章项时徽章墙可见', self && self.visible);
  // ★ 核心：/user_stats 只给已解锁的（桩里 3 枚 / 真链路里新号 0 枚），能渲染出**全量目录**
  //   就证明前端确实补拿了 /api/profile —— 这条在两种模式下都由"接口说了几枚"现算。
  check(self && self.total === selfApi.items,
    '★ B3 自己视角渲染出的枚数 == /api/profile 的全量目录', self && { rendered: self.total, api: selfApi.items });
  check(self && self.unlocked === selfApi.unlocked,
    '★ B4 已解锁数与接口一致', self && { rendered: self.unlocked, api: selfApi.unlocked, ids: self.ids });
  check(self && self.locked === selfApi.items - selfApi.unlocked,
    '★ B5 其余全部带 .locked（灰掉的未解锁位）', self && { locked: self.locked, expect: selfApi.items - selfApi.unlocked, lockedIds: self.lockedIds });
  check(self && new RegExp('已解锁\\s*' + selfApi.unlocked + '\\s*/\\s*' + selfApi.total).test(self.countText || ''),
    'B6 标题写明「已解锁 N / 总数」', self && { text: self.countText, api: selfApi });
  check(self && (self.lockedTitles || []).every((t) => /未解锁/.test(t)),
    '★ B7 每枚未解锁徽章的 title 里都写了「未解锁」', self && (self.lockedTitles || []).slice(0, 2));
  const lockedTitles = self ? (self.lockedTitles || []) : [];
  check(lockedTitles.length === 0 || lockedTitles.every((t) => /：/.test(t)),
    '★ B8 title 里带解锁条件文案（形如「未解锁：累计击沉 ≥ 50」）', lockedTitles.slice(0, 2));
  check(self && (self.lockedGlyphs || []).every((g) => g === '?'),
    'B9 未解锁徽章用「?」占位（不是图标）', self && self.lockedGlyphs.slice(0, 3));
  const unlockedTitles = await ev(`(function(){
    var c = document.getElementById('opponent-stats-content');
    var box = c.querySelector('#profile-view-badges');
    var unl = [].slice.call(box.querySelectorAll('.badge')).filter(function (b) { return !b.classList.contains('locked'); });
    return unl.map(function (b) { return { id: b.dataset.badge, title: b.getAttribute('title') || '',
      group: b.dataset.group || '', glyph: (b.querySelector('.badge-glyph') || {}).textContent || '' }; }); })()`);
  check(Array.isArray(unlockedTitles) && unlockedTitles.length === selfApi.unlocked
    && unlockedTitles.every((b) => b.title && !/未解锁/.test(b.title)),
    'B10 已解锁徽章的 title 写名称/说明（没有「未解锁」字样）', unlockedTitles);
  check(Array.isArray(unlockedTitles) && unlockedTitles.every((b) => b.glyph && b.glyph !== '?'),
    'B11 已解锁徽章显示图标而不是「?」', unlockedTitles && unlockedTitles.map((b) => b.glyph));
  check(Array.isArray(unlockedTitles) && unlockedTitles.every((b) => b.group),
    'B12 每枚徽章带上 data-group（服务端给的中文分组）', unlockedTitles && unlockedTitles.map((b) => b.group));

  // ---------- 2. 看别人：只有已解锁的，且不泄露未解锁进度 ----------
  await ev('(function(){ var m=document.getElementById("opponent-stats-modal"); if(m) m.classList.add("hidden"); return true; })()');
  await sleep(200);
  // 别人视角的期望值同样**从接口现算**：/user_stats 只下发已解锁的，总数只在 badge_count 里
  const otherApi = await ev(`(async function(){
    var r = await fetch('/user_stats?username=' + encodeURIComponent(${JSON.stringify(OTHER)}));
    var d = await r.json(); var s = (d && d.stats) || {};
    var a = s.achievements || []; var cnt = s.badge_count || {};
    return { items: a.length, total: Number(cnt.total) || 0,
      ids: a.map(function (x) { return x.id; }),
      anyLocked: a.some(function (x) { return x.unlocked === false; }) }; })()`);
  await openCard(OTHER);
  const other = await ev(BADGES_PROBE);
  check(other && other.visible === (otherApi.items > 0),
    'B13 看别人时：他有已解锁徽章才显示这一块', other && { visible: other.visible, api: otherApi.items });
  check(other && other.total === otherApi.items,
    '★ B14 看别人只显示**接口下发的那几枚**（不多不少）', other && { total: other.total, api: otherApi.items, ids: other.ids });
  check(other && other.locked === 0 && otherApi.anyLocked === false,
    '★ B15 看别人时**没有**未解锁的灰位（接口也不下发未解锁的，不泄露别人的进度）', other && { locked: other.locked });
  check(other && (other.ids || []).every((id) => otherApi.ids.indexOf(id) >= 0),
    '★ B16 渲染出来的徽章 id 全部来自接口下发的集合', other && { rendered: other.ids, api: otherApi.ids });
  if (otherApi.total > 0) {
    // ★ 别人视角只下发已解锁的那几枚，总数来自 badge_count.total —— 前端要是拿
    // "下发了几枚"当总数，这里就会显示成「已解锁 2 / 2」（B 票 2026-09-17 专门提醒过）。
    check(other && new RegExp('已解锁\\s*' + otherApi.items + '\\s*/\\s*' + otherApi.total).test(other.countText || ''),
      '★ B16b 看别人时总数来自 badge_count.total（不是「N / N」）', other && { text: other.countText, api: otherApi });
  } else {
    console.log('SKIP  B16b 别人视角没给总数（badge_count 缺失），跳过 N / 总数 断言');
  }

  // ---------- 3. 零徽章 / 无数据 ----------
  // ⚠️ 这里要分清两种"零"：
  //   ① 有完整目录但**一枚都没解锁**（新号）→ **必须显示**一整墙灰位（B 票 2026-09-17
  //      的补充：整块隐藏只在"完全没有徽章项"时；否则新玩家根本不知道有徽章这回事）
  //   ② 接口**没有下发任何徽章项**（老接口 / 异常数据）→ 整块 hidden，且不留空标题
  // 真链路模式下 `?badgezero` 不起作用 —— 但刚注册的账号本来就是 0 枚解锁，
  // 所以两种模式验的是同一件事（期望值一样从接口现算）。
  await goto(APP + '?badgezero=1');
  await ev('(function(){ document.getElementById("show-profile").click(); return true; })()');
  await waitFor(async () => (await ev(MODAL('opponent-stats-modal'))) === true, 15000, '自己名片打开（0 枚解锁）');
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'), 20000, '名片渲染完成（0 枚解锁）');
  const zeroApi = await ev(`(async function(){
    var r = await fetch('/api/profile'); var d = await r.json();
    var p = (d && d.profile) || {}; var items = p.achievements || []; var cnt = p.badge_count || {};
    return { items: items.length, unlocked: Number(cnt.unlocked) || 0, total: Number(cnt.total) || items.length }; })()`);
  const zeroSelf = await ev(BADGES_PROBE);
  check(zeroApi && zeroApi.items > 0 && zeroApi.unlocked === 0,
    'B17a 前提：这个账号拿着完整目录、但一枚都没解锁', zeroApi);
  check(zeroSelf && zeroSelf.visible === true,
    '★ B17 自己 0 枚解锁时徽章墙**仍然显示**（新玩家要看得到收集目标）', zeroSelf && { visible: zeroSelf.visible, total: zeroSelf.total });
  check(zeroSelf && zeroSelf.total === zeroApi.items && zeroSelf.locked === zeroApi.items && zeroSelf.unlocked === 0,
    '★ B18 0 枚解锁时全部以 .locked 出现', zeroSelf && { total: zeroSelf.total, locked: zeroSelf.locked });
  check(zeroSelf && new RegExp('已解锁\\s*0\\s*/\\s*' + zeroApi.total).test(zeroSelf.countText || ''),
    'B19 标题写明「已解锁 0 / 总数」', zeroSelf && { text: zeroSelf.countText, api: zeroApi });
  await goto(APP);   // 回到正常页面

  // ② 接口**没有下发任何徽章项**（老接口 / 异常数据）→ 整块 hidden，且不留空标题。
  //    这两个账号只存在于桩模式（真链路上查不到它们的数据，名片本身就不是这张卡）。
  if (!NO_STUB) {
    await ev('(function(){ var m=document.getElementById("opponent-stats-modal"); if(m) m.classList.add("hidden"); return true; })()');
    await sleep(200);
    await openCard(ZERO);
    const zero = await ev(BADGES_PROBE);
    check(zero && zero.exists === true, '★ B20 接口没给任何徽章项时：#profile-view-badges 这个 id 仍然存在（契约要求）', zero && zero.exists);
    check(zero && zero.visible === false, '★ B21 接口没给任何徽章项时整块 hidden', zero && zero.visible);
    check(zero && zero.childCount === 0 && zero.headingText === null,
      '★ B22 hidden 时不留「空标题」（第 1 批空区块占位的教训）', zero && { childCount: zero.childCount, headingText: zero.headingText });

    await ev('(function(){ var m=document.getElementById("opponent-stats-modal"); if(m) m.classList.add("hidden"); return true; })()');
    await sleep(200);
    await openCard(NODATA);
    const nodata = await ev(BADGES_PROBE);
    check(nodata && nodata.exists === true && nodata.visible === false,
      '★ B23 接口连 achievements 字段都没有时：不抛异常、整块 hidden', nodata && { exists: nodata.exists, visible: nodata.visible });
  } else {
    console.log('SKIP  B20–B23「接口没给徽章项」这组只在桩模式下有意义（真链路上没有这两个账号）');
  }

  // ---------- 4. 撞 id 防护：非查看面不许输出这套 id ----------
  const lean = await ev(`(function(){
    var html = window.renderUserStatsHTML({ id: 'x', username: 'lean', wins: 1, losses: 0,
      achievements: ${JSON.stringify(SELF_ACH)} }, [], {});
    return { hasId: html.indexOf('id="profile-view-badges"') >= 0,
      hasClass: html.indexOf('pf-badges') >= 0,
      hasBadge: html.indexOf('class="badge') >= 0 }; })()`);
  check(lean && lean.hasClass === true && lean.hasBadge === true,
    'C1 非查看面仍然渲染徽章（只是不出 id）', lean);
  check(lean && lean.hasId === false,
    '★ C2 非查看面**不输出** id="profile-view-badges"（两个容器同 id 会让 getElementById 拿错）', lean && lean.hasId);

  // ---------- 5. 窄屏不横向溢出 ----------
  for (const w of [390, 336]) {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(300);
    await ev('(function(){ var m=document.getElementById("opponent-stats-modal"); if(m) m.classList.add("hidden"); return true; })()');
    await openCard(ME);
    const o = await ev(`(function(){
      var doc = document.scrollingElement;
      var c = document.getElementById('opponent-stats-content');
      var box = c.querySelector('#profile-view-badges');
      var grid = box ? box.querySelector('.badge-grid') : null;
      return { docOverflow: doc.scrollWidth - window.innerWidth,
        contentOverflow: c.scrollWidth - c.clientWidth,
        gridOverflow: grid ? (grid.scrollWidth - grid.clientWidth) : null,
        badges: box ? box.querySelectorAll('.badge').length : 0 }; })()`);
    check(o.docOverflow <= 1 && o.contentOverflow <= 1 && o.gridOverflow !== null && o.gridOverflow <= 1,
      `C3 ${w}px 宽徽章墙不横向溢出（文档 / 名片 / 网格三处都查）`, o);
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1500, height: 950, deviceScaleFactor: 1, mobile: false });
  await sleep(300);

  // ---------- 6. 反向自检：探针必须真的看得出「该有的东西没了」 ----------
  await ev('(function(){ var m=document.getElementById("opponent-stats-modal"); if(m) m.classList.add("hidden"); return true; })()');
  await openCard(ME);
  const neg = await ev(`(function(){
    var c = document.getElementById('opponent-stats-content');
    var box = c.querySelector('#profile-view-badges');
    if (!box) return { skip: 'no-box' };
    var beforeVisible = box.offsetHeight > 0;
    var beforeLocked = box.querySelectorAll('.badge.locked').length;
    box.classList.add('hidden');
    var hiddenSeen = box.offsetHeight === 0;
    box.classList.remove('hidden');
    var one = box.querySelector('.badge.locked');
    if (one) one.classList.remove('locked');
    var lockedNow = box.querySelectorAll('.badge.locked').length;
    if (one) one.classList.add('locked');
    return { beforeVisible: beforeVisible, hiddenSeen: hiddenSeen,
      beforeLocked: beforeLocked, lockedNow: lockedNow,
      restoredLocked: box.querySelectorAll('.badge.locked').length }; })()`);
  check(neg && neg.hiddenSeen === true, '★ N1 探针能看出徽章墙被隐藏（上面的可见性断言不是假绿）', neg);
  check(neg && neg.lockedNow === neg.beforeLocked - 1 && neg.restoredLocked === neg.beforeLocked,
    '★ N2 探针能数出 .locked 的变化（计数断言不是假绿）', neg && { before: neg.beforeLocked, after: neg.lockedNow, restored: neg.restoredLocked });

  if (SHOT) {
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(png.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }

  check(jsProblems.length === 0, 'Z9 全程无 JS 异常 / console.error', jsProblems.slice(0, 4));
} catch (err) {
  console.error('检查中断: ' + err.message);
  problems.push('中断: ' + err.message);
} finally {
  try { if (ws) ws.close(); } catch (e) { /* ignore */ }
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
}

console.log('');
if (problems.length) {
  console.log('✗ ' + problems.length + ' 项未通过: ' + problems.join(' | '));
} else {
  console.log('✓ 全部通过');
}
console.log('（注：本工具对 /api/profile 与 /user_stats 的 achievements 字段是**桩**的；'
  + 'B 票接口落地后需再跑一次真链路，见文件头注释。）');
process.exit(problems.length ? 1 : 0);
