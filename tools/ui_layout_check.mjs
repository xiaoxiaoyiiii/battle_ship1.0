#!/usr/bin/env node
/**
 * UI 布局回归检查（无头 Edge + CDP）
 *
 * 两段式：
 *   A. 宽屏 1600x1000 —— 原始 9 项不变量（浮窗式桌面布局）
 *   B. 紧凑视口组 —— 移动端自适应不变量（棋盘零遮挡 / 零滚动 / 零叠压 / 触摸目标）
 *
 * 用法：
 *   node tools/ui_layout_check.mjs --url http://127.0.0.1:5000/ [--shot out.png] [--shots dir] [--only wide|compact]
 *
 * 被检查的服务端必须放行该来源：
 *   PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 python server.py
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const SHOTS = argOf('--shots', '');
const ONLY = argOf('--only', '');
const PORT = 9333;
const MIN_TAP = 40;       // 触摸目标下限
const MIN_TAP_TIGHT = 36; // 视口高 < 420（横屏手机）时放宽：336px 高度装不下 6x6@40px + 任何 chrome
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/ui_layout_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过 UI 布局检查'); process.exit(0); }
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

let browser = null, ws = null;
const pending = new Map();
const problems = [];
let seq = 0;

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
  });
}

async function ev(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await fn()) return true; } catch (e) { /* keep polling */ }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label);
}

let currentPass = 'wide';
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + '[' + currentPass + '] ' + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push('[' + currentPass + '] ' + label);
}

// ---------- 探针 A：宽屏（原有 9 项不变量） ----------
function wideProbe() {
  function rect(el) { if (!el) return null; var b = el.getBoundingClientRect(); return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) }; }
  function centerY(r) { return r ? Math.round(r.y + r.h / 2) : null; }
  var bar = document.getElementById('effect-status-bar');
  var box = document.getElementById('turn-indicator');
  var boxRect = rect(box);
  var btns = ['enter-battle-phase', 'enter-end-phase', 'end-turn-btn'].map(function (id) { var b = document.getElementById(id); return { id: id, display: b ? getComputedStyle(b).display : null, rect: rect(b) }; }).filter(function (b) { return b.display !== 'none'; });
  var title = rect(document.querySelector('.turn-indicator-inner h2'));
  var sur = rect(document.getElementById('surrender-btn'));
  var preview = rect(document.getElementById('magic-card-preview'));
  var chat = rect(document.getElementById('in-game-chat-container'));
  function overlap(a, b) { if (!a || !b) return 'n/a'; var ox = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)); var oy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)); return Math.round(ox) + 'x' + Math.round(oy); }
  return {
    phase: document.getElementById('current-phase').textContent,
    statusBarDisplay: getComputedStyle(bar).display,
    statusBarHidden: bar.classList.contains('hidden'),
    boards: [rect(document.getElementById('game-player-board')), rect(document.getElementById('opponent-board'))],
    cells: [document.querySelectorAll('#game-player-board .cell').length, document.querySelectorAll('#opponent-board .cell').length],
    phaseBox: boxRect,
    visibleButtons: btns.map(function (b) { return { id: b.id, offset: Math.round((b.rect.x + b.rect.w / 2) - (boxRect.x + boxRect.w / 2)) }; }),
    titleCenterY: centerY(title),
    surrenderCenterY: centerY(sur),
    previewPanel: preview,
    chatPanel: chat,
    overlap: overlap(preview, chat),
    logEmpty: !!document.querySelector('#game-logs .log-empty'),
    logEntries: document.querySelectorAll('#game-logs .log-entry').length,
    logTextLen: ((document.getElementById('game-logs') || {}).innerText || '').trim().length,
    attacks: (document.getElementById('attacks-remaining') || {}).textContent,
    ships: (document.getElementById('your-ships') || {}).textContent
  };
}

// ---------- 探针 B：紧凑视口（移动端自适应不变量） ----------
function compactProbe(MIN_TAP) {
  var vw = window.innerWidth, vh = window.innerHeight;
  var de = document.documentElement;
  function R(e) { if (!e) return null; var b = e.getBoundingClientRect(); return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height), bottom: Math.round(b.bottom), right: Math.round(b.right) }; }
  function shown(e) { if (!e) return false; var cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false; var b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; }
  function boardStat(id) {
    var board = document.getElementById(id);
    if (!board || !shown(board)) return { id: id, present: false };
    var cells = [].slice.call(board.querySelectorAll('.cell'));
    var occluded = 0, inView = 0, minCell = 1e9, worst = null;
    cells.forEach(function (c) {
      var b = c.getBoundingClientRect();
      minCell = Math.min(minCell, b.width);
      var cx = (b.x + b.right) / 2, cy = (b.y + b.bottom) / 2;
      if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) return;
      inView++;
      var top = document.elementFromPoint(cx, cy);
      var hit = top === c || (top && c.contains(top)) || (top && top.contains(c));
      if (!hit) { occluded++; if (!worst) worst = { top: (top && (top.id || top.className || top.tagName)) || null, cx: Math.round(cx), cy: Math.round(cy) }; }
    });
    var bb = board.getBoundingClientRect();
    return { id: id, present: true, occluded: occluded, inView: inView, cells: cells.length, minCell: Math.round(minCell * 10) / 10,
      rect: R(board), worst: worst,
      fullyInView: bb.top >= -1 && bb.bottom <= window.innerHeight + 1 && bb.left >= -1 && bb.right <= window.innerWidth + 1 };
  }
  var panels = [['预览', document.getElementById('magic-card-preview')], ['日志', document.querySelector('.log-container')],
    ['聊天', document.getElementById('in-game-chat-container')], ['手牌', document.getElementById('magic-system')],
    ['面板槽', document.getElementById('aux-dock')], ['棋盘区', document.querySelector('.boards-container')],
    ['头像角标', document.getElementById('avatar-corner')], ['对手角标', document.getElementById('opponent-avatar-corner')]]
    .filter(function (p) { return shown(p[1]); })
    .map(function (p) { return { name: p[0], el: p[1], r: R(p[1]) }; });
  var overlaps = [];
  for (var i = 0; i < panels.length; i++) for (var j = i + 1; j < panels.length; j++) {
    // 面板槽里装着日志/聊天/手牌，属于包含关系，不算"叠压"
    if (panels[i].el.contains(panels[j].el) || panels[j].el.contains(panels[i].el)) continue;
    var a = panels[i].r, b = panels[j].r;
    var ox = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
    var oy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
    if (ox > 1 && oy > 1) overlaps.push(panels[i].name + '∩' + panels[j].name + '=' + Math.round(ox) + 'x' + Math.round(oy));
  }
  var small = [];
  var clickable = [].slice.call(document.querySelectorAll('#game-screen button, #game-screen .cell, #game-screen .magic-card, #game-screen input, #game-screen .dock-tab'))
    .filter(function (e) { return shown(e); });
  clickable.forEach(function (e) {
    var b = e.getBoundingClientRect();
    var label = e.id || (typeof e.className === 'string' ? e.className.split(' ')[0] : e.tagName);
    if (Math.min(b.width, b.height) < MIN_TAP - 0.5) small.push(label + ':' + Math.round(b.width) + 'x' + Math.round(b.height));
  });
  var elById = function (id) { return document.getElementById(id); };
  var hand = elById('magic-hand');
  var handRect = R(document.getElementById('magic-system'));
  return {
    vw: vw, vh: vh, dpr: window.devicePixelRatio,
    layout: (elById('game-screen') || { dataset: {} }).dataset.layout || null,
    boardMode: (document.querySelector('.boards-container') || { dataset: {} }).dataset.mode || null,
    scrollHeight: de.scrollHeight, innerHeight: vh,
    hOverflow: de.scrollWidth - vw,
    pageScrolls: de.scrollHeight > vh + 2,
    boards: [boardStat('game-player-board'), boardStat('opponent-board')],
    panels: panels,
    overlaps: overlaps,
    smallTargets: small,
    handCards: hand ? hand.querySelectorAll('.magic-card').length : 0,
    handRect: handRect,
    handVisible: handRect ? (handRect.bottom <= vh + 1 && handRect.y >= -1 && handRect.h > 0) : false,
    handInDock: !!(document.getElementById('magic-system') && document.getElementById('magic-system').closest && document.getElementById('magic-system').closest('#aux-dock')),
    dockOpen: (elById('aux-dock') || { dataset: {} }).dataset.open || null,
    dockRect: R(elById('aux-dock')),
    hudRect: R(document.querySelector('.game-info')),
    stageRect: R(document.querySelector('.boards-container')),
    fixedOverlays: [].slice.call(document.querySelectorAll('body *')).filter(function (e) { return getComputedStyle(e).position === 'fixed' && shown(e); }).map(function (e) { return (e.id || e.className) + ''; })
  };
}

const COMPACT_VIEWPORTS = [
  ['320x568', 320, 568, 2],
  ['336x664', 336, 664, 2],
  ['390x844', 390, 844, 3],
  ['430x932', 430, 932, 3],
  ['landscape-664x336', 664, 336, 2],
  ['tablet-768x1024', 768, 1024, 2]
];

async function setViewport(w, h, dsf, mobile) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dsf, mobile: !!mobile });
  await send('Emulation.setTouchEmulationEnabled', { enabled: !!mobile, maxTouchPoints: 5 });
  await sleep(600);
}

async function enterGame() {
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="UI检查"; window.__logDragSeed=1; document.getElementById("ai-match").click(); return true;})()');
  await waitFor(async () => await ev('document.getElementById("ship-placement-screen").classList.contains("active")'), 30000, '布船界面');
  await ev('document.getElementById("random-ships").click()');
  await sleep(400);
  await ev('document.getElementById("confirm-ships").click()');
  const logEmptyAtStart = await ev('!!document.querySelector("#game-logs .log-empty")');
  await waitFor(async () => await ev('document.getElementById("rps-screen").classList.contains("active")'), 30000, '猜拳界面');
  for (let i = 0; i < 5; i++) {
    await ev('document.querySelectorAll(".rps-choice")[0].click()');
    await sleep(3000);
    if (await ev('document.getElementById("game-screen").classList.contains("active")')) break;
  }
  await waitFor(async () => await ev('document.getElementById("game-screen").classList.contains("active")'), 20000, '对局界面');
  await waitFor(async () => await ev('!!document.querySelector("#game-player-board .cell")'), 15000, '棋盘格子');
  await sleep(1200);
  return logEmptyAtStart;
}

try {
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
      target = list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* browser still starting */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');

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
  await setViewport(1600, 1000, 1, false);
  await send('Page.navigate', { url: APP });
  const logEmptyAtStart = await enterGame();

  if (ONLY !== 'compact') {
    currentPass = 'wide';
    await setViewport(1600, 1000, 1, false);
    const m = await ev('(' + wideProbe.toString() + ')()');
    console.log('阶段: ' + m.phase + ' | 你的船: ' + m.ships + ' | 剩余攻击次数: ' + m.attacks + NL);
    check(m.statusBarDisplay === 'none' && m.statusBarHidden === true, '无激活效果时状态条不渲染', { display: m.statusBarDisplay, hidden: m.statusBarHidden });
    const b1 = m.boards[0], b2 = m.boards[1];
    check(!!b1 && !!b2 && b1.w === b2.w && b1.h === b2.h && b1.w >= 280, '两块棋盘同尺寸且不过小', { left: b1, right: b2 });
    check(m.cells[0] === m.cells[1] && m.cells[0] === 36, '两块棋盘格子数一致（6x6）', m.cells);
    const offs = m.visibleButtons.map((b) => b.offset);
    check(offs.length > 0 && offs.every((o) => Math.abs(o) <= 3), '阶段按钮在卡片内水平居中', m.visibleButtons);
    check(m.titleCenterY !== null && m.surrenderCenterY !== null && Math.abs(m.titleCenterY - m.surrenderCenterY) <= 3, '投降按钮与回合标题垂直对齐', { title: m.titleCenterY, surrender: m.surrenderCenterY });
    const parts = String(m.overlap).split('x').map(Number);
    check(parts[0] === 0 || parts[1] === 0, '右上角预览框与右下角聊天窗不重叠', { overlap: m.overlap, preview: m.previewPanel, chat: m.chatPanel });
    check(logEmptyAtStart === true, '开局日志显示空状态提示（而非一片空白）', { logEmptyAtStart: logEmptyAtStart });
    check(m.logTextLen > 0 && !(m.logEmpty && m.logEntries > 0), '日志框始终有内容，且占位与真实日志不共存', { empty: m.logEmpty, entries: m.logEntries, textLen: m.logTextLen });
    if (SHOT) { const s = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(SHOT, Buffer.from(s.data, 'base64')); console.log('截图已保存: ' + SHOT); }
  }

  if (ONLY !== 'wide') {
    currentPass = 'compact';
    for (const [label, w, h, dsf] of COMPACT_VIEWPORTS) {
      await setViewport(w, h, dsf, true);
      await ev('window.scrollTo(0,0)');
      await sleep(500);
      const tap = h < 420 ? MIN_TAP_TIGHT : MIN_TAP;   // 336px 高的横屏放不下 6x6@40px，见文件头说明
      const m = await ev('(' + compactProbe.toString() + ')(' + tap + ')');
      console.log('--- ' + label + '  layout=' + m.layout + ' boards=' + m.boardMode + ' scrollH=' + m.scrollHeight + ' vh=' + m.innerHeight + ' hOverflow=' + m.hOverflow);
      for (const b of m.boards) {
        if (!b.present) { console.log('     棋盘 ' + b.id + ': 未显示'); continue; }
        console.log('     棋盘 ' + b.id + ': 格宽=' + b.minCell + 'px 可视格=' + b.inView + '/' + b.cells + ' 被遮挡=' + b.occluded + ' 整体在视口内=' + b.fullyInView + (b.worst ? ' 最差遮挡=' + JSON.stringify(b.worst) : ''));
      }
      console.log('     面板: ' + m.panels.map((p) => p.name + '(' + p.r.x + ',' + p.r.y + ' ' + p.r.w + 'x' + p.r.h + ')').join(' '));
      if (m.smallTargets.length) console.log('     小于 ' + MIN_TAP + 'px 的可点元素(' + m.smallTargets.length + '): ' + m.smallTargets.slice(0, 8).join(', '));
      if (m.overlaps.length) console.log('     叠压: ' + m.overlaps.join(' | '));
      console.log('     手牌 ' + m.handCards + ' 张 区域=' + JSON.stringify(m.handRect) + ' 全在视口内=' + m.handVisible);
      console.log('     固定层: ' + (m.fixedOverlays.join(', ') || '无'));

      check(m.hOverflow <= 1, label + ' 无水平溢出', m.hOverflow);
      check(!m.pageScrolls, label + ' 对局页不产生纵向滚动（一屏）', { scrollHeight: m.scrollHeight, vh: m.innerHeight });
      const visibleBoards = m.boards.filter((b) => b.present);
      check(visibleBoards.length >= 1, label + ' 至少一块棋盘可见', visibleBoards.map((b) => b.id));
      const occl = visibleBoards.reduce((s, b) => s + b.occluded, 0);
      check(occl === 0, label + ' 棋盘格子零遮挡', visibleBoards.map((b) => ({ id: b.id, occluded: b.occluded })));
      const minCell = Math.min.apply(null, visibleBoards.map((b) => b.minCell));
      check(minCell >= tap, label + ' 格子尺寸达触摸下限 ' + tap + 'px', minCell);
      const notInView = visibleBoards.filter((b) => !b.fullyInView).map((b) => b.id);
      check(notInView.length === 0, label + ' 棋盘完整落在视口内（不需滚动）', notInView);
      check(m.overlaps.length === 0, label + ' 面板之间零叠压', m.overlaps);
      check(m.smallTargets.length === 0, label + ' 可点元素均不小于 ' + tap + 'px', m.smallTargets.slice(0, 10));
      check(m.handCards > 0 && (m.handVisible || m.handInDock),
        label + ' 手牌够得着（常驻在舞台下方，或收在面板槽的卡牌页里）',
        { cards: m.handCards, rect: m.handRect, inDock: m.handInDock });
      if (SHOTS) { const s = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(SHOTS + '/' + label + '.png', Buffer.from(s.data, 'base64')); }

      // 展开面板槽后再测一遍：用户主动看日志/聊天时，棋盘仍必须完整可见且零遮挡
      const clickLogTab = '(function(){var t=document.querySelector(".dock-tab[data-dock-tab=log]"); if(t) t.click(); return 1;})()';
      await ev(clickLogTab);
      await sleep(500);
      const d = await ev('(' + compactProbe.toString() + ')(' + tap + ')');
      if (process.env.UI_CHECK_VERBOSE) {
        console.log('   [面板槽展开] 棋盘区=' + JSON.stringify(d.stageRect) + ' 面板槽=' + JSON.stringify(d.dockRect) + ' 手牌=' + JSON.stringify(d.handRect));
      }
      const vb2 = d.boards.filter((b) => b.present);
      check(vb2.length >= 1 && vb2.reduce((s, b) => s + b.occluded, 0) === 0,
        label + ' 展开面板槽后棋盘仍零遮挡', vb2.map((b) => ({ id: b.id, occluded: b.occluded })));
      check(vb2.length >= 1 && vb2.every((b) => b.fullyInView),
        label + ' 展开面板槽后棋盘仍完整可见', vb2.filter((b) => !b.fullyInView).map((b) => b.id));
      check(d.overlaps.length === 0, label + ' 展开面板槽后无叠压', d.overlaps);
      check(!d.pageScrolls, label + ' 展开面板槽后仍不产生纵向滚动',
        { scrollHeight: d.scrollHeight, vh: d.innerHeight });
      if (SHOTS) { const s2 = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(SHOTS + '/' + label + '-dockopen.png', Buffer.from(s2.data, 'base64')); }
      await ev(clickLogTab);   // 收起，恢复默认态
      await sleep(300);
    }
  }

  currentPass = 'both';
  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  console.log(NL + (problems.length ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL) : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}