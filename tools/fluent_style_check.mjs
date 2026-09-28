#!/usr/bin/env node
/**
 * Fluent / Windows 11（微软）风格专项验收 —— 无头 Edge + CDP，可复跑。
 *
 * 为什么需要它：Fluent 改版会重写 style.css 的令牌与组件层，而既有的
 * `ui_layout_check.mjs` 只验「布局不变量」。缺了这个工具，「令牌没落地 / 字体没换 /
 * 圆角还是旧的任意值 / 强调色按钮还是渐变 / 深色不跟随系统」这类问题**不报错**，
 * 只是看着不像 Windows 11 —— 只能靠人眼，且下次谁改回去也没人发现。
 *
 * 四个断言组（`--only` 可单跑）：
 *   set      令牌 / 字体 / 圆角档位 / 材质（半透明+模糊）与定位安全 / 强调色与对比度 / 首页标题不再是渐变文字
 *   presets  8 个预设存在且分成两组 / 默认预设 = fluent / 8 个预设同规范（形状与间距必须一致）/
 *            强调色两两不同 / 8 预设 × 明暗两态的正文对比度
 *   dark     跟随系统（dark/light）+ 用户显式选择优先 + 主题引导脚本在 <head>（无闪烁）
 *   shots    6 个视口截图
 *
 * 用法：
 *   node tools/fluent_style_check.mjs --url http://127.0.0.1:5099/ [--shots DIR] [--only set|presets|dark|shots]
 *
 * 目标服务端怎么起（隔离库；⚠️ 端口别用 5060/5061 —— Fetch 规范的被阻止端口，
 * Node fetch / Chrome 会拒发而 curl 正常，看着像服务器卡死）：
 *   BATTLESHIP_DB_PATH=.tmp/fluent_check.db CORS_ORIGINS=http://127.0.0.1:5099 PORT=5099 python server.py
 *   node tools/fluent_style_check.mjs --url http://127.0.0.1:5099/
 *
 * 退出码：0 = 全部通过；1 = 有 FAIL（明细在结尾汇总里重复一遍）。
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const ONLY = argOf('--only', '');
const PORT = Number(argOf('--port', '9344'));   // 固定调试端口：9344 在本项目其它工具（9333/9334/9335/…）之外
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const SHOTS_ARG = argOf('--shots', '.tmp/fluent_shots/');
const SHOTS_DIR = path.isAbsolute(SHOTS_ARG) ? SHOTS_ARG : path.join(ROOT, SHOTS_ARG);

// 验收常量（集中一处，改设计只改这里）
const ACCENT = '#0078d4';                        // Fluent 2 的默认强调色
const ACCENT_RGB = 'rgb(0, 120, 212)';
const ACCENT_OBJ = { r: 0, g: 120, b: 212, a: 1 };
/* Fluent 的两档：控件 4 / 卡片 8。
   2026-09-27（1:1 复刻示意稿 C/V 批）追加 12px：**arena 预设自带一套形状** ——
   示意稿里的入口卡/主行动就是 12px 圆角、面板 14px，压成 8px 就不叫复刻了。
   其它 7 个预设仍然只用 4/8（下面的"同规范签名"断言把这层区分也钉住了）。 */
const RADIUS_ALLOWED = ['4px', '8px', '12px'];
// arena 的专属形状档（其余预设必须完全一致，见下面那条断言）
const ARENA_PRESET = 'arena';
const PRESETS = ['fluent', 'deep', 'lava', 'cyber', 'dusk', 'aurora', 'classic', 'arena'];
const LEGACY_PRESETS = ['deep', 'lava', 'cyber', 'dusk', 'aurora', 'classic'];
const SPACE_TOKENS = ['--fluent-space-2', '--fluent-space-3', '--fluent-space-4'];
const CONTRAST_MIN = 4.5;
const GROUPS = ['set', 'presets', 'dark', 'shots'];

// ⚠️ 找不到浏览器就跳过（退出码 0）：CI/别人机器上没有 Edge 时不该判失败。
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
// profile 放项目内 .tmp/（不要 C:/Windows/Temp：那台机器的临时目录 ACL 坏过，
// 而且残留 profile 会带着上轮的 localStorage，让「默认预设」这类断言假绿）。
const PROFILE = path.join(ROOT, '.tmp', 'fluent_style_check_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const SHOT_VIEWPORTS = [
  ['1600x1000', 1600, 1000, 1, false],
  ['1440x900', 1440, 900, 1, false],
  ['1366x768', 1366, 768, 1, false],
  ['1024x768', 1024, 768, 1, false],
  ['390x844', 390, 844, 3, true],
  ['320x568', 320, 568, 2, true],
];

if (ONLY && !GROUPS.includes(ONLY)) {
  console.error('--only 只能是 ' + GROUPS.join('|') + '，收到: ' + ONLY);
  process.exit(2);
}
if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过 Fluent 风格检查'); process.exit(0); }

const t0 = Date.now();
let browser = null, ws = null;
const pending = new Map();
const problems = [];
let seq = 0;

// ---------------------------------------------------------------------------
// 残留进程预清理
// ---------------------------------------------------------------------------
// ⚠️ 残留的无头进程会让新浏览器**静默起不来**（端口没释放 / profile 被锁），
// 于是工具连上的是上一轮的实例、带着上一轮的 localStorage —— 表现为随机假红。
// 这里按 profile 名匹配杀进程（比按端口更准，不会误伤别的工具）。
function preClean() {
  for (const exe of ['msedge.exe', 'chrome.exe']) {
    try {
      execSync('powershell -NoProfile -Command "' +
        'Get-CimInstance Win32_Process -Filter \\"Name=\'' + exe + '\'\\" | ' +
        'Where-Object { $_.CommandLine -like \'*fluent_style_check_profile*\' } | ' +
        'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
        { stdio: 'ignore', timeout: 20000 });
    } catch (e) { /* 没有残留就够了 */ }
  }
}

// ⚠️ 不能只写 list.find(t => t.type === 'page')：headless Edge 自带一个
// edge://sync-confirmation-dialog 页面，且稳定排在 /json/list 第一位 →
// 所有断言都会跑在那个内置页上（症状是「全项假红」，不是报错）。
function pickPage(list) {
  const isApp = (t) => t.type === 'page' && /^(https?|file):/.test(t.url || '');
  return list.find(isApp) || list.find((t) => t.type === 'page' && t.url !== 'about:blank'
    && !/^(edge|chrome|devtools):/.test(t.url || '')) || list.find((t) => t.type === 'page');
}

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
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    try { if (await fn()) return true; } catch (e) { /* 导航中：继续轮询 */ }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label);
}

let currentPass = 'init';
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + '[' + currentPass + '] ' + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push('[' + currentPass + '] ' + label);
}

// ---------------------------------------------------------------------------
// Node 侧的颜色 / 对比度工具（WCAG 相对亮度，自己算，不借第三方）
// ---------------------------------------------------------------------------
function parseColor(input) {
  const s = String(input == null ? '' : input).trim().toLowerCase();
  if (!s) return null;
  if (s === 'transparent') return { r: 0, g: 0, b: 0, a: 0 };
  const m = s.match(/^rgba?\(([^)]+)\)$/);
  if (m) {
    const parts = m[1].split(/[,/\s]+/).filter(Boolean);
    if (parts.length < 3) return null;
    const r = Number(parts[0]), g = Number(parts[1]), b = Number(parts[2]);
    if ([r, g, b].some((v) => Number.isNaN(v))) return null;
    let a = 1;
    if (parts.length > 3) {
      const raw = String(parts[3]);
      const n = Number(raw.replace('%', ''));
      a = Number.isNaN(n) ? 1 : (raw.endsWith('%') ? n / 100 : n);
    }
    return { r, g, b, a };
  }
  const h = s.match(/^#([0-9a-f]{3,8})$/);
  if (h) {
    let hex = h[1];
    if (hex.length === 3 || hex.length === 4) hex = hex.split('').map((c) => c + c).join('');
    return {
      r: parseInt(hex.slice(0, 2), 16), g: parseInt(hex.slice(2, 4), 16), b: parseInt(hex.slice(4, 6), 16),
      a: hex.length >= 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1,
    };
  }
  return null;
}
const sameColor = (a, b, tol = 2) => !!a && !!b
  && Math.abs(a.r - b.r) <= tol && Math.abs(a.g - b.g) <= tol && Math.abs(a.b - b.b) <= tol;
function relLum(c) {
  const f = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
}
function contrastRatio(a, b) {
  const l1 = relLum(a), l2 = relLum(b);
  const hi = Math.max(l1, l2), lo = Math.min(l1, l2);
  return (hi + 0.05) / (lo + 0.05);
}
const r2 = (n) => Math.round(n * 100) / 100;

// 页面底色取法：body 的 background-color 若是不透明实色就用它；否则用 `--fluent-layer-bg`
// （令牌层里的「页面实心底色」；--bg-page 只是叠在它上面的渐变，不能拿来算对比度）。
function pickPageBg(theme) {
  const c = parseColor(theme.bodyBgColor);
  if (c && c.a > 0.95) return { color: c, source: 'body background-color' };
  const l = parseColor(theme.layerBg);
  if (l) return { color: { r: l.r, g: l.g, b: l.b, a: 1 }, source: '--fluent-layer-bg ' + theme.layerBg };
  if (c && c.a > 0) return { color: c, source: 'body background-color(半透明)' };
  return null;
}

// 深色标记：目前是 `html.theme-dark`。这里认三种写法并打印实际命中的那个，
// 免得将来引导脚本换成 data-theme="dark" 时工具只会红、说不出为什么。
function darkMarker(theme) {
  if (/\btheme-dark\b/.test(theme.htmlClass || '')) return 'class theme-dark';
  if (String(theme.dataThemeAttr || '') === 'dark') return 'attr data-theme=dark';
  if (String(theme.htmlClass || '').split(/\s+/).includes('dark')) return 'class dark';
  return null;
}

// ---------------------------------------------------------------------------
// 页面内探针（用 toString() 注入到页面里执行；只依赖自己的参数，别引用模块作用域）
// ---------------------------------------------------------------------------

// ① 令牌：读 html 计算样式里所有 `--fluent-*`。
//    Chromium 会把自定义属性放进 computed style，但**枚举**可能不全（@media / @supports 里的声明），
//    所以再用 cssRules 兜一遍 —— 两处合并后才算数。
function tokensProbe() {
  function fromRules() {
    var map = {};
    var sheets = document.styleSheets;
    for (var i = 0; i < sheets.length; i++) {
      var rules = null;
      try { rules = sheets[i].cssRules; } catch (e) { continue; }   // 跨域表读不到，跳过
      if (!rules) continue;
      for (var j = 0; j < rules.length; j++) {
        var r = rules[j];
        if (!r.style || !r.selectorText) continue;
        for (var k = 0; k < r.style.length; k++) {
          var p = r.style[k];
          if (String(p).indexOf('--fluent-') !== 0) continue;
          var v = String(r.style.getPropertyValue(p) || '').trim();
          if (v) map[p] = v;
        }
      }
    }
    return map;
  }
  var root = getComputedStyle(document.documentElement);
  var list = [];
  var empty = [];
  for (var i = 0; i < root.length; i++) {
    var n = root[i];
    if (String(n).indexOf('--fluent-') !== 0) continue;
    var val = String(root.getPropertyValue(n) || '').trim();
    if (val) list.push({ name: n, value: val }); else empty.push(n);
  }
  var fromComputed = list.length;
  var rules = fromRules();
  var ruleNames = Object.keys(rules);
  var have = {};
  list.forEach(function (t) { have[t.name] = 1; });
  ruleNames.forEach(function (k) { if (!have[k]) list.push({ name: k, value: rules[k] }); });
  list.sort(function (a, b) { return a.name < b.name ? -1 : 1; });
  // `--primary` 的**解析后**颜色：自定义属性本身只是文本，只有塞进一个元素的 color
  // 才拿得到浏览器真正用的 rgb()（`rgb(0, 120, 212)` 还是 `#0078d4` 由浏览器决定）。
  var probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;left:-9999px;top:0;color:var(--primary)';
  document.documentElement.appendChild(probe);
  var resolved = getComputedStyle(probe).color;
  probe.parentNode.removeChild(probe);
  return {
    fromComputed: fromComputed, fromRules: ruleNames.length, empty: empty, tokens: list,
    primaryRaw: String(root.getPropertyValue('--primary') || '').trim(),
    primaryResolved: resolved
  };
}

// ② 任意选择器的一批计算值。一个探针打天下：字体/圆角/材质/强调色/标题都在这里取。
function styleProbe(pairs) {
  var out = [];
  for (var i = 0; i < pairs.length; i++) {
    var label = pairs[i][0], sel = pairs[i][1];
    var el = null;
    try { el = document.querySelector(sel); } catch (e) { el = null; }
    if (!el) { out.push({ label: label, selector: sel, found: false }); continue; }
    var cs = getComputedStyle(el);
    var bf = cs.backdropFilter || cs.getPropertyValue('backdrop-filter') || 'none';
    var wbf = cs.getPropertyValue('-webkit-backdrop-filter') || 'none';
    out.push({
      label: label, selector: sel, found: true,
      visible: !(cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0'),
      radius: cs.borderRadius,
      corners: [cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomRightRadius, cs.borderBottomLeftRadius],
      fontFamily: cs.fontFamily,
      backgroundColor: cs.backgroundColor,
      backgroundImage: cs.backgroundImage,
      color: cs.color,
      webkitFill: cs.getPropertyValue('-webkit-text-fill-color') || cs.webkitTextFillColor || '',
      transform: cs.transform,
      filter: cs.filter,
      backdropFilter: bf,
      webkitBackdropFilter: wbf,
      position: cs.position
    });
  }
  return out;
}

// ③ 任意自定义属性的字面值（间距/圆角令牌）。
function varsProbe(names) {
  var root = getComputedStyle(document.documentElement);
  var out = {};
  for (var i = 0; i < names.length; i++) out[names[i]] = String(root.getPropertyValue(names[i]) || '').trim();
  return out;
}

// ④ 预设区结构：不猜 DOM 形状，直接把它汇报出来，由 Node 侧判断「有没有两个分组容器」。
function presetStructureProbe() {
  var grid = document.getElementById('theme-preset-grid');
  if (!grid) return { grid: false };
  var cards = [].slice.call(grid.querySelectorAll('.theme-card[data-preset]'));
  // ⚠️ `children` 只取**直接子节点**，所以对「7 张卡直接挂在网格下」的扁平结构，
  // 卡自己的 cardCount 只能是 1（querySelectorAll 在自身内部找不到自己）。
  // 之前漏了这一步，输出里卡片显示「(0张)」，看着像解析器坏了。
  var children = [].slice.call(grid.children).map(function (c) {
    var isCard = c.classList.contains('theme-card');
    var inner = isCard ? [c] : [].slice.call(c.querySelectorAll('.theme-card[data-preset]'));
    return {
      tag: c.tagName.toLowerCase(),
      cls: (typeof c.className === 'string' ? c.className : '') || '',
      isCard: c.classList.contains('theme-card'),
      preset: c.dataset ? (c.dataset.preset || null) : null,
      cardCount: c.classList.contains('theme-card') ? 1 : inner.length,
      presets: inner.map(function (x) { return x.dataset.preset; })
    };
  });
  // 「分组容器」= 直接子节点里不是卡、但装着卡的那些（一组一个）
  var groups = children.filter(function (c) { return !c.isCard && c.cardCount > 0; });
  return {
    grid: true,
    gridPresets: cards.map(function (c) { return c.dataset.preset; }),
    childShape: children.map(function (c) { return c.tag + (c.cls ? '.' + c.cls.split(' ').join('.') : '') + '(' + c.cardCount + '张)'; }),
    children: children,
    groupCount: groups.length,
    groups: groups.map(function (c) { return c.presets; }),
    ungroupedCards: children.filter(function (c) { return c.isCard; }).length
  };
}

// ⑤ 主题相关：html 的标记 / 底色令牌 / 正文色 / head 子节点顺序 / localStorage。
function themeProbe() {
  var html = document.documentElement;
  var body = document.body || html;
  var cs = getComputedStyle(body);
  var root = getComputedStyle(html);
  var headChildren = [].slice.call(document.querySelectorAll('head > *')).map(function (e, i) {
    var kind = 'other';
    if (e.tagName === 'SCRIPT') kind = 'script';
    else if (e.tagName === 'LINK' && String(e.getAttribute('rel') || '').indexOf('stylesheet') >= 0) kind = 'stylesheet';
    return {
      idx: i, tag: e.tagName.toLowerCase(), kind: kind,
      src: e.getAttribute('src') || '',
      text: e.tagName === 'SCRIPT' ? String(e.textContent || '').trim().slice(0, 300) : ''
    };
  });
  var read = function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } };
  return {
    htmlClass: String(html.className || ''),
    datasetThemePreset: html.dataset ? (html.dataset.themePreset || null) : null,
    dataThemeAttr: html.getAttribute('data-theme') || null,
    layerBg: String(root.getPropertyValue('--fluent-layer-bg') || '').trim(),
    bgPage: String(root.getPropertyValue('--bg-page') || '').trim(),
    bodyColor: cs.color,
    bodyBgColor: cs.backgroundColor,
    bodyBgImage: cs.backgroundImage,
    prefersDark: window.matchMedia('(prefers-color-scheme: dark)').matches,
    headChildren: headChildren,
    bodyBootstrapScripts: [].slice.call(document.querySelectorAll('body script')).filter(function (s) {
      return /theme-dark|prefers-color-scheme|data-theme-preset/.test(String(s.textContent || ''));
    }).length,
    localStorageTheme: read('theme'),
    localStoragePreset: read('battleship_theme_preset')
  };
}

// ⑥ 首页状态（截图前确认真的停在首页、动画已停）
function homeProbe() {
  var ss = document.getElementById('start-screen');
  var running = 0;
  try { running = document.getAnimations().filter(function (a) { return a.playState === 'running'; }).length; } catch (e) { running = -1; }
  return {
    startActive: !!ss && ss.classList.contains('active'),
    visibleScreens: [].slice.call(document.querySelectorAll('.screen')).filter(function (s) {
      var cs = getComputedStyle(s);
      return !(cs.display === 'none' || cs.visibility === 'hidden');
    }).map(function (s) { return s.id || s.className; }),
    runningAnimations: running,
    scrollY: window.scrollY
  };
}

// ---------------------------------------------------------------------------
// 驱动辅助
// ---------------------------------------------------------------------------
async function setViewport(w, h, dsf, mobile) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dsf, mobile: !!mobile });
  await send('Emulation.setTouchEmulationEnabled', { enabled: !!mobile, maxTouchPoints: 5 });
  await sleep(400);
}

async function setMedia(mode) {
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: mode }] });
}

// 导航 + 「等状态稳定」。
// ⚠️ readyState=complete 不等于主题就绪：主题引导脚本与 game.js 的
// restoreThemeFromStorage() 都挂在 DOMContentLoaded 上，还要读 localStorage。
// 这里连采两次快照、一致了才继续 —— 否则会读到中间态（表现为随机假红）。
async function reload(media) {
  if (media) await setMedia(media);
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 25000, '页面加载');
  await waitFor(async () => await ev('!!document.getElementById("start-screen")'), 20000, '首页 DOM');
  const started = Date.now();
  let last = null;
  while (Date.now() - started < 8000) {
    const snap = await ev('(function(){var h=document.documentElement,cs=getComputedStyle(h);' +
      'return [h.className,h.dataset.themePreset||"",(cs.getPropertyValue("--fluent-layer-bg")||"").trim(),' +
      '(cs.getPropertyValue("--primary")||"").trim()].join("|");})()').catch(() => null);
    if (snap && snap === last) return;
    last = snap;
    await sleep(250);
  }
}

async function clearStorage() {
  await ev('(function(){ try { localStorage.clear(); } catch(e){} return 1; })()');
}

async function openSettingsModal() {
  const ok = await ev('(function(){ var b=document.getElementById("settings-btn"); if(!b) return false; b.click(); return true; })()');
  await sleep(300);
  return ok && await ev('!!document.querySelector(".modal-overlay:not(.hidden)")');
}

async function closeOverlays() {
  await ev('(function(){ var o=document.querySelector(".modal-overlay:not(.hidden)"); if(o){ var c=o.querySelector(".modal-close"); if(c) c.click(); else o.classList.add("hidden"); } return 1; })()');
  await sleep(200);
}

// 切换预设：**优先点卡片**（真实用户路径，顺带验证事件绑定还在）。
// 卡片还没落地时（DOM 尚未改完）退化为直接写 dataset —— CSS 预设本来就靠
// `html[data-theme-preset="X"]` 生效，退化路径测出来的形状/颜色一样可信，
// 但会在输出里标出来，免得把「卡片缺失」当成通过。
async function applyPreset(name) {
  const sel = '#theme-preset-grid .theme-card[data-preset="' + name + '"]';
  const clicked = await ev('(function(){var c=document.querySelector(' + JSON.stringify(sel) + '); if(!c) return "no-card"; c.click(); return "clicked";})()');
  await sleep(250);
  const applied = await ev('document.documentElement.dataset.themePreset || ""');
  if (clicked === 'clicked' && applied === name) return 'click';
  await ev('document.documentElement.dataset.themePreset = ' + JSON.stringify(name));
  await sleep(200);
  return clicked === 'clicked' ? 'click-未生效→dataset' : 'no-card→dataset';
}

const PAIRS_BASE = [
  ['body', 'body'],
  ['主行动按钮', '#find-match'],
  ['姓名输入', '#player-name'],
];
const PAIRS_MODAL = [
  ['模态内容 .modal-content', '.modal-overlay:not(.hidden) .modal-content'],
  ['主题预设卡 .theme-card', '#theme-preset-grid .theme-card[data-preset]'],
  ['次级按钮', '#custom-create-room'],       // 页面上不存在时改量 #help-btn（见 groupSet 里的 fallback 分支）
  ['导航 .nav', '.nav'],
  ['模态遮罩 .modal-overlay', '.modal-overlay:not(.hidden)'],
];

function normalizeTransform(v) {
  const s = String(v || '').trim();
  if (!s || s === 'none') return 'none';
  // 单位矩阵 = 没变形（有些浏览器/动画结束后会把 none 归一成 matrix(1,0,0,1,0,0)）
  if (/^matrix\(\s*1[,\s]+0[,\s]+0[,\s]+1[,\s]+0[,\s]+0\s*\)$/.test(s)) return 'none';
  return s;
}

// 不靠 document.fonts.check（字体**是否装了**与字体**栈声明顺序**是两件事，
// 而且无头环境里系统字体可能缺失 → 会假红），改断言声明的栈字符串本身：
// Segoe UI 必须出现，且必须排在泛型族之前。
function stackHasSegoeBeforeGeneric(family) {
  const GENERIC = ['sans-serif', 'serif', 'system-ui', 'monospace', 'cursive', 'fantasy', 'ui-sans-serif', 'ui-serif'];
  const parts = String(family || '').split(',').map((s) => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
  let segoe = -1, generic = -1, genericName = null;
  parts.forEach((p, i) => {
    const low = p.toLowerCase();
    if (segoe < 0 && low.indexOf('segoe ui') === 0) segoe = i;
    if (generic < 0 && GENERIC.includes(low)) { generic = i; genericName = low; }
  });
  return { parts, first: parts[0] || '', segoe, generic, genericName, ok: segoe >= 0 && generic > segoe };
}

const byLabel = (list, label) => list.find((x) => x.label === label) || { found: false, label };

// ---------------------------------------------------------------------------
// 组 set
// ---------------------------------------------------------------------------
async function groupSet() {
  currentPass = 'set';
  await clearStorage();
  await setViewport(1600, 1000, 1, false);
  await reload('light');   // 1600x1000 浅色态

  // ---------- 1. 令牌 ----------
  const tok = await ev('(' + tokensProbe.toString() + ')()');
  console.log('--fluent-* 令牌：计算样式 ' + tok.fromComputed + ' 个，cssRules ' + tok.fromRules + ' 个，合并 ' + tok.tokens.length + ' 个');
  tok.tokens.forEach((t) => console.log('   ' + t.name + ' = ' + t.value));
  if (tok.empty.length) console.log('   值为空的令牌: ' + tok.empty.join(', '));
  check(tok.tokens.length >= 12, '存在 ≥12 个 --fluent-* 令牌且值非空',
    { count: tok.tokens.length, fromComputed: tok.fromComputed, fromRules: tok.fromRules, emptyValues: tok.empty });
  const pa = parseColor(tok.primaryResolved) || parseColor(tok.primaryRaw);
  /* 断言重定（2026-09-25，Phase 6 首页批）：原来这里写死 Fluent 的 #0078d4，
     但默认预设已改为 arena（见 IMPLEMENTATION_PLAN_2026_09_23.md 的 M1）——
     写死颜色等于"默认必须是 Fluent"，与本组的本意（强调色出自令牌层、且主行动用它）不符。
     现在改为：读**当前默认预设在 CSS 里声明的 --primary**，与页面计算值核对；
     声明的值取不到时退化为"属于已声明预设的强调色集合"（仍然拦得住裸值）。 */
  const presetAccent = JSON.parse(await ev(`(function(){
    var root = document.documentElement;
    var preset = root.getAttribute('data-theme-preset') || '';
    var dark = root.classList.contains('theme-dark');
    var want = '', all = [];
    for (var i = 0; i < document.styleSheets.length; i++) {
      var rules; try { rules = document.styleSheets[i].cssRules; } catch (e) { continue; }
      for (var j = 0; j < rules.length; j++) {
        var r = rules[j], sel = r.selectorText || '';
        if (sel.indexOf('data-theme-preset="') < 0) continue;
        var v = (r.style && r.style.getPropertyValue('--primary')) || '';
        if (!v) continue;
        v = v.trim(); all.push(v);
        if (sel.indexOf('data-theme-preset="' + preset + '"') >= 0 && (sel.indexOf('theme-dark') >= 0) === dark) want = v;
      }
    }
    return JSON.stringify({ preset: preset, dark: dark, want: want, all: all,
      got: getComputedStyle(root).getPropertyValue('--primary').trim() });
  })()`));
  const accentOk = presetAccent.want
    ? sameColor(pa, parseColor(presetAccent.want))
    : presetAccent.all.some((v) => sameColor(pa, parseColor(v)));
  check(accentOk, '--primary 出自当前预设 ' + presetAccent.preset + ' 声明的强调色（' + presetAccent.want + '）',
    { raw: tok.primaryRaw, resolved: tok.primaryResolved, declared: presetAccent.want });

  // ---------- 打开设置弹窗（.modal-content / .theme-card 得真的在页面上才量得到） ----------
  const modalOpen = await openSettingsModal();
  console.log('   设置弹窗已打开: ' + modalOpen);
  const raw = await ev('(' + styleProbe.toString() + ')(' + JSON.stringify(PAIRS_BASE.concat(PAIRS_MODAL)) + ')');
  const secondary = byLabel(raw, '次级按钮');
  if (!secondary.found) {   // #custom-create-room 不存在 → 按任务书改量 #help-btn
    const alt = await ev('(' + styleProbe.toString() + ')([["次级按钮","#help-btn"]])');
    const idx = raw.findIndex((x) => x.label === '次级按钮');
    if (idx >= 0) raw[idx] = Object.assign({}, alt[0], { label: '次级按钮', fallback: '#help-btn' });
    console.log('   #custom-create-room 不存在，次级按钮改测 #help-btn');
  }

  // ---------- 2. 字体 ----------
  ['body', '主行动按钮', '姓名输入', '模态内容 .modal-content'].forEach((label) => {
    const el = byLabel(raw, label);
    const family = el.found ? String(el.fontFamily || '') : '';
    console.log('   字体 ' + label + ': ' + (family || '<未找到>'));
    check(el.found && /Segoe UI/i.test(family), label + ' 的 font-family 含 Segoe UI',
      { selector: el.selector, family });
  });
  const bodyEl = byLabel(raw, 'body');
  const bodyStack = stackHasSegoeBeforeGeneric(bodyEl.found ? bodyEl.fontFamily : '');
  check(bodyStack.ok, 'body 字体栈里 Segoe UI 排在泛型（' + (bodyStack.genericName || '?') + '）之前',
    { firstDeclared: bodyStack.first, segoeIndex: bodyStack.segoe, genericIndex: bodyStack.generic, stack: bodyEl.fontFamily });
  check(bodyStack.first !== '' && !/^(times|times new roman|serif)$/i.test(bodyStack.first),
    'body 字体栈首个可用字体不是 Times/serif', { firstDeclared: bodyStack.first });

  // ---------- 3. 圆角档位 ----------
  // 只查这批**明确是本次检查对象**的选择器；999px / 50% 出现在胶囊或头像上不算违规。
  const RADIUS_TARGETS = ['主行动按钮', '次级按钮', '姓名输入', '模态内容 .modal-content', '导航 .nav', '主题预设卡 .theme-card'];
  RADIUS_TARGETS.forEach((label) => {
    const el = byLabel(raw, label);
    if (!el.found) {
      check(false, label + ' 存在（要量它的 border-radius）', { selector: el.selector || null });
      return;
    }
    const corners = el.corners.map((c) => String(c || '').trim());
    const bad = corners.filter((c) => !RADIUS_ALLOWED.includes(c));
    console.log('   borderRadius ' + label + ' (' + el.selector + ') = ' + el.radius + '  [' + corners.join(' | ') + ']');
    check(bad.length === 0, label + ' 的每个圆角都在 Fluent 档位 {' + RADIUS_ALLOWED.join(', ') + '} 内',
      { radius: el.radius, corners, illegal: bad });
  });

  // ---------- 4. 材质（半透明 + backdrop-filter）与定位安全 ----------
  const surfaceCandidates = ['模态遮罩 .modal-overlay', '导航 .nav'];
  let acrylic = null;
  surfaceCandidates.forEach((label) => {
    const el = byLabel(raw, label);
    if (!el.found) { console.log('   材质候选 ' + label + ': 不存在'); return; }
    const bg = parseColor(el.backgroundColor);
    const hasBlur = /blur\(/.test(String(el.backdropFilter || '') + ' ' + String(el.webkitBackdropFilter || ''));
    const translucent = !!bg && bg.a < 1;
    console.log('   材质候选 ' + label + ': backdropFilter=' + el.backdropFilter + ' (webkit=' + el.webkitBackdropFilter +
      ') backgroundColor=' + el.backgroundColor + ' alpha=' + (bg ? r2(bg.a) : 'n/a'));
    if (!acrylic && hasBlur && translucent) acrylic = label;
  });
  check(!!acrylic, '至少一个浮层/表面是「半透明 + backdrop-filter blur」', { candidates: surfaceCandidates, hit: acrylic });

  // ⚠️ 这条不是审美问题：给含 position:fixed 后代的容器加 transform/filter/backdrop-filter，
  // 会让它成为 fixed 后代的【包含块】—— 弹窗遮罩只盖中间一列、浮窗贴不到视口边缘。
  // 本项目为此专门把毛玻璃挪到 .game-container::before 上（见 style.css 的注释）。
  // `.screen.active` = 当前可见的那个 .screen（其余 display:none，量不出问题）；
  // 没有 active 时退到 #start-screen，免得「找不到元素」被误当成「样式违规」。
  const BREAKERS = ['.game-container', '.game-content', '.game-main-container', '.screen.active, #start-screen'];
  const breakRaw = await ev('(' + styleProbe.toString() + ')(' + JSON.stringify(BREAKERS.map((s) => [s, s])) + ')');
  BREAKERS.forEach((sel, i) => {
    const el = breakRaw[i];
    if (!el.found) { check(false, sel + ' 存在（要断言它不含破坏 fixed 定位的写法）', { selector: sel }); return; }
    const tf = normalizeTransform(el.transform);
    const ok = tf === 'none' && String(el.filter).trim() === 'none'
      && String(el.backdropFilter).trim() === 'none' && String(el.webkitBackdropFilter).trim() === 'none';
    console.log('   ' + sel + ': transform=' + el.transform + ' filter=' + el.filter +
      ' backdropFilter=' + el.backdropFilter + ' webkitBackdropFilter=' + el.webkitBackdropFilter);
    check(ok, sel + ' 的 transform/filter/backdrop-filter 均为 none（不破坏 fixed 定位）',
      { transform: tf, filter: el.filter, backdropFilter: el.backdropFilter, webkitBackdropFilter: el.webkitBackdropFilter });
  });

  // ---------- 5. 强调色 ----------
  const fm = byLabel(raw, '主行动按钮');
  const fmBg = parseColor(fm.backgroundColor);
  check(presetAccent.want ? sameColor(fmBg, parseColor(presetAccent.want)) : sameColor(fmBg, ACCENT_OBJ),
    '#find-match 的计算底色 = 当前预设的强调色',
    { backgroundColor: fm.backgroundColor, expected: presetAccent.want || ACCENT_RGB });
  const fmFg = parseColor(fm.color);
  // ⚠️ 底色必须是不透明的「实心按钮色」才谈得上对比度：旧实现给按钮的是
  // `background: var(--primary-gradient)`（颜色落在 background-image 里），
  // 于是 `backgroundColor` 算出 `rgba(0,0,0,0)` —— 透明底与白字比出来 21:1，
  // 白白 PASS。这里显式把「底色不透明」并入判据（背景图是否为 none 另有单独断言）。
  const fmBgSolid = !!fmBg && fmBg.a > 0.95;
  const ratio = (fmBgSolid && fmFg) ? contrastRatio(fmBg, fmFg) : 0;
  console.log('   #find-match 文字 ' + fm.color + ' vs 底色 ' + fm.backgroundColor +
    '（底色不透明=' + fmBgSolid + '）对比度 = ' + r2(ratio) + ':1');
  check(fmBgSolid && ratio >= CONTRAST_MIN, '#find-match 文字与实心底色对比度 ≥ ' + CONTRAST_MIN + ':1',
    { ratio: r2(ratio), fg: fm.color, bg: fm.backgroundColor, bgOpaque: fmBgSolid });
  check(String(fm.backgroundImage).trim() === 'none', '#find-match 没有残留 linear-gradient 背景图（Fluent 实心按钮 = 纯色）',
    { backgroundImage: fm.backgroundImage });

  // ---------- 6. 首页标题不再是渐变文字 ----------
  const h1raw = await ev('(' + styleProbe.toString() + ')([["首页主标题","#start-screen h1"]])');
  const h1 = h1raw[0];
  const h1c = parseColor(h1.color);
  const h1f = parseColor(h1.webkitFill);
  console.log('   #start-screen h1 color=' + h1.color + ' -webkit-text-fill-color=' + h1.webkitFill +
    ' backgroundImage=' + h1.backgroundImage);
  check(h1.found && !!h1c && h1c.a > 0, '#start-screen h1 的 color 不是 transparent', { color: h1.color, fill: h1.webkitFill });
  check(h1.found && !!h1f && h1f.a > 0, '#start-screen h1 的 -webkit-text-fill-color 不是 transparent', { fill: h1.webkitFill });

  await closeOverlays();
}

// ---------------------------------------------------------------------------
// 组 presets
// ---------------------------------------------------------------------------
// 「同规范」签名 = 字体 + 三处圆角 + 三个间距令牌；颜色类一律不进签名（允许不同）。
const styleSig = (list, vars) => [
  (byLabel(list, 'body').fontFamily || ''),
  (byLabel(list, '主行动按钮').radius || ''),
  (byLabel(list, '姓名输入').radius || ''),
  (byLabel(list, '导航 .nav').radius || ''),
  vars['--fluent-space-2'] || '', vars['--fluent-space-3'] || '', vars['--fluent-space-4'] || '',
].join(' | ');

async function measureSignature() {
  const list = await ev('(' + styleProbe.toString() +
    ')([["body","body"],["主行动按钮","#find-match"],["姓名输入","#player-name"],["导航 .nav",".nav"]])');
  const vars = await ev('(' + varsProbe.toString() + ')(' + JSON.stringify(SPACE_TOKENS) + ')');
  return { list, vars, sig: styleSig(list, vars) };
}

async function groupPresets() {
  currentPass = 'presets';
  await setViewport(1600, 1000, 1, false);

  // ---------- 8. 默认预设：必须是「已声明的一个预设」，不是某个写死的名字 ----------
  /* 断言重定（2026-09-27，首页 C 化批）：原来写死 `=== 'fluent'`。
     本意是"清空 localStorage 后落到一个**已声明**的默认预设"，不是"默认必须是 fluent" ——
     而 M1 已经把默认改成 arena（见 docs/IMPLEMENTATION_PLAN_2026_09_23.md §6 与
     docs/PHASE6_HOME_2026_09_25.md §1），这条从 Phase 6 起就一直是红的
     （presets 组不是每次改前端都会复跑，所以一直没人撞上）。
     现在断言那个**不变量**：默认落在 PRESETS 名单里、html 上有 data-theme-preset、
     且该预设的强调色真的解析得出来（漏了 fallback / 落到未知名字 / 预设块选择器写错都会红）。 */
  await clearStorage();
  await reload('light');
  const thDef = await ev('(' + themeProbe.toString() + ')()');
  const defName = String(thDef.datasetThemePreset || '');
  console.log('   默认预设（清空 localStorage 后）= ' + JSON.stringify(defName));
  check(PRESETS.includes(defName), '清空 localStorage 后默认预设是已声明的预设之一（' + PRESETS.join('/') + '）',
    { datasetThemePreset: thDef.datasetThemePreset, htmlClass: thDef.htmlClass, localStoragePreset: thDef.localStoragePreset });
  const defPrimary = String(await ev(
    "(function(){ return getComputedStyle(document.documentElement).getPropertyValue('--primary').trim(); })()"));
  check(!!defPrimary, '默认预设下 --primary 有解析值（预设块命中 html）',
    { preset: defName, primary: defPrimary });

  // ---------- 7. 8 个预设 + 两分组 ----------
  const st = await ev('(' + presetStructureProbe.toString() + ')()');
  if (!st.grid) {
    check(false, '#theme-preset-grid 存在', { grid: false });
  } else {
    console.log('   预设卡: ' + JSON.stringify(st.gridPresets));
    console.log('   网格直接子节点: ' + (st.childShape.join(', ') || '无'));
    st.children.forEach((c, i) => console.log('     子[' + i + '] ' + c.tag + '.' + c.cls +
      ' isCard=' + c.isCard + ' 卡=' + JSON.stringify(c.presets)));
    const missing = PRESETS.filter((p) => !st.gridPresets.includes(p));
    check(missing.length === 0, '预设区含 8 个 data-preset（fluent/deep/lava/cyber/dusk/aurora/classic/arena）',
      { found: st.gridPresets, missing });
    // 分组结构：不猜标签名/类名，只要求「直接子节点里有两个装卡的容器」这一个可判定的形状。
    // 当前 DOM 若是平的（8 张卡直接挂在 #theme-preset-grid 下），这里就是 FAIL —— 正是要抓的。
    check(st.groupCount >= 2, '预设区存在两个分组容器（默认组 + 旧风格组）',
      { groupCount: st.groupCount, groups: st.groups, ungroupedCards: st.ungroupedCards, childShape: st.childShape });
    if (st.groupCount >= 2) {
      const flat = st.groups.map((g) => g.filter(Boolean));
      const fluentIdx = flat.findIndex((g) => g.includes('fluent'));
      const defaultGroupClean = fluentIdx >= 0 && flat[fluentIdx].filter((p) => LEGACY_PRESETS.includes(p)).length === 0;
      const legacyGroupOk = fluentIdx >= 0
        && flat.some((g, i) => i !== fluentIdx && LEGACY_PRESETS.every((p) => g.includes(p)));
      check(defaultGroupClean, '默认组只含新式预设（fluent/arena），不含旧 6 个', { groups: st.groups, fluentGroupIndex: fluentIdx });
      check(legacyGroupOk, '另一组含其余 6 个旧预设', { groups: st.groups });
    }
  }

  // ---------- 9/10. 8 个预设同规范 + 强调色两两不同 ----------
  const opened = await openSettingsModal();
  console.log('   设置弹窗已打开: ' + opened);
  const rows = [];
  const primaries = {};
  const vias = {};
  for (const name of PRESETS) {
    vias[name] = await applyPreset(name);
    const sig = await measureSignature();
    const pv = await ev('(' + varsProbe.toString() + ')(["--primary"])');
    primaries[name] = pv['--primary'];
    rows.push({
      preset: name, via: vias[name], sig: sig.sig, font: sig.list[0].fontFamily,
      radius: [sig.list[1].radius, sig.list[2].radius, sig.list[3].radius], space: sig.vars,
    });
    console.log('   ' + name.padEnd(8) + ' via=' + vias[name] + ' --primary=' + pv['--primary'] +
      ' radius=' + [sig.list[1].radius, sig.list[2].radius, sig.list[3].radius].join('/') +
      ' space=' + SPACE_TOKENS.map((t) => sig.vars[t]).join('/'));
  }
  /* 断言重定（2026-09-27，1:1 复刻 demo 批）：原来要求"8 个预设的字体/圆角/间距完全一致"。
     那是在 arena 只是"另一套配色"时定的；现在 arena 是**一整套设计**（示意稿 C/V 原样：
     入口/主行动 12px、面板 14px），形状必然与 Fluent 那 7 个不同。
     新的不变量：**除 arena 外的 7 个预设仍然完全一致**，且 arena 自己内部自洽
     （字体与间距令牌与其它预设相同，只有圆角档不同）。 */
  const legacySigs = new Set(rows.filter((r) => r.preset !== ARENA_PRESET).map((r) => r.sig));
  const arenaRows = rows.filter((r) => r.preset === ARENA_PRESET);
  const arenaKey = (r) => [r.font, r.radius.join('/'), SPACE_TOKENS.map((t) => r.space[t]).join('/')].join(' | ');
  const arenaSig = new Set(arenaRows.map(arenaKey));
  console.log('   规范签名不同取值数：除 arena 外 = ' + legacySigs.size + '，arena 自身 = ' + arenaSig.size);
  console.log('   arena 的形状签名 = ' + [...arenaSig].join(' , '));
  check(legacySigs.size === 1, '除 arena 外的 7 个预设字体/圆角/间距完全一致（只有颜色允许不同）',
    { distinctSignatures: legacySigs.size, signatures: [...legacySigs], radius: rows.map((r) => r.radius) });
  check(arenaSig.size === 1, 'arena 预设自身形状自洽（字体 + 圆角 + 间距只有一个取值）',
    { arenaSignatures: [...arenaSig], arenaRadius: arenaRows.map((r) => r.radius) });
  const distinctPrimaries = new Set(Object.values(primaries).map((v) => String(v).trim()));
  check(distinctPrimaries.size === PRESETS.length, '8 个预设的 --primary 两两不同',
    { distinct: distinctPrimaries.size, map: primaries });

  // ---------- 11. 8 预设 × 明暗两态的正文对比度 ----------
  // 明暗态走「清掉 theme 键 + 系统偏好 + reload」（真实路径）；
  // 预设在同一态内点卡片切换即可（CSS 靠 html[data-theme-preset] 生效，不用重新加载）。
  for (const mode of ['light', 'dark']) {
    await ev('(function(){ try { localStorage.removeItem("theme"); } catch(e){} return 1; })()');
    await reload(mode);
    const th = await ev('(' + themeProbe.toString() + ')()');
    console.log('   [' + mode + '] 跟随系统: html.class=' + JSON.stringify(th.htmlClass) +
      ' prefersDark=' + th.prefersDark + ' layerBg=' + th.layerBg);
    await openSettingsModal();
    for (const name of PRESETS) {
      await applyPreset(name);
      const t = await ev('(' + themeProbe.toString() + ')()');
      const bg = pickPageBg(t);
      const fg = parseColor(t.bodyColor);
      const cr = (fg && bg) ? contrastRatio(fg, bg.color) : 0;
      console.log('     ' + mode + '/' + name.padEnd(8) + ' 文字=' + t.bodyColor +
        ' 底=' + (bg ? bg.source : '<无>') + ' 对比度=' + r2(cr) + ':1');
      check(!!bg && !!fg && cr >= CONTRAST_MIN, mode + ' 态 + ' + name + ' 预设：正文色与页面底色对比度 ≥ ' + CONTRAST_MIN + ':1',
        { ratio: r2(cr), fg: t.bodyColor, bg: bg ? bg.color : null, bgSource: bg ? bg.source : null,
          layerBg: t.layerBg, bodyBgColor: t.bodyBgColor });
    }
  }
  await closeOverlays();
}

// ---------------------------------------------------------------------------
// 组 dark
// ---------------------------------------------------------------------------
async function groupDark() {
  currentPass = 'dark';
  await setViewport(1600, 1000, 1, false);

  /* 断言重定（2026-09-27，1:1 复刻 demo 批）。
     原来这一组断言的是「跟随系统」：`清空 localStorage + 系统浅色 → 必须没有深色标记`。
     用户要求一比一复刻示意稿 C/V —— 它们都是**暗色设计**，所以默认（没显式选过）
     改成深色，系统的明暗偏好不再决定首屏。这一组现在断言新契约的三件事：
       ① 没有显式选择时**默认深色**（系统浅色/深色都一样）；
       ② 用户显式选浅色 → 浅色，且**跨重载、跨系统偏好**都保持（显式选择优先）；
       ③ 首帧不闪：定 `theme-dark` 的引导脚本仍在 <head> 里、且排在样式表之前。 */
  await clearStorage();
  await reload('light');
  let th = await ev('(' + themeProbe.toString() + ')()');
  check(!!darkMarker(th), '清空 localStorage + 系统浅色 → 默认深色（示意稿 C/V 是暗色设计）',
    { htmlClass: th.htmlClass, prefersDark: th.prefersDark, localStorageTheme: th.localStorageTheme });
  let bg = pickPageBg(th);
  check(!!bg && relLum(bg.color) < 0.35, '默认深色下页面底色确实是深色（相对亮度 < 0.35）',
    { source: bg ? bg.source : null, luminance: bg ? r2(relLum(bg.color)) : null, layerBg: th.layerBg });

  await clearStorage();
  await reload('dark');
  th = await ev('(' + themeProbe.toString() + ')()');
  check(!!darkMarker(th), '系统偏好 dark → 仍是深色（与默认一致，不冲突）',
    { htmlClass: th.htmlClass, prefersDark: th.prefersDark });

  // ---------- 用户显式选择优先：点 #toggle-theme（真实用户路径） ----------
  await clearStorage();
  await reload('light');                    // 默认深色
  await ev('(function(){ var a=document.getElementById("toggle-theme"); if(a) a.click(); return 1; })()');
  await sleep(300);
  const afterClick = await ev('(' + themeProbe.toString() + ')()');
  const pathUsed = afterClick.localStorageTheme ? 'click #toggle-theme' : 'localStorage.setItem';
  console.log('   点击 #toggle-theme 后: ' + JSON.stringify({ marker: darkMarker(afterClick),
    htmlClass: afterClick.htmlClass, localStorageTheme: afterClick.localStorageTheme }));
  check(!darkMarker(afterClick) && String(afterClick.localStorageTheme) === 'light',
    '默认深色下点一次明暗切换 → 变成显式浅色',
    { path: pathUsed, htmlClass: afterClick.htmlClass, localStorageTheme: afterClick.localStorageTheme });

  await setMedia('dark');                   // 系统偏好切到深色
  await send('Page.navigate', { url: APP }); // ⚠️ 这里**不清** localStorage
  await waitFor(async () => await ev('document.readyState === "complete"'), 25000, '页面加载');
  await sleep(800);
  const th2 = await ev('(' + themeProbe.toString() + ')()');
  const bg2 = pickPageBg(th2);
  check(!darkMarker(th2), '显式选浅色后，系统偏好为 dark 时仍是浅色（用户选择优先）',
    { path: pathUsed, htmlClass: th2.htmlClass, prefersDark: th2.prefersDark, localStorageTheme: th2.localStorageTheme });
  check(!!bg2 && relLum(bg2.color) > 0.65, '显式浅色下底色确实是浅色（相对亮度 > 0.65）',
    { source: bg2 ? bg2.source : null, luminance: bg2 ? r2(relLum(bg2.color)) : null });

  // ---------- 15. 无闪烁：引导脚本必须在 <head> 里、且排在样式表之前 ----------
  const heads = th2.headChildren.filter((h) => h.kind === 'script'
    && /theme-dark|prefers-color-scheme|data-theme|themePreset|localStorage\.getItem\(\s*['"]theme/.test(h.text || ''));
  const sheetIdx = th2.headChildren.findIndex((h) => h.kind === 'stylesheet');
  console.log('   head 子节点: ' + th2.headChildren.map((h) => h.idx + ':' + h.tag + '(' + h.kind + ')').join(' '));
  console.log('   body 里含主题引导逻辑的内联脚本数: ' + th2.bodyBootstrapScripts);
  heads.forEach((h) => console.log('   head 引导脚本[' + h.idx + ']: ' +
    (h.src || h.text.slice(0, 120).replace(/\s+/g, ' '))));
  check(heads.length > 0, '主题引导脚本在 <head> 内（先于任何 body 内容执行 → 无「先浅后深」闪烁）',
    { headBootstrapScripts: heads.map((h) => ({ idx: h.idx, src: h.src, snippet: h.text.slice(0, 80) })),
      headChildren: th2.headChildren.map((h) => h.idx + ':' + h.tag + '(' + h.kind + ')'),
      bodyBootstrapScripts: th2.bodyBootstrapScripts, firstStylesheetIdx: sheetIdx });
  check(heads.some((h) => h.idx < sheetIdx), '引导脚本排在 style.css 之前（首帧就是对的底色）',
    { headIdxs: heads.map((h) => h.idx), firstStylesheetIdx: sheetIdx });
}

// ---------------------------------------------------------------------------
// 组 shots
// ---------------------------------------------------------------------------
async function groupShots() {
  currentPass = 'shots';
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  await clearStorage();     // 截图统一用「默认预设 + 默认明暗」（2026-09-27 起默认是深色）
  await sleep(50);
  const shots = [];
  for (const [label, w, h, dsf, mobile] of SHOT_VIEWPORTS) {
    await setViewport(w, h, dsf, mobile);
    // 先切回首页再 reload：跑完前面的组可能停在别的屏（弹窗/对局）；
    // reload 也能复位，但显式 switchScreen 更贴近「用户回到首页」的路径。
    await ev('(function(){ try { switchScreen(document.getElementById("start-screen")); } catch(e){} return 1; })()');
    await send('Page.navigate', { url: APP });
    await waitFor(async () => await ev('document.getElementById("start-screen").classList.contains("active")'), 25000, label + ' 首页激活');
    await ev('window.scrollTo(0,0)');
    // 等动画稳定：切屏/入场动画（fadeIn 0.6s 等）跑完再截，免得截到半透明的中间帧。
    // ⚠️ 只等**有限次**的动画：粒子气泡等是 `infinite` 循环动画，永远不会停
    // （实测只数 running 会等到超时，每档白等 6 秒还刷一条误导性的警告）。
    // 超时不判失败，只提示「可能截到动画中帧」。
    await waitFor(async () => await ev('(function(){try{' +
      'return document.getAnimations().filter(function(a){' +
      'var it=a.effect&&a.effect.getTiming?a.effect.getTiming().iterations:1;' +
      'return a.playState==="running" && it!==Infinity;}).length===0;' +
      '}catch(e){return true;}})()'), 6000, label + ' 动画稳定')
      .catch(() => console.log('   ' + label + ': 有限次动画未在 6 秒内跑完，仍截图'));
    await sleep(300);
    const home = await ev('(' + homeProbe.toString() + ')()');
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    const file = path.join(SHOTS_DIR, label + '.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    const size = fs.statSync(file).size;
    shots.push({ label, file, size });
    console.log('   截图 ' + label + ' -> ' + file + ' (' + size + ' 字节) dsf=' + dsf +
      ' 可见屏=' + JSON.stringify(home.visibleScreens) + ' 运行中动画=' + home.runningAnimations);
    check(home.startActive && size > 0, label + ' 截图已写入且停在首页',
      { file, size, startActive: home.startActive, scrollY: home.scrollY });
  }
  console.log(NL + '截图 ' + shots.length + ' 张 -> ' + SHOTS_DIR);
  shots.forEach((s) => console.log('  ' + s.file));
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
try {
  preClean();
  fs.mkdirSync(PROFILE, { recursive: true });
  browser = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = pickPage(list);
      if (target) break;
    } catch (e) { /* 浏览器还在起 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口 ' + PORT + '（有残留进程？换个 --port）');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  const jsProblems = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
  };

  await send('Page.enable');
  await send('Runtime.enable');
  // ⚠️ 必须禁用缓存：本项目静态资源带 asset_v 戳，但开发中直接改 style.css 时戳不变
  // → 持久 profile 会命中旧 CSS，表现为「改了没生效」的假绿/假红。
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 25000, '首次加载');

  console.log('目标: ' + APP + NL + '浏览器: ' + BROWSER + NL +
    '分组: ' + (ONLY || GROUPS.join(',')) + '   截图目录: ' + SHOTS_DIR + NL);

  if (!ONLY || ONLY === 'set') await groupSet();
  if (!ONLY || ONLY === 'presets') await groupPresets();
  if (!ONLY || ONLY === 'dark') await groupDark();
  if (!ONLY || ONLY === 'shots') await groupShots();

  currentPass = 'page';
  check(jsProblems.length === 0, '页面无 JS 异常/console.error', jsProblems.slice(0, 8));
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
  if (/等待超时|无法连接/.test(err.message)) {
    console.error('提示：确认服务端已起、且放行该来源（CORS_ORIGINS=http://127.0.0.1:<端口>），端口别用 5060/5061。');
  }
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  const secs = r2((Date.now() - t0) / 1000);
  console.log(NL + '耗时 ' + secs + ' 秒');
  console.log(problems.length
    ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL)
    : '结果: 全部通过');
  process.exit(problems.length ? 1 : 0);
}
