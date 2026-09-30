#!/usr/bin/env node
/**
 * C+ 十屏 · **门控回归**（真实服务端配置的负例验收）
 *
 * 为什么必须另起一支工具：
 *   `cplus_screens_check.mjs` 验的是"配置正确时十屏都长对了"。它对**配置错误**
 *   是盲的 —— 只要把断言写歪一点（历史的 `!!x >= 0` 恒真、`|| mode==='v2'`
 *   让总开关一开就无视清单），十屏全绿看上去毫无异常。
 *   本项目已经栽过一次：实测「总关 + 空清单」下那支工具照样打印 `hit=true`。
 *   所以这里反过来做：**故意把服务端配置改坏**，要求每个负例都真的退回旧样式。
 *
 * 三条不容含糊的规则：
 *   ① 配置必须来自**服务端模板渲染**（环境变量 → api.py → index.html 属性），
 *      不是在 DevTools 里改 `documentElement.dataset` —— 后者证明不了模板接线。
 *   ② 基准不是写死的常量，是**同一台机器同一次运行里量出来的**：
 *        `full` 配置下每屏的签名 = "开着的样子"，`off` 配置下 = "关掉的样子"。
 *      然后逐条对照，于是"这一屏到底该长什么样"永远不需要人工维护常量。
 *   ③ 每条负例都必须**指出退回到哪种旧样子**：
 *        list 里删掉 replay  → replay 的签名必须**逐字节等于 off 下的 replay**，
 *                              同时其余九屏必须**逐字节等于 full 下的它们**。
 *      这一条同时覆盖了 A02 的两半：单屏关得掉、别的屏不受影响。
 *
 * 覆盖：
 *   full       v2 + 完整清单                    —— 基线：十屏都得是"开着"的样子
 *   off        总关 + 完整清单                  —— 十屏都得退回、且**没有任何 C+ DOM 残留**
 *   empty      v2 + 空清单                      —— 同上
 *   no-replay  v2 + 清单里删掉 replay            —— 只退 replay，其余九屏不受影响
 *   no-room     v2 + 清单里删掉 room             —— 只退 room（换一屏再验一遍，防"只对 replay 特判"）
 *   only-lobby v2 + 只有 lobby                  —— 只有 lobby 开着，其余九屏全退
 *   unknown    v2 + 清单里混入不存在的 token      —— 不该多开任何一屏，也不该少开
 *   odd-list   v2 + 前后/中间多空格的清单         —— 空白切分不能被写坏
 *
 * 用法：
 *   node tools/cplus_gate_check.mjs                 # 全部用例
 *   node tools/cplus_gate_check.mjs --cases off,no-replay
 *   node tools/cplus_gate_check.mjs --keep-shots    # 每个用例每个视口留一张对照图
 * 参数：
 *   --python <exe>     Python 解释器（默认 python）
 *   --base-port <n>    服务器端口基址（默认 9391，按用例递增）
 *   --browser <path>   浏览器可执行文件（默认探测 Edge/Chrome）
 *   --shots <dir>      截图目录（默认 .tmp/cplus-gate/shots）
 *   --cases <a,b>      只跑指定用例
 * 退出码：0 全过；1 有 FAIL；2 SKIP（没有浏览器或起不了服务端）。
 *
 * ⚠️ 本工具**自己起服务端**：每用例一个独立端口 + 独立 SQLite（都在 .tmp 下），
 *    不碰 5000 / 5057 等已有实例，也不使用 5060／5061（手册里保留的端口）。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..');
const TMPROOT = path.join(REPO, '.tmp', 'cplus-gate');
const PY = argOf('--python', 'python');
const BASE_PORT = Number(argOf('--base-port', '9391'));
const SHOTS = argOf('--shots', path.join(TMPROOT, 'shots'));
const ONLY = argOf('--cases', '').split(',').map((s) => s.trim()).filter(Boolean);
const KNOWN_BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const EDGE_EXPLICIT = argOf('--browser', '');
const EDGE = EDGE_EXPLICIT ? (fs.existsSync(EDGE_EXPLICIT) ? EDGE_EXPLICIT : null)
  : KNOWN_BROWSERS.find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const ALL_TOKENS = ['lobby', 'room', 'placement', 'collection', 'leaderboard',
  'profile', 'result', 'spectate', 'replay', 'settings'];
const without = (...drop) => ALL_TOKENS.filter((t) => !drop.includes(t)).join(' ');

/* 用例表。`mode`/`list` 直接进环境变量，由 api.py 读走并渲染进模板。 */
const CASES = [
  { id: 'full', mode: 'v2', list: ALL_TOKENS.join(' '),
    expect: 'all-on', note: '基线：十屏都该是"开着"的样子' },
  { id: 'off', mode: 'off', list: ALL_TOKENS.join(' '),
    expect: 'all-off', note: '总关：十屏全部退回，且不留 C+ 空容器' },
  { id: 'empty', mode: 'v2', list: '',
    expect: 'all-off', note: '空清单：等价于全关' },
  { id: 'no-replay', mode: 'v2', list: without('replay'),
    expect: 'only-off:replay', note: '删 replay token：只退 replay' },
  { id: 'no-room', mode: 'v2', list: without('room'),
    expect: 'only-off:room', note: '删 room token：只退 room（换一屏防特判）' },
  { id: 'only-lobby', mode: 'v2', list: 'lobby',
    expect: 'only-on:lobby', note: '只开 lobby：其余九屏全退' },
  { id: 'unknown', mode: 'v2', list: ALL_TOKENS.join(' ') + ' nosuchtoken',
    expect: 'all-on', note: '未知 token 不该改变任何一屏' },
  { id: 'odd-list', mode: 'v2', list: '  ' + ALL_TOKENS.join('   ') + '  ',
    expect: 'all-on', note: '多余空白不该切断 token' },
];

/* 每屏的签名怎么量。三条都必须是**只有 C+ 层才会改**的东西：
     eyebrow —— 屏头 ::before 的 content（C+ 独有）
     align   —— 标题 computed text-align（C+ 把原来居中的标题改成左对齐）
     radius  —— 标记物的圆角（C+ 面板档位）

   另有两组：
     containers —— **C+ 新加的空壳**（关屏时必须不可见，否则页面上留一个无样式空块）。
                   只有"关掉之后没有任何意义"的元素才算：领奖台、图鉴详情栏、
                   设置里的样式预览。像 `.ax-deploy-side` 这种**装着真控件**的容器
                   不算 —— 它关掉之后仍然该在，只是回到旧的纵向排布（见 anchor）。
     anchor     —— 这一屏的**可用性锚点**（关键控件/容器）。要求它在**每一种配置下**
                   都存在、可见、宽高非零 —— 这就是"配置退回仍然给出可用的旧体验"
                   那条验收的可执行形式；只把样式关掉、把操作也一起弄没了是不行的。 */
const SIGNATURE = [
  { key: 'lobby', root: 'lobby-screen', title: '#lobby-screen > h2', marker: '#lobby-screen .lobby-panel',
    containers: ['#lobby-screen .ax-panel'], anchor: '#lobby-screen .lobby-panel' },
  { key: 'room', root: 'custom-room-screen', title: '#custom-room-screen > h1', marker: '#custom-room-info',
    containers: [], anchor: '#custom-current-room-id',
    before: `(function(){ var i = document.getElementById('custom-room-info'); if (i) i.classList.remove('hidden');
      var c = document.getElementById('custom-current-room-id'); if (c && !c.textContent.trim()) c.textContent='A7C2E1'; return 1; })()` },
  { key: 'placement', root: 'ship-placement-screen', title: '#ship-placement-screen > h2', marker: '.ax-deploy-side',
    containers: [], anchor: '#random-ships',
    before: `(function(){ var b = document.getElementById('player-board'); if (b && !b.children.length && typeof initBoard === 'function') initBoard(b, true); return 1; })()` },
  { key: 'collection', modal: 'help-modal', title: '#help-modal .modal-content > h2', marker: '.ax-codex',
    containers: ['#codex-detail'], anchor: '#help-magic-cards',
    before: `(function(){ document.getElementById('help-btn').click(); return 1; })()` },
  { key: 'leaderboard', root: 'leaderboard-screen', title: '#leaderboard-screen > h2', marker: '#leaderboard-tabs',
    containers: ['#leaderboard-podium'], anchor: '#leaderboard-table',
    before: `(function(){ if (typeof showLeaderboard === 'function') showLeaderboard(); return 1; })()` },
  { key: 'profile', modal: 'opponent-stats-modal', title: '#opponent-stats-modal .modal-content > h2', marker: '#opponent-stats-title',
    containers: [], anchor: '#opponent-stats-modal .modal-content',
    before: `(function(){ var n = window.__USERNAME || ''; if (typeof window.showUserProfile === 'function') window.showUserProfile(n); return 1; })()` },
  { key: 'result', root: 'game-over-screen', title: '#game-over-screen .over-verdict > h2', marker: '.over-verdict',
    containers: [], anchor: '#game-over-screen .over-wrap',
    before: `(function(){ var r = document.getElementById('game-result'); if (r && !r.textContent.trim()) r.textContent='胜利';
      var h = document.getElementById('over-head'); if (h) h.classList.add('win'); return 1; })()` },
  { key: 'spectate', root: 'spectate-screen', title: '#spectate-screen > .spectate-title', marker: '.spectate-topbar',
    containers: [], anchor: '#spectate-screen .spectate-topbar' },
  { key: 'replay', root: 'replay-screen', title: '#replay-screen > .replay-title', marker: '.replay-topbar',
    containers: [], anchor: '#replay-screen .replay-topbar' },
  { key: 'settings', modal: 'settings-modal', title: '#settings-modal .modal-content > h2', marker: '.ax-preview',
    modal2: null, containers: ['#settings-preview'], anchor: '#settings-modal .modal-content',
    before: `(function(){ if (typeof openSettingsModal === 'function') openSettingsModal('look');
      else document.getElementById('settings-btn').click(); return 1; })()` },
];

/* 主题／预设不该改变**布局模式**（结构轴与颜色轴分开，见实施方案 §5 与
   arena_screens.css 文件头）。所以下面这组在 full 配置上换轴，要求签名不变。
   ⚠️ `custom` 不是 THEME_PRESETS 里的成员（game.js:638 那八个里没有它）——
   它表示"玩家动过主色微调"，落到 html 上靠的是**存了 battleship_primary_color
   且没有合法 preset**（applyCustomPrimaryColor 会写一个会被下次加载判为非法的
   'custom'，于是走主色分支）。所以这一档要写主色键、删 preset 键，
   直接往 preset 里塞 'custom' 会被 applyThemePreset() 判非法并落回 arena
   ——第一版就是这么写的，量到 preset 仍是 'arena'，看着像门控坏了，其实是驱动方式错。 */
const THEME_AXIS = [
  { id: 'dark-arena', theme: 'dark', preset: 'arena' },
  { id: 'light-arena', theme: 'light', preset: 'arena' },
  { id: 'dark-custom', theme: 'dark', color: '#7c5cf0' },
  { id: 'light-custom', theme: 'light', color: '#7c5cf0' },
  { id: 'dark-fluent', theme: 'dark', preset: 'fluent' },
];

const MEASURE = `(function(cfg){
  function q(sel){ try { return document.querySelector(sel); } catch (e) { return null; } }
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  document.querySelectorAll('.modal-overlay').forEach(function(m){ m.classList.add('hidden'); });
  document.body.classList.remove('layout-compact', 'layout-ingame');
  var help = document.getElementById('help-content'); if (help) help.classList.remove('ax-show-detail');
  var setupError = null;
  if (cfg.before) { try { eval(cfg.before); } catch (e) { setupError = String(e).slice(0, 160); } }
  if (cfg.root) { var root = document.getElementById(cfg.root); if (root) root.classList.add('active'); }
  if (cfg.modal) { var m = document.getElementById(cfg.modal); if (m) m.classList.remove('hidden'); }
  var title = q(cfg.title);
  var marker = q(cfg.marker);
  var eb = title ? getComputedStyle(title, '::before') : null;
  var cont = {};
  (cfg.containers || []).forEach(function(sel){
    var e = q(sel);
    cont[sel] = e ? getComputedStyle(e).display : (cfg.modal || null ? 'absent' : 'absent');
  });
  var anchorEl = q(cfg.anchor);
  var anchor = null;
  if (anchorEl) {
    var acs = getComputedStyle(anchorEl), ar = anchorEl.getBoundingClientRect();
    anchor = { selector: cfg.anchor, display: acs.display, visibility: acs.visibility,
      w: Math.round(ar.width), h: Math.round(ar.height),
      inViewport: ar.width > 0 && ar.height > 0 && ar.bottom > 0 && ar.right > 0
        && ar.top < window.innerHeight && ar.left < window.innerWidth };
  } else { anchor = { selector: cfg.anchor, display: 'absent' }; }
  return {
    setupError: setupError,
    eyebrow: (eb && eb.content && eb.content !== 'none') ? eb.content : null,
    align: title ? getComputedStyle(title).textAlign : null,
    fontSize: title ? getComputedStyle(title).fontSize : null,
    radius: marker ? getComputedStyle(marker).borderTopLeftRadius : null,
    gate: {
      mode: document.documentElement.getAttribute('data-arena-screens'),
      list: document.documentElement.getAttribute('data-arena-screen-list'),
    },
    containers: cont,
    anchor: anchor,
  };
})`;

/* 只比对"层控能改变的东西"；gate 本身每个用例不同，**不进签名**。 */
function sigOf(m) {
  return JSON.stringify({ eyebrow: m.eyebrow, align: m.align, fontSize: m.fontSize,
    radius: m.radius, containers: m.containers });
}

if (!EDGE) {
  console.log('SKIP  没有找到可用的 Edge/Chrome —— 这**不是通过**，是未验收。');
  if (EDGE_EXPLICIT) console.log('      --browser 指定的路径不存在：' + EDGE_EXPLICIT);
  else console.log('      已探测：\n        ' + KNOWN_BROWSERS.join('\n        '));
  process.exit(2);
}

fs.mkdirSync(TMPROOT, { recursive: true });
const PROFILE = path.join(TMPROOT, 'profile');
fs.mkdirSync(PROFILE, { recursive: true });
const DEBUG_PORT = BASE_PORT + 500;

/* ---------- 起一个只服务本工具的服务端 ---------- */
function startServer(c) {
  const port = BASE_PORT + CASES.indexOf(c);
  const dir = path.join(TMPROOT, c.id);
  fs.mkdirSync(dir, { recursive: true });
  const env = {
    ...process.env,
    BATTLESHIP_DB_PATH: path.join(dir, 'gate.db'),
    PORT: String(port),
    CORS_ORIGINS: 'http://127.0.0.1:' + port,
    ENABLE_TEST_EVENTS: '1',
    TURN_TIMEOUT_SECONDS: '0',
    TMP: dir, TEMP: dir,
    ARENA_SCREENS_MODE: c.mode,
    ARENA_SCREEN_LIST: c.list,
  };
  // ⚠️ 端口要拼进 Python 源码里：写成 `'…port=%d…' % port` 是**Python 的**格式化，
  //    在 JS 里 `%` 是取模 —— 整条命令会变成字面量 `NaN`，服务端起不来还看不出原因。
  const code = 'import server; server.db.init_db(); '
    + 'server.socketio.run(server.app, host="127.0.0.1", port=' + port
    + ', debug=False, use_reloader=False)';
  const logFile = fs.openSync(path.join(dir, 'server.log'), 'w');
  const child = spawn(PY, ['-c', code], { cwd: REPO, env, stdio: ['ignore', logFile, logFile] });
  return { child, port, url: 'http://127.0.0.1:' + port + '/', log: path.join(dir, 'server.log') };
}

async function waitUp(url, tries) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(url); if (r.ok) return true; } catch (e) { /* 还没起来 */ }
    await sleep(400);
  }
  return false;
}

console.log('== C+ 门控回归（真实服务端配置）==');
console.log('   浏览器 ' + EDGE);
console.log('   profile ' + PROFILE + '   服务端端口从 ' + BASE_PORT + ' 起');

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + DEBUG_PORT,
  '--user-data-dir=' + PROFILE, 'about:blank'], { stdio: 'ignore' });

const started = [];
let ws = null;
let exitCode = 0;
try {
  // ---- 连浏览器 ----
  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + DEBUG_PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还没起来 */ }
    await sleep(500);
  }
  if (!target) { console.error('无法连接无头浏览器调试端口 ' + DEBUG_PORT); process.exit(3); }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const id = ++seq; pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 25000);
  });
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 300) };
    return r.result && r.result.value;
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  /* 量一个实例下的十屏签名。可选地在测之前把主题轴设成 theme/preset。 */
  async function measureAll(url, axis) {
    await send('Page.navigate', { url });
    for (let i = 0; i < 60; i++) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break; await sleep(300); }
    await sleep(700);
    if (axis) {
      await ev(`(function(){ try {
        localStorage.setItem('theme', ${JSON.stringify(axis.theme)});
        if (${JSON.stringify(axis.color || null)}) {
          localStorage.setItem('battleship_primary_color', ${JSON.stringify(axis.color || '')});
          localStorage.removeItem('battleship_theme_preset');
        } else {
          localStorage.setItem('battleship_theme_preset', ${JSON.stringify(axis.preset || 'arena')});
          localStorage.removeItem('battleship_primary_color');
        }
      } catch (e) {} return 1; })()`);
      await send('Page.navigate', { url });
      for (let i = 0; i < 60; i++) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break; await sleep(300); }
      await sleep(700);
    }
    const pageGate = await ev('(function(){ return { mode: document.documentElement.getAttribute("data-arena-screens"), list: document.documentElement.getAttribute("data-arena-screen-list"), preset: document.documentElement.getAttribute("data-theme-preset"), dark: document.documentElement.classList.contains("theme-dark") }; })()');
    const out = {};
    for (const s of SIGNATURE) {
      const cfg = JSON.stringify({ root: s.root || null, title: s.title, marker: s.marker, modal: s.modal || null,
        containers: s.containers || [], anchor: s.anchor, before: s.before || null });
      const m = await ev('(' + MEASURE + ')(' + cfg + ')');
      out[s.key] = m;
    }
    return { gate: pageGate, sigs: out };
  }

  console.log('');
  console.log('-- 1. 负例矩阵（每个用例一个独立端口 + 独立库）--');
  const measured = {};
  const wanted = CASES.filter((c) => !ONLY.length || ONLY.includes(c.id));
  for (const c of wanted) {
    const srv = startServer(c);
    started.push(srv);
    const up = await waitUp(srv.url, 60);
    if (!up) {
      check(false, '[' + c.id + '] 服务端起得来（' + srv.url + '）', { mode: c.mode, list: c.list, log: srv.log });
      continue;
    }
    const r = await measureAll(srv.url);
    // 模板真的注入了这两个值吗？—— 这是"配置来自服务端"的直接证据
    check(r.gate && r.gate.mode === c.mode, '[' + c.id + '] 模板注入的 mode 与服务端配置一致', r.gate);
    check(r.gate && r.gate.list === c.list, '[' + c.id + '] 模板注入的 list 与服务端配置一致', r.gate && { got: r.gate.list, want: c.list });
    measured[c.id] = r;
    console.log('   [' + c.id + '] ' + c.note);
  }

  const base = measured['full'];
  const off = measured['off'];
  if (!base || !off) {
    check(false, '基线用例（full / off）必须都跑到 —— 否则无法做相对判定', { have: Object.keys(measured) });
  } else {
    console.log('');
    console.log('-- 2. 每屏"开着 / 关掉"必须真的不同（十屏都得受控）--');
    for (const s of SIGNATURE) {
      const a = sigOf(base.sigs[s.key]), b = sigOf(off.sigs[s.key]);
      check(a !== b, '屏 ' + s.key + '：总关后签名确实变了（这一屏真的受门控）',
        a === b ? { signature: a, hint: '门控对这一屏没生效 —— 公共规则很可能只挂了总开关' } : undefined);
    }
    console.log('');
    console.log('-- 3. 关掉时不许留 C+ 空容器（无样式空块 / 领奖台残留）--');
    for (const s of SIGNATURE) {
      const m = off.sigs[s.key];
      const visible = Object.entries(m.containers || {})
        .filter(([, d]) => d !== 'none' && d !== 'absent')
        .map(([sel, d]) => ({ selector: sel, display: d }));
      check(visible.length === 0, '屏 ' + s.key + '：总关后没有可见的 C+ 新增容器',
        visible.length ? visible : undefined);
    }
    console.log('');
    console.log('-- 3b. 每一种配置下，十屏都仍然可用（配置退回 = 可用的旧体验）--');
    for (const c of wanted) {
      const r = measured[c.id];
      if (!r) continue;
      for (const s of SIGNATURE) {
        const a = r.sigs[s.key].anchor;
        check(!!a && a.display !== 'none' && a.display !== 'absent' && a.w > 0 && a.h > 0 && a.inViewport,
          '[' + c.id + '] 屏 ' + s.key + ' 的可用性锚点在位（' + s.anchor + '）', a);
      }
    }
    console.log('');
    console.log('-- 4. 逐屏关：只退被删的那一屏，其余九屏不受影响 --');
    for (const c of wanted) {
      if (!c.expect.startsWith('only-off:')) continue;
      const r = measured[c.id];
      if (!r) continue;
      const gone = c.expect.split(':')[1];
      for (const s of SIGNATURE) {
        const isTarget = s.key === gone;
        const want = isTarget ? sigOf(off.sigs[s.key]) : sigOf(base.sigs[s.key]);
        const got = sigOf(r.sigs[s.key]);
        check(got === want,
          '[' + c.id + '] 屏 ' + s.key + (isTarget ? ' 退回旧样式（= 总关时的样子）' : ' 保持 C+ 样子（不受影响）'),
          got === want ? undefined : { got, want });
      }
      const vis = Object.entries(r.sigs[gone].containers || {})
        .filter(([, d]) => d !== 'none' && d !== 'absent').map(([sel, d]) => ({ selector: sel, display: d }));
      check(vis.length === 0, '[' + c.id + '] 被删 token 的那一屏不留可见 C+ 容器', vis.length ? vis : undefined);
    }
    console.log('');
    console.log('-- 5. 只开一屏：其余九屏全部退回 --');
    const only = wanted.filter((c) => c.expect.startsWith('only-on:'));
    for (const c of only) {
      const r = measured[c.id];
      if (!r) continue;
      const onKey = c.expect.split(':')[1];
      for (const s of SIGNATURE) {
        const want = s.key === onKey ? sigOf(base.sigs[s.key]) : sigOf(off.sigs[s.key]);
        const got = sigOf(r.sigs[s.key]);
        check(got === want, '[' + c.id + '] 屏 ' + s.key + (s.key === onKey ? ' 开着' : ' 退回'),
          got === want ? undefined : { got, want });
      }
    }
    console.log('');
    console.log('-- 6. 未知 token / 冗余空白：不该改变任何一屏 --');
    for (const id of ['unknown', 'odd-list']) {
      const r = measured[id];
      if (!r) continue;
      for (const s of SIGNATURE) {
        const got = sigOf(r.sigs[s.key]), want = sigOf(base.sigs[s.key]);
        check(got === want, '[' + id + '] 屏 ' + s.key + ' 与全开基线一致', got === want ? undefined : { got, want });
      }
    }
  }

  console.log('');
  console.log('-- 7. 主题／预设不该改变布局模式（结构轴 ≠ 颜色轴）--');
  if (base) {
    for (const ax of THEME_AXIS) {
      const srv = started.find((s) => s.url);
      const r = await measureAll(srv.url, ax);
      for (const s of SIGNATURE) {
        const got = sigOf(r.sigs[s.key]), want = sigOf(base.sigs[s.key]);
        check(got === want, '[轴 ' + ax.id + '] 屏 ' + s.key + ' 布局签名不变',
          got === want ? undefined : { got, want });
      }
      check(r.gate && r.gate.preset === (ax.preset || 'custom'),
        '[轴 ' + ax.id + '] 预设真的落在了 html 上', r.gate);
    }
  }

  console.log('');
  if (problems.length) {
    console.log('✗ ' + problems.length + ' 项未通过：');
    problems.slice(0, 40).forEach((p) => console.log('   · ' + p));
    if (problems.length > 40) console.log('   … 共 ' + problems.length + ' 项');
    exitCode = 1;
  } else {
    console.log('✓ 全部通过（' + (wanted.length) + ' 个配置用例 + 主题轴矩阵）');
  }
} finally {
  for (const s of started) { try { s.child.kill(); } catch (e) { /* 已经退了 */ } }
  try { if (ws) ws.close(); } catch (e) { /* 已断 */ }
  try { browser.kill(); } catch (e) { /* 已经退了 */ }
}
process.exit(exitCode);
