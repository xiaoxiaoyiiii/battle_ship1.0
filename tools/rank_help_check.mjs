#!/usr/bin/env node
/**
 * 帮助页「段位与排位」块回归检查（无头 Edge + CDP，全部断言真实 DOM）
 *
 * 需求（作者原话）：「把段位介绍写进帮助里 —— 点帮助能看到不同段位的图标和名字长什么样，
 * 包括排位赛的规则是怎么计分的」。
 *
 * 覆盖七块（对应任务书里的 7 条）：
 *   1. **点真实入口**（`#help-btn`，不是直接调渲染函数）→ `#help-rank-section` 出现且可见；
 *   2. `#help-rank-tiers` 正好 9 行，每行 `.rank-icon` 的 `data-tier` 与 `/api/rank_constants`
 *      下发的 9 个段位 id **逐一对应**，段位名与 `tier_name` 逐字相同；
 *      9 枚 SVG **真的画出来了**（`getBoundingClientRect().width > 0`，且不是空 `<svg>`）；
 *   3. 两张计分表有行，且**每一格都与 `/api/rank_constants` 的 `scoring` 逐项一致**
 *      （标签 / 分值 / 条件三列都比）—— 工具里**不写死任何数字**，否则只是在验证
 *      "帮助和工具手抄的一致"；
 *   4. 高段位的图标在帮助页里**真的**更重：用真实光栅化数像素（不是数 `<path>` 的条数），
 *      同时断言最低段位那行**确实轻** —— 两边都断言才不是假绿；
 *   5. 拉不到接口时（CDP 注入 fetch 拦截）→ `#help-rank-error` 可见，且
 *      `#help-rank-section` **不清空**（保留上一帧）；
 *   6. 320×568 / 390×844 / 1600×1000 三个视口下帮助弹窗不横向溢出、段位行不被压住；
 *   7. 全程零 JS 异常 / 零 console.error。
 *
 * 用法：
 *   node tools/rank_help_check.mjs --url http://127.0.0.1:5041/ [--db <隔离库>] [--shot out.png]
 *
 * ⚠️ 只在**隔离库 + 本地服务**上用（会注册一个 `rankhelp_*` 账号并写段位分）。
 *    默认库 `<repo>/.tmp/rank_help.db`，必须与服务端 `BATTLESHIP_DB_PATH` 指向同一份。
 * ⚠️ 登录走 Node 侧 fetch + `redirect: 'manual'` 拿 Set-Cookie，再把 Cookie 头交给
 *    `Network.setCookie` —— 比在无头浏览器里填表单稳（本项目踩过"页面表单填了但没提交"）。
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5041/').replace(/\/?$/, '/');
const SHOT = argOf('--shot', '');
const PORT = 9362;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const ROOT = path.resolve(HERE, '..');
const TMP = path.join(ROOT, '.tmp');
const DB = argOf('--db', path.join(TMP, 'rank_help.db'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(TMP, 'rank_help_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过段位帮助检查'); process.exit(0); }
fs.mkdirSync(TMP, { recursive: true });

// ---------- 预清理：残留的无头 Edge 会占着调试端口 + 锁住 profile ----------
// （不清理的话新浏览器**静默起不来**，工具连上的是上一轮的旧实例 → 查不出所以然的假红。）
try {
  spawnSync('powershell', ['-NoProfile', '-Command',
    'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
    'Where-Object { $_.CommandLine -like \'*rank_help_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'],
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没有残留就够了 */ }

const SUFFIX = String(Date.now()).slice(-6);
const PW = 'rankhelp123456';
const ME = 'rankhelp_' + SUFFIX;

let browser = null, ws = null, seq = 0;
const pending = new Map();
const problems = [];
const passes = [];
const jsProblems = [];

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
  if (r.exceptionDetails) throw new Error('页面异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeout) {
    try { last = await fn(); if (last) return last; } catch (e) { last = 'err:' + e.message; }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label + '  (最后=' + JSON.stringify(last) + ')');
}

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (ok) passes.push(label); else problems.push(label);
}

// ---------- 隔离库助手：造账号 + 设段位分（唯一"造数据"途径，没有 HTTP 接口能改分） ----------
const DB_HELPER = path.join(TMP, 'rank_help_db.py');
fs.writeFileSync(DB_HELPER, String.raw`
# -*- coding: utf-8 -*-
"""rank_help_check.mjs 用的隔离库助手：造号 / 设段位分。只动 BATTLESHIP_DB_PATH 指的那个库。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
from werkzeug.security import generate_password_hash

cmd = sys.argv[1]
db.init_db()

def ensure(username):
    user = db.get_user(username=username)
    if not user:
        uid = db.create_user(username, generate_password_hash('rankhelp123456'))
        user = db.get_user(uid=uid)
    return user

if cmd == 'seed':
    u = ensure(sys.argv[2])
    if not u:
        print(json.dumps({'ok': False})); sys.exit(1)
    db.set_rank_points(u['id'], int(sys.argv[3]))
    print(json.dumps({'ok': True, 'username': u['username'], 'points': int(sys.argv[3])}))
else:
    print(json.dumps({'ok': False, 'error': 'unknown cmd'})); sys.exit(1)
`);

function dbHelper(args) {
  // ⚠️ spawnSync + 参数数组，**不要** execSync 拼字符串：Windows 走 cmd.exe，
  //    参数里的引号/方括号会被 shell 吃掉。
  const r = spawnSync('python', [DB_HELPER].concat(args), {
    cwd: ROOT, encoding: 'utf8', timeout: 90000,
    env: { ...process.env, BATTLESHIP_DB_PATH: DB, PYTHONIOENCODING: 'utf-8' },
  });
  const out = String(r.stdout || '');
  const line = out.trim().split(/\r?\n/).filter((l) => l.trim().startsWith('{')).pop();
  if (!line) throw new Error('隔离库助手失败: ' + String(r.stderr || r.error || '').slice(-400));
  return JSON.parse(line);
}

/** Node 侧 get/post（拿服务端权威数据与 cookie）。 */
async function apiGet(url) {
  const r = await fetch(url, { headers: { 'Accept': 'application/json' } });
  const text = await r.text();
  let json = null;
  try { json = JSON.parse(text); } catch (e) { /* 非 JSON 也给回文本 */ }
  return { status: r.status, json, text };
}

async function loginAndGetCookie() {
  const body = new URLSearchParams({ username: ME, password: PW }).toString();
  const r = await fetch(APP + 'login', {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  const raw = r.headers.getSetCookie ? r.headers.getSetCookie() : [r.headers.get('set-cookie')].filter(Boolean);
  const session = raw.map((c) => String(c).split(';')[0]).filter((c) => c.indexOf('session=') === 0);
  return { status: r.status, location: r.headers.get('location'), cookie: session.join('; ') };
}

// ---------- 页面侧探针 ----------
const RECT = 'function R(e){var b=e.getBoundingClientRect();return {x:Math.round(b.left),y:Math.round(b.top),w:Math.round(b.width),h:Math.round(b.height)};}';

/** 「这块东西有没有被别的元素盖住」——矩形内多点采样 elementFromPoint。 */
const OCCLUSION_PROBE = (sel) => `(function(){
  ${RECT}
  var el = document.querySelector(${JSON.stringify(sel)});
  if (!el) return { present: false };
  var cs = getComputedStyle(el);
  if (cs.display === 'none' || cs.visibility === 'hidden') return { present: false, hidden: true };
  var r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return { present: false, zero: true };
  var samples = 0, occluded = 0, worst = null;
  for (var i = 1; i <= 3; i++) for (var j = 1; j <= 3; j++) {
    var x = r.left + r.width * i / 4, y = r.top + r.height * j / 4;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
    samples++;
    var top = document.elementFromPoint(x, y);
    var hit = top === el || (top && el.contains(top)) || (top && top.contains(el));
    if (!hit) { occluded++; if (!worst) worst = { tag: top ? top.tagName : null, id: top ? top.id : null,
      cls: top ? String(top.className).slice(0, 60) : null, x: Math.round(x), y: Math.round(y) }; }
  }
  return { present: true, samples: samples, occluded: occluded, worst: worst, rect: R(el) };
})()`;

/** 帮助块的整体探针：段位行 / 图标 / 计分表都从这里读。 */
const HELP_PROBE = `(function(){
  var sec = document.getElementById('help-rank-section');
  var out = { section: !!sec, visible: false, hiddenAttr: false };
  if (!sec) return out;
  var cs = getComputedStyle(sec);
  var r = sec.getBoundingClientRect();
  out.hiddenAttr = sec.hidden === true;
  out.visible = cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  out.sectionRect = { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  var err = document.getElementById('help-rank-error');
  out.error = { present: !!err, hidden: err ? (err.hidden === true || getComputedStyle(err).display === 'none') : true,
                text: err ? (err.textContent || '').trim() : '' };
  var rows = [].slice.call(document.querySelectorAll('#help-rank-tiers .help-rank-tier'));
  out.tierCount = rows.length;
  out.tiers = rows.map(function (row) {
    var svg = row.querySelector('svg.rank-icon');
    var b = svg ? svg.getBoundingClientRect() : null;
    return {
      tier: row.getAttribute('data-tier'),
      name: (row.querySelector('.help-rank-name') || {}).textContent || '',
      meta: (row.querySelector('.help-rank-meta') || {}).textContent || '',
      unlock: (row.querySelector('.help-rank-unlock') || {}).textContent || '',
      note: (row.querySelector('.help-rank-note') || {}).textContent || '',
      icon: svg ? { w: b.width, h: b.height, color: getComputedStyle(svg).color, filter: getComputedStyle(svg).filter,
                    shapes: svg.querySelectorAll('path,circle,rect,line,polygon,polyline,ellipse').length,
                    box: { x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) } } : null,
      rowClientW: row.clientWidth, rowScrollW: row.scrollWidth,
    };
  });
  var cellText = function (el) { var n = el.querySelector('.help-rank-score-value'); return n ? (n.textContent || '').trim() : null; };
  var condText = function (el) { var n = el.querySelector('.help-rank-score-cond'); return n ? (n.textContent || '').trim() : null; };
  var lblText = function (el) { var n = el.querySelector('.help-rank-score-label'); return n ? (n.textContent || '').trim() : null; };
  var read = function (id) {
    var box = document.getElementById(id);
    if (!box) return { present: false, rows: [] };
    var rows = [].slice.call(box.querySelectorAll('.help-rank-score-row'));
    return { present: true, rows: rows.map(function (r) { return { label: lblText(r), value: cellText(r), condition: condText(r) }; }) };
  };
  out.win = read('help-rank-scoring-win');
  out.lose = read('help-rank-scoring-lose');
  // 只取**可见**文案：把 [hidden] / display:none 的子节点剪掉再读 textContent。
  // （直接读 textContent 会把"已经收起来的占位句"也算进去，断言会假红。）
  var visibleText = function (el) {
    if (!el) return '';
    var clone = el.cloneNode(true);
    [].slice.call(clone.querySelectorAll('[hidden], .hidden')).forEach(function (n) {
      if (n.parentNode) n.parentNode.removeChild(n);
    });
    return (clone.textContent || '').replace(/\s+/g, ' ').trim();
  };
  out.scoringPlaceholder = visibleText(document.getElementById('help-rank-scoring'));
  return out;
})()`;

/**
 * 图标"重量"的真实光栅化：把 SVG 里的 path/circle/rect 采样成多边形，
 * 在 canvas 上按与页面**相同**的 currentColor 描边 + 填充，数有多少个像素被画到。
 *
 * ⚠️ 为什么不用 `path` 条数 / `viewBox`：那只是"文件里写了几个元素"，
 *    与"屏幕上看起来多重"是两码事（本项目吃过"加了 class 被通用规则盖掉"的假绿）。
 *    这里数的是**真实像素**，两端都断言（最高段位重、最低段位轻）才不是假绿。
 */
const ICON_PIXEL_PROBE = `(function(){
  var SIZE = 72;
  function poly(points, n) {
    var d = '';
    for (var i = 0; i < n; i++) d += (i ? 'L' : 'M') + points[i].x.toFixed(2) + ' ' + points[i].y.toFixed(2);
    return d + 'Z';
  }
  function strokePoly(cx, cy, r, w) {
    var pts = [], n = 12;
    for (var i = 0; i < n; i++) { var a = i / n * Math.PI * 2; pts.push({ x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r }); }
    var o = [];
    for (var j = 0; j < n; j++) {
      var p = pts[j], q = pts[(j + 1) % n];
      var dx = q.x - p.x, dy = q.y - p.y, len = Math.hypot(dx, dy) || 1;
      var nx = -dy / len * w, ny = dx / len * w;
      o.push({ x: p.x + nx, y: p.y + ny });
    }
    for (var k = n - 1; k >= 0; k--) {
      var p2 = pts[k], q2 = pts[(k + 1) % n];
      var dx2 = q2.x - p2.x, dy2 = q2.y - p2.y, len2 = Math.hypot(dx2, dy2) || 1;
      var nx2 = -dy2 / len2 * w, ny2 = dx2 / len2 * w;
      o.push({ x: p2.x - nx2, y: p2.y - ny2 });
    }
    return poly(o, o.length);
  }
  function rectOutline(x, y, w, h, rx, sw) {
    if (!(rx > 0)) return 'M' + x + ' ' + y + 'H' + (x + w) + 'V' + (y + h) + 'H' + x + 'Z';
    return 'M' + (x + rx) + ' ' + y + 'H' + (x + w - rx) + 'A' + rx + ' ' + rx + ' 0 0 1 ' + (x + w) + ' ' + (y + rx) +
      'V' + (y + h - rx) + 'A' + rx + ' ' + rx + ' 0 0 1 ' + (x + w - rx) + ' ' + (y + h) + 'H' + (x + rx) +
      'A' + rx + ' ' + rx + ' 0 0 1 ' + x + ' ' + (y + h - rx) + 'V' + (y + rx) + 'A' + rx + ' ' + rx + ' 0 0 1 ' + (x + rx) + ' ' + y + 'Z';
  }
  function raster(svg) {
    var cv = document.createElement('canvas');
    cv.width = SIZE; cv.height = SIZE;
    var ctx = cv.getContext('2d');
    if (!ctx) return -1;
    var scaleX = SIZE / 24, scaleY = SIZE / 24;
    ctx.setTransform(scaleX, 0, 0, scaleY, 0, 0);      // viewBox 是 0 0 24 24
    ctx.fillStyle = ctx.strokeStyle = getComputedStyle(svg).color;
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    var shapes = svg.querySelectorAll('path,circle,rect,line,polygon,polyline,ellipse');
    for (var i = 0; i < shapes.length; i++) {
      var sh = shapes[i], cs = getComputedStyle(sh);
      var sw = parseFloat(cs.strokeWidth); if (!(sw > 0)) sw = 1.5;
      var fill = sh.getAttribute('fill'), stroke = sh.getAttribute('stroke');
      var tag = sh.tagName.toLowerCase();
      if (sh.getAttribute('stroke-dasharray')) sw = Math.min(sw, 1.2);   // 齿轮虚线圈：按细线算，别把重量算爆
      if (tag === 'path') {
        try {
          var len = sh.getTotalLength();
          if (len > 0) { ctx.lineWidth = sw; ctx.beginPath(); ctx.setLineDash([]); ctx.stroke(new Path2D(sh.getAttribute('d'))); }
        } catch (e) { /* 个别浏览器不支持 Path2D(d)，那就按下面 fill 规则处理 */ }
        if (fill !== 'none') { try { ctx.beginPath(); ctx.fill(new Path2D(sh.getAttribute('d'))); } catch (e2) { /* ignore */ } }
      } else if (tag === 'circle') {
        var ccx = parseFloat(sh.getAttribute('cx')), ccy = parseFloat(sh.getAttribute('cy')), cr = parseFloat(sh.getAttribute('r'));
        ctx.beginPath();
        if (stroke !== 'none') ctx.fill(new Path2D(strokePoly(ccx, ccy, cr, sw / 2)));
        if (fill !== 'none') { ctx.beginPath(); ctx.arc(ccx, ccy, cr, 0, Math.PI * 2); ctx.fill(); }
      } else if (tag === 'rect') {
        var rx0 = parseFloat(sh.getAttribute('x')), ry0 = parseFloat(sh.getAttribute('y'));
        var rw = parseFloat(sh.getAttribute('width')), rh = parseFloat(sh.getAttribute('height'));
        var rr = parseFloat(sh.getAttribute('rx')) || 0;
        ctx.beginPath();
        if (stroke !== 'none') ctx.fill(new Path2D(rectOutline(rx0, ry0, rw, rh, rr, sw)));
        if (fill !== 'none') ctx.fill(new Path2D(rectOutline(rx0, ry0, rw, rh, rr, 0)));
      }
    }
    var data = ctx.getImageData(0, 0, SIZE, SIZE).data;
    var painted = 0;
    for (var p = 3; p < data.length; p += 4) if (data[p] > 24) painted++;
    return painted;
  }
  var rows = [].slice.call(document.querySelectorAll('#help-rank-tiers .help-rank-tier'));
  return rows.map(function (row) {
    var svg = row.querySelector('svg.rank-icon');
    if (!svg) return { tier: row.getAttribute('data-tier'), painted: -1, shapes: 0 };
    return { tier: row.getAttribute('data-tier'), painted: raster(svg),
             shapes: svg.querySelectorAll('path,circle,rect,line,polygon,polyline,ellipse').length,
             color: getComputedStyle(svg).color };
  });
})()`;

/** 分值显示口径（与 game.js 的 rankScoringValueText 同一套规则，工具侧独立实现）。 */
function expectedValueText(v) {
  if (typeof v === 'number' && isFinite(v)) {
    if (v === 0) return '0';
    return (v > 0 ? '+' : '−') + Math.abs(v);
  }
  const t = String(v == null ? '' : v).trim();
  if (t === '') return '';
  if (/^[+-]?\d+(\.\d+)?$/.test(t)) {
    const n = Number(t);
    if (n === 0) return '0';
    return (n > 0 ? '+' : '−') + Math.abs(n);
  }
  return t;
}

/**
 * 规范 href 用于比对：只比较 **origin + pathname + search**。
 * ⚠️ 调用方传的"期望地址"必须与**服务端实际给出的地址**一致（带不带结尾斜杠是两回事）,
 *    不然 `?rankfail=1` 这种带参数的地址会一直等不到（实测踩过）。
 */
const normHref = (u) => {
  try {
    const x = new URL(String(u));
    return x.origin + x.pathname + x.search;
  } catch (e) { return String(u); }
};

/** 只比 origin + pathname（忽略 query）：页面地址带不带旗子都算"到了这个页面"。 */
const samePath = (a, b) => {
  try {
    const x = new URL(String(a)), y = new URL(String(b));
    return x.origin === y.origin && x.pathname === y.pathname;
  } catch (e) { return String(a) === String(b); }
};

async function goto(url, waitHref) {
  await send('Page.navigate', { url });
  const want = normHref(waitHref || url);
  let seen = '';
  try {
    await waitFor(async () => {
      const st = await ev('({ href: location.href, ready: document.readyState })');
      seen = st ? (st.ready + ' ' + normHref(st.href)) : 'null';
      return st && st.ready === 'complete' && samePath(st.href, want);
    }, 30000, '页面加载 ' + url);
  } catch (e) {
    throw new Error('页面加载 ' + url + ' 失败：want=' + want + ' 最后看到=' + JSON.stringify(seen));
  }
  await sleep(400);
}

/** 打开帮助 → 等段位图鉴渲染（默认等 9 行）→ 滚到它跟前。 */
async function openHelpAndWait(minRows = 9) {
  await ev('(function(){ document.getElementById("help-btn").click(); return true; })()');
  await waitFor(async () => (await ev('document.querySelectorAll("#help-rank-tiers .help-rank-tier").length')) >= minRows,
    15000, '帮助页段位图鉴渲染出 ' + minRows + ' 行');
  await scrollIntoView('#help-rank-tiers');
}

/** 把元素滚进视口（帮助弹窗内部是滚动容器，判定前必须先滚到跟前）。 */
async function scrollIntoView(sel) {
  await ev(`(function(){ var e = document.querySelector(${JSON.stringify(sel)}); if (e) e.scrollIntoView({ block: 'center' }); return true; })()`);
  await sleep(250);
}

try {
  // ---------- A. 准备：隔离库 + 段位规则数据（服务端权威） ----------
  if (!fs.existsSync(DB)) {
    console.error('找不到隔离库 ' + DB + '：请用 BATTLESHIP_DB_PATH=' + DB + ' 起服务端');
    process.exit(2);
  }
  const seed = dbHelper(['seed', ME, '1850']);        // 轮机长Ⅰ 50 分：解锁项最多的一档之一
  check(!!(seed && seed.ok), 'A1 隔离库里造出账号并设好段位分（' + ME + ' = 1850 分）', seed);

  const constantsResp = await apiGet(APP + 'api/rank_constants');
  const K = constantsResp.json;
  check(constantsResp.status === 200 && !!K && typeof K === 'object',
    'A2 GET /api/rank_constants 匿名可访问且返回 JSON 对象', { status: constantsResp.status });
  const TIERS = (K && Array.isArray(K.tiers)) ? K.tiers : [];
  const SCORING = (K && K.scoring && typeof K.scoring === 'object') ? K.scoring : null;
  check(TIERS.length === 9, 'A3 规则快照里有 9 个段位（含 id 与 tier_name）', TIERS.map((t) => t.id));
  check(!!SCORING && Array.isArray(SCORING.win) && SCORING.win.length > 0
    && Array.isArray(SCORING.lose) && SCORING.lose.length > 0,
    'A4 规则快照里有 scoring（win/lose 两张表非空）—— 这是帮助页数字的唯一来源',
    SCORING ? { win: SCORING.win.length, lose: SCORING.lose.length } : null);
  // 未登录也能读 /api/profile（401 是预期，不是错误）：图鉴的"解锁外观"那一栏才需要登录
  const anonProfile = await apiGet(APP + 'api/profile');
  check(anonProfile.status === 401, 'A5 /api/profile 匿名访问是 401（帮助页据此把"解锁外观"留空，不是错误）',
    anonProfile.status);
  if (TIERS.length !== 9 || !SCORING) {
    console.error('段位规则快照不完整（缺 tiers 或 scoring），后面的断言无法进行 —— 先确认 ranks.constants() 已带上 scoring');
    process.exit(2);
  }

  // ---------- B. 登录（Node 侧拿 cookie → 交给浏览器） ----------
  const login = await loginAndGetCookie();
  check(!!login.cookie, 'B1 登录拿到 session cookie（帮助页的"解锁外观"要 /api/profile 的 catalog）', login);

  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank'], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      // ⚠️ 无头 Edge 自带 edge://sync-confirmation-dialog 且稳定排在 /json/list 第一位：
      //    按 URL 过滤，但**必须留 type==='page' 兜底**（初始页是 about:blank）。
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
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });

  const host = new URL(APP).hostname;
  const setCookie = await send('Network.setCookie', {
    name: 'session', value: login.cookie.replace(/^session=/, ''), domain: host, path: '/', httpOnly: true,
  });
  check(!!(setCookie && setCookie.success), 'B2 session cookie 已交给无头浏览器', setCookie);

  // 故障注入钩子：URL 带 `?rankfail=1` 时让 `/api/rank_constants` 失败。
  // ⚠️ 为什么用 URL 而不是 `window.__failRankConstants` 开关：`addScriptToEvaluateOnNewDocument`
  //    里运行的脚本在**新文档**里跑，页面里设的开关当场被重置 —— 想验证"重载后拿不到规则"
  //    就只能让旗子跟着 URL 走（这是本项目"工具假红"清单里的一条：持久 profile + 同一文档的标志位）。
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `(function(){
    var orig = window.fetch;
    window.fetch = function (url, opts) {
      var fail = false;
      try { fail = new URL(location.href).searchParams.get('rankfail') === '1'; } catch (e) { fail = false; }
      if (fail && String(url).indexOf('/api/rank_constants') >= 0) {
        return Promise.reject(new Error('模拟：段位规则接口不可用'));
      }
      return orig.apply(this, arguments);
    };
    return 'hooked';
  })()` });

  await goto(APP, APP);
  const who = await ev('window.__USERNAME || null');
  check(who === ME, 'B3 页面认得出登录态（window.__USERNAME = 隔离库里的那个账号）', who);

  // 先把名片目录拉起来（帮助页的"解锁外观"吃的是 /api/profile 的 catalog）
  await ev('(async function(){ try { await fetch("/api/profile"); } catch (e) {} return true; })()');

  // ---------- C. 1：点真实入口，段位块出现且可见 ----------
  await openHelpAndWait();
  let H = await ev(HELP_PROBE);
  check(H.section && H.visible && !H.hiddenAttr,
    'C1 点 #help-btn 后 #help-rank-section 出现且可见（真实入口，不是直接调渲染函数）',
    { section: H.section, visible: H.visible, rect: H.sectionRect });
  const helpModalOpen = await ev('!document.getElementById("help-modal").classList.contains("hidden")');
  check(helpModalOpen, 'C1b 用的是现有那个帮助弹窗（#help-modal 打开着，没有另开一个弹窗）');

  // ---------- C. 2：9 个段位图鉴 ----------
  check(H.tierCount === 9, 'C2 #help-rank-tiers 里正好 9 行 .help-rank-tier', H.tierCount);
  const expectedIds = TIERS.map((t) => String(t.id));
  const gotIds = H.tiers.map((t) => String(t.tier));
  check(JSON.stringify(gotIds) === JSON.stringify(expectedIds),
    'C2b 9 行的 data-tier 与 /api/rank_constants 的 tiers 顺序逐个一致（不是前端自建的映射）',
    { expected: expectedIds, got: gotIds });
  const namesOk = H.tiers.every((t, i) => t.name.trim() === String(TIERS[i].name));
  check(namesOk, 'C2c 每行的段位名与接口下发的 tier_name 逐字相同',
    H.tiers.map((t, i) => t.name + ' / ' + TIERS[i].name).slice(0, 3));
  const iconsDrawn = H.tiers.every((t) => t.icon && t.icon.w > 0 && t.icon.h > 0);
  check(iconsDrawn, 'C2d 9 枚 SVG 真的画出来了（getBoundingClientRect 的宽高都 > 0）',
    H.tiers.map((t) => t.icon ? [Math.round(t.icon.w), Math.round(t.icon.h)] : null));
  const shapesDrawn = H.tiers.every((t) => t.icon && t.icon.shapes > 0);
  check(shapesDrawn, 'C2e 每枚 SVG 里都有真实图形（不是空 <svg>）', H.tiers.map((t) => t.icon && t.icon.shapes));
  // 前 8 个段位有"起始 N 分"，大舰长那行写晋升条件
  const startsOk = H.tiers.slice(0, 8).every((t, i) => {
    const start = K.start_points_of_tier[TIERS[i].id];
    return t.meta.indexOf(String(start) + ' 分') >= 0;
  });
  check(startsOk, 'C2f 前 8 个段位那行显示「起始 N 分」（N 与 start_points_of_tier 一致）',
    H.tiers.slice(0, 8).map((t) => t.meta.trim()));
  const topNote = H.tiers[8] ? H.tiers[8].note : '';
  const noteOk = topNote.indexOf(String(K.admiral_rank_limit)) >= 0
    && topNote.indexOf(String(K.admiral_min_captains)) >= 0
    && topNote.indexOf(String(TIERS[7].name)) >= 0;
  check(noteOk, 'C2g 大舰长那行写明晋升条件（先到船长 + 段内排名前 admiral_rank_limit + 池内人数门槛）', topNote);
  const unlockRows = H.tiers.filter((t) => t.unlock.indexOf('解锁：') === 0 && t.unlock.length > 3);
  check(unlockRows.length >= 5, 'C2h 图鉴按 catalog 的 requirement 归组出各段位解锁的外观（称号/头像框/名片底色）',
    unlockRows.map((t) => t.name + ' → ' + t.unlock).slice(0, 4));

  // ---------- C. 3：计分表逐项与接口一致 ----------
  const compareTable = (domRows, apiRows, tag) => {
    if (!domRows.present) return { ok: false, why: tag + ' 容器不存在' };
    if (domRows.rows.length !== apiRows.length) {
      return { ok: false, why: tag + ' 行数不一致', dom: domRows.rows.length, api: apiRows.length };
    }
    for (let i = 0; i < apiRows.length; i++) {
      const a = apiRows[i], d = domRows.rows[i];
      const want = {
        label: String(a.label || a.key || '').trim(),
        value: expectedValueText(a.value),
        condition: String(a.condition || '').trim(),
      };
      const got = { label: String(d.label || '').trim(), value: String(d.value || '').trim(), condition: String(d.condition || '').trim() };
      if (got.label !== want.label || got.value !== want.value || got.condition !== want.condition) {
        return { ok: false, why: tag + ' 第 ' + (i + 1) + ' 行与接口不一致', want, got };
      }
    }
    return { ok: true, count: apiRows.length };
  };
  const winCmp = compareTable(H.win, SCORING.win, '胜局表');
  check(winCmp.ok, 'C3 #help-rank-scoring-win 每一格都与 /api/rank_constants 的 scoring.win 一致', winCmp);
  const loseCmp = compareTable(H.lose, SCORING.lose, '败局表');
  check(loseCmp.ok, 'C3b #help-rank-scoring-lose 每一格都与 scoring.lose 一致', loseCmp);
  const baseWin = SCORING.win.find((r) => r.key === 'base') || SCORING.win[0];
  const shownWin = H.win.rows.find((r) => r.label === String(baseWin.label));
  check(!!shownWin && shownWin.value === expectedValueText(baseWin.value) && shownWin.value.charAt(0) === '+',
    'C3c 胜利基础分带符号显示（+' + baseWin.value + '），没有变成裸数字',
    shownWin);
  const baseLose = SCORING.lose.find((r) => r.key === 'base') || SCORING.lose[0];
  const shownLose = H.lose.rows.find((r) => r.label === String(baseLose.label));
  check(!!shownLose && shownLose.value === expectedValueText(baseLose.value),
    'C3d 失败基础分显示成负号形式（' + expectedValueText(baseLose.value) + '）', shownLose);
  const capsOk = typeof SCORING.loss_floor === 'number'
    ? H.scoringPlaceholder.indexOf('败局单局扣分不低于 ' + expectedValueText(SCORING.loss_floor)) >= 0 : true;
  check(capsOk, 'C3e 表外的数（败局扣分下限 / 闪电战阈值 / 0 分封底）也照接口的值写，不是手抄的',
    H.scoringPlaceholder.slice(-160));

  // ---------- C. 4：高段位的图标真的更重（光栅化数像素，两端都断言） ----------
  const pixels = await ev(ICON_PIXEL_PROBE);
  const px = {};
  pixels.forEach((p) => { px[p.tier] = p; });
  const lowTier = String(TIERS[0].id), midTier = String(TIERS[5].id), topTier = String(TIERS[8].id);
  check(!(px[lowTier] && px[lowTier].painted < 0), 'C4 图标光栅化探针可用（canvas 能取到像素）', px[lowTier]);
  check(!!(px[topTier] && px[lowTier] && px[topTier].painted > px[midTier].painted && px[midTier].painted > px[lowTier].painted),
    'C4b 段位越高图标画出来的像素越多（低 → 中 → 高严格递增，真实光栅化不是数 path 条数）',
    { low: px[lowTier] && px[lowTier].painted, mid: px[midTier] && px[midTier].painted, top: px[topTier] && px[topTier].painted });
  // 反证：最低段位那行**确实轻**（避免"探针恒真"的假绿）
  check(!!(px[lowTier] && px[lowTier].painted > 0 && px[lowTier].painted < px[topTier].painted * 0.75),
    'C4c 最低段位那行确实"轻"（像素数不足最高段位的 75%，两端都断言才不是假绿）',
    { low: px[lowTier] && px[lowTier].painted, top: px[topTier] && px[topTier].painted });
  const colorOf = (id) => (H.tiers.find((t) => t.tier === id) || {}).icon || {};
  const cLow = colorOf(lowTier).color, cTop = colorOf(topTier).color;
  check(cLow && cTop && cLow !== cTop,
    'C4d 高低段位的图标颜色确有差异（配色来自 style.css 第 29 节，帮助页直接复用）', { low: cLow, top: cTop });
  check(!!colorOf(topTier).filter && colorOf(topTier).filter !== 'none',
    'C4e 最高段位带光晕（filter 生效；低段位没有）',
    { top: colorOf(topTier).filter, low: colorOf(lowTier).filter });

  // ---------- C. 5：排位规则文案 ----------
  const rulesText = await ev('(function(){ var s = document.getElementById("help-rank-section"); return s ? s.textContent : ""; })()');
  const needText = [['排位对战', '怎么进排位'], ['需要登录', '需要登录'], ['投降', '赛前投降不给分'],
    ['人机', '人机局不给分'], ['自定义房', '自定义房不给分'], ['0 分', '0 分封底'],
    ['段位榜', '段位榜页签'], ['段位公开', '段位公开开关'], ['不受这个开关影响', '段位榜不受开关影响']];
  const missing = needText.filter(([t]) => rulesText.indexOf(t) < 0).map(([, why]) => why);
  check(missing.length === 0, 'C5 排位规则要讲到的点都在（怎么进排位 / 不给分的三种情况 / 0 分封底 / 在哪看 / 公开开关）', missing);

  // ---------- C. 6：拉不到接口 → 错误位可见 + 容器不清空 ----------
  // ⚠️ 必须**从页面加载那一刻**就让它失败：`rankHelpConstants` 是模块作用域的缓存，
  //    成功拿到一次之后点多少次帮助都不会再发请求 —— 所以加载带 `?rankfail=1` 的页面，
  //    让首屏那次 `/api/rank_constants` 直接失败（也顺手验证了图鉴**不依赖**那个接口）。
  await goto(APP + '?rankfail=1', APP);
  await ev('(function(){ document.getElementById("help-btn").click(); return true; })()');
  await waitFor(async () => (await ev('(function(){ var e = document.getElementById("help-rank-error"); return !!e && e.hidden !== true && getComputedStyle(e).display !== "none"; })()')),
    15000, '故障情形下 #help-rank-error 可见');
  const afterFail = await ev(HELP_PROBE);
  check(afterFail.error.present && !afterFail.error.hidden && afterFail.error.text.length > 0,
    'C6 接口拉不到时 #help-rank-error 可见且有说明文案（不是静默失败）', afterFail.error);
  check(afterFail.error.text.indexOf('段位规则加载失败') >= 0
    && afterFail.error.text.indexOf('上一次成功加载的内容') >= 0,
    'C6b 提示文案写明"加载失败"，并说明下面保留的是上一次的内容', afterFail.error.text);
  check(afterFail.win.rows.length === 0 && afterFail.lose.rows.length === 0,
    'C6c 计分表**不编数字顶上**：拿不到 scoring 时两张表是空的',
    { win: afterFail.win.rows.length, lose: afterFail.lose.rows.length });
  check(afterFail.scoringPlaceholder.indexOf('计分规则暂不可用') >= 0
    && afterFail.scoringPlaceholder.indexOf('加载中') < 0,
    'C6d 计分表位置写明「暂不可用」（不是永远挂在"加载中…"），更不显示一份推算出来的假表',
    afterFail.scoringPlaceholder.trim().slice(0, 90));
  const failTiersText = await ev("(function(){ var t = document.getElementById('help-rank-tiers'); return (t.textContent || '').trim(); })()");
  check(String(failTiersText).length > 0,
    'C6e 图鉴容器不是"清空留白"：拿不到规则时给的是明确占位文案', JSON.stringify(String(failTiersText).slice(0, 40)));
  check(afterFail.section === true && !afterFail.hiddenAttr,
    'C6f 规则拉不到时 #help-rank-section 整块仍然在（不是把容器清空/藏起来）',
    { section: afterFail.section, rect: afterFail.sectionRect });
  const failRules = await ev('(function(){ var s = document.getElementById("help-rank-section"); return s ? s.textContent : ""; })()');
  check(failRules.indexOf('需要登录') >= 0 && failRules.indexOf('0 分封底') >= 0,
    'C6g 静态的规则文案照旧渲染（它们不来自那个接口，失败也不该消失）');

  // 恢复：去掉 URL 上的旗子重新加载 —— 同一个入口应当自愈（错误位收起、内容回来）
  await goto(APP, APP);
  await openHelpAndWait();
  const recovered = await ev(HELP_PROBE);
  check(recovered.error.hidden && recovered.win.rows.length === 7
    && recovered.lose.rows.length === 6 && recovered.tierCount === 9,
    'C6h 接口恢复后重开帮助即自愈：错误位收起、9 行图鉴与两张计分表照常（不清空 → 重填正确）',
    { errHidden: recovered.error.hidden, tiers: recovered.tierCount, win: recovered.win.rows.length, lose: recovered.lose.rows.length });

  // ---------- D. 三个视口：不横向溢出、段位行不被压住 ----------
  for (const [w, h] of [[320, 568], [390, 844], [1600, 1000]]) {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await sleep(400);
    // 关掉再打开，确保这个视口下真的重新渲染过一次
    await ev('(function(){ document.getElementById("help-modal").classList.add("hidden"); return true; })()');
    await openHelpAndWait();

    const size = await ev(`(function(){
      var c = document.querySelector('#help-modal .modal-content');
      return { sw: c ? c.scrollWidth : 0, cw: c ? c.clientWidth : 0,
               secSw: (document.getElementById('help-rank-section') || {}).scrollWidth || 0,
               secCw: (document.getElementById('help-rank-section') || {}).clientWidth || 0,
               pageSw: document.scrollingElement.scrollWidth, iw: innerWidth }; })()`);
    check(size.sw <= size.cw + 4, `${w}×${h}：帮助弹窗内部没有横向溢出（scrollWidth ≤ clientWidth）`, size);
    check(size.pageSw <= size.iw + 1, `${w}×${h}：帮助页整体没有把文档撑出横向滚动`, size);

    const rows = await ev(`(function(){
      return [].slice.call(document.querySelectorAll('#help-rank-tiers .help-rank-tier')).map(function (r) {
        var b = r.getBoundingClientRect();
        var icon = r.querySelector('svg.rank-icon');
        var ib = icon ? icon.getBoundingClientRect() : null;
        return { tier: r.getAttribute('data-tier'), clientW: r.clientWidth, scrollW: r.scrollWidth,
                 h: Math.round(b.height), iconW: ib ? Math.round(ib.width) : 0, iconH: ib ? Math.round(ib.height) : 0 };
      }); })()`);
    check(rows.length === 9, `${w}×${h}：段位图鉴仍是 9 行`, rows.length);
    const squeezed = rows.filter((r) => r.scrollW > r.clientW + 2 || r.h < 24 || r.iconW < 20 || r.iconH < 20);
    check(squeezed.length === 0, `${w}×${h}：段位行没有被压住（行内不溢出、行高 ≥24px、图标 ≥20px）`, squeezed);
    const iconOverflow = rows.filter((r) => r.iconW > size.cw);
    check(iconOverflow.length === 0, `${w}×${h}：图标没有超出弹窗宽度`, iconOverflow);

    // 谁在溢出？逐个后代量 scrollWidth（只报"自己比父容器还宽"的那些，并把它的孩子标出来）
    const overflowKids = await ev(`(function(){
      var root = document.getElementById('help-rank-section');
      var limit = root.getBoundingClientRect().width;
      var describe = function (el) {
        return { tag: el.tagName, cls: String(el.className).slice(0, 40), id: el.id || '',
                 sw: el.scrollWidth, cw: el.clientWidth, ow: Math.round(el.getBoundingClientRect().width),
                 ws: getComputedStyle(el).whiteSpace,
                 kids: [].slice.call(el.children).map(function (k) {
                   return { tag: k.tagName, cls: String(k.className).slice(0, 30),
                            sw: k.scrollWidth, cw: k.clientWidth,
                            ow: Math.round(k.getBoundingClientRect().width), ws: getComputedStyle(k).whiteSpace }; }) };
      };
      var bad = [];
      [].slice.call(root.querySelectorAll('*')).forEach(function (el) {
        if (el.scrollWidth > Math.ceil(limit) + 2) bad.push(describe(el));
      });
      return bad.slice(0, 3); })()`);
    check(overflowKids.length === 0, `${w}×${h}：#help-rank-section 里没有比容器还宽的后代`, overflowKids);

    await scrollIntoView('#help-rank-tiers .help-rank-tier:nth-child(5)');
    const probe = await ev(OCCLUSION_PROBE('#help-rank-tiers .help-rank-tier:nth-child(5)'));
    check(probe.present && probe.occluded === 0 && probe.samples >= 3,
      `${w}×${h}：段位行没有被任何元素压住（多点 elementFromPoint 采样）`, probe);
    await scrollIntoView('#help-rank-scoring-win');
    const probeWin = await ev(OCCLUSION_PROBE('#help-rank-scoring-win'));
    check(probeWin.present && probeWin.occluded === 0 && probeWin.samples >= 3,
      `${w}×${h}：胜局计分表没有被任何元素压住`, probeWin);

    if (w === 320 && SHOT) {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(SHOT.replace(/\.png$/i, '_320.png'), Buffer.from(shot.data, 'base64'));
    }
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await sleep(300);

  if (SHOT) {
    await ev('(function(){ document.getElementById("help-modal").classList.add("hidden"); return true; })()');
    await openHelpAndWait();
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(png.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }

  // ---------- E. 全程零异常 ----------
  check(jsProblems.length === 0, 'E1 全程无 JS 异常 / console.error', jsProblems.slice(0, 4));
} catch (err) {
  console.error('检查中断: ' + err.message);
  problems.push('中断: ' + err.message);
} finally {
  try { if (ws) ws.close(); } catch (e) { /* ignore */ }
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
}

console.log('');
console.log(`通过 ${passes.length} 项 / 失败 ${problems.length} 项`);
console.log(problems.length ? ('✗ 未通过: ' + problems.join(' | ')) : '✓ 全部通过');
process.exit(problems.length ? 1 : 0);
