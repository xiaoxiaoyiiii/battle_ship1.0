#!/usr/bin/env node
/**
 * UI 布局回归检查（截图审查修复批的端到端验证）
 *
 * 用无头 Edge 自动打一局人机对战，然后断言几处「改回去就会红」的布局不变量：
 *   1. 效果状态条在没有激活效果时 display:none（否则会渲染成一条空白横条）
 *   2. 两块棋盘同宽同高（否则一块大一块小）
 *   3. 阶段按钮在阶段卡片里水平居中（block 级按钮会贴左边）
 *   4. 投降按钮与「第N回合」标题垂直中线对齐
 *   5. 右下角的局内聊天浮窗和右上角的魔法卡预览框不重叠
 *   6. 页面没有 JS 异常 / 控制台报错
 *
 * 用法：
 *   node tools/ui_layout_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 *
 * 注意：被检查的服务端必须放行该来源，否则 socket.io 会拒绝连接：
 *   PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 python server.py
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def;
};
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9333;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/ui_layout_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) {
  console.error('找不到 Edge/Chrome，跳过 UI 布局检查');
  process.exit(0);
}

let browser = null;
let ws = null;
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

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const NL = String.fromCharCode(10);
const METRICS_EXPR = [
  '(function(){',
  '  function rect(el){ if(!el) return null; var b=el.getBoundingClientRect(); return {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),h:Math.round(b.height)}; }',
  '  function centerY(r){ return r ? Math.round(r.y + r.h/2) : null; }',
  '  var bar=document.getElementById("effect-status-bar");',
  '  var box=document.getElementById("turn-indicator");',
  '  var boxRect=rect(box);',
  '  var btns=["enter-battle-phase","enter-end-phase","end-turn-btn"].map(function(id){ var b=document.getElementById(id); return {id:id, display:b?getComputedStyle(b).display:null, rect:rect(b)}; }).filter(function(b){ return b.display!=="none"; });',
  '  var title=rect(document.querySelector(".turn-indicator-inner h2"));',
  '  var sur=rect(document.getElementById("surrender-btn"));',
  '  var preview=rect(document.getElementById("magic-card-preview"));',
  '  var chat=rect(document.getElementById("in-game-chat-container"));',
  '  function overlap(a,b){ if(!a||!b) return "n/a"; var ox=Math.max(0, Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)); var oy=Math.max(0, Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)); return Math.round(ox)+"x"+Math.round(oy); }',
  '  return {',
  '    phase: document.getElementById("current-phase").textContent,',
  '    statusBarDisplay: getComputedStyle(bar).display,',
  '    statusBarHidden: bar.classList.contains("hidden"),',
  '    boards: [rect(document.getElementById("game-player-board")), rect(document.getElementById("opponent-board"))],',
  '    cells: [document.querySelectorAll("#game-player-board .cell").length, document.querySelectorAll("#opponent-board .cell").length],',
  '    phaseBox: boxRect,',
  '    visibleButtons: btns.map(function(b){ return {id:b.id, offset: Math.round((b.rect.x+b.rect.w/2)-(boxRect.x+boxRect.w/2))}; }),',
  '    titleCenterY: centerY(title),',
  '    surrenderCenterY: centerY(sur),',
  '    previewPanel: preview,',
  '    chatPanel: chat,',
  '    overlap: overlap(preview, chat),',
  '    logEmpty: !!document.querySelector("#game-logs .log-empty"),',
  '    logEntries: document.querySelectorAll("#game-logs .log-entry").length,',
  '    logTextLen: ((document.getElementById("game-logs")||{}).innerText || "").trim().length,',
  '    attacks: (document.getElementById("attacks-remaining")||{}).textContent,',
  '    ships: (document.getElementById("your-ships")||{}).textContent',
  '  };',
  '})()',
].join(NL);

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
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      if (m.error) { p.rej(new Error(JSON.stringify(m.error))); } else { p.res(m.result); }
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') problems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && ['error'].indexOf(m.params.type) >= 0) {
      problems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');

  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="UI检查"; document.getElementById("ai-match").click(); return true;})()');
  await waitFor(async () => await ev('document.getElementById("ship-placement-screen").classList.contains("active")'), 30000, '布船界面');
  await ev('document.getElementById("random-ships").click()');
  await sleep(300);
  await ev('document.getElementById("confirm-ships").click()');
  // 开局（还没有任何攻击/出牌）时，日志必须是空状态提示，而不是一片空白
  await sleep(600);
  const logEmptyAtStart = await ev('!!document.querySelector("#game-logs .log-empty")');
  await waitFor(async () => await ev('document.getElementById("rps-screen").classList.contains("active")'), 30000, '猜拳界面');
  await ev('document.querySelectorAll(".rps-choice")[0].click()');
  await waitFor(async () => await ev('document.getElementById("game-screen").classList.contains("active")'), 30000, '对局界面');
  // 等阶段 UI 渲染出来（updatePhaseUI 由服务端状态驱动，可能晚一两拍）
  await waitFor(async () => await ev('["enter-battle-phase","enter-end-phase","end-turn-btn"].some(function(id){ var b=document.getElementById(id); return b && getComputedStyle(b).display !== "none"; })'), 15000, '阶段按钮出现');
  await sleep(200);

  const m = await ev(METRICS_EXPR);
  console.log('阶段: ' + m.phase + ' | 你的船: ' + m.ships + ' | 剩余攻击次数: ' + m.attacks + NL);

  check(m.statusBarDisplay === 'none' && m.statusBarHidden === true,
    '无激活效果时状态条不渲染', { display: m.statusBarDisplay, hidden: m.statusBarHidden });

  const [b1, b2] = m.boards;
  check(!!b1 && !!b2 && b1.w === b2.w && b1.h === b2.h && b1.w >= 280,
    '两块棋盘同尺寸且不过小', { left: b1, right: b2 });

  check(m.cells[0] === m.cells[1] && m.cells[0] === 36, '两块棋盘格子数一致（6x6）', m.cells);

  const offs = m.visibleButtons.map((b) => b.offset);
  check(offs.length > 0 && offs.every((o) => Math.abs(o) <= 3),
    '阶段按钮在卡片内水平居中', m.visibleButtons);

  check(m.titleCenterY !== null && m.surrenderCenterY !== null && Math.abs(m.titleCenterY - m.surrenderCenterY) <= 3,
    '投降按钮与回合标题垂直对齐', { title: m.titleCenterY, surrender: m.surrenderCenterY });

  // 两个浮窗允许在同一列上下排布，只要重叠面积为零即可
  const [ovx, ovy] = String(m.overlap).split('x').map(Number);
  check(ovx === 0 || ovy === 0, '右上角预览框与右下角聊天窗不重叠', { overlap: m.overlap, preview: m.previewPanel, chat: m.chatPanel });

  check(logEmptyAtStart === true, '开局日志显示空状态提示（而非一片空白）', { logEmptyAtStart: logEmptyAtStart });
  check(m.logTextLen > 0 && !(m.logEmpty && m.logEntries > 0),
    '日志框始终有内容，且占位与真实日志不共存', { empty: m.logEmpty, entries: m.logEntries, textLen: m.logTextLen });

  if (SHOT) {
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  const jsProblems = problems.filter((p) => p.indexOf('JS 异常') === 0 || p.indexOf('console.error') === 0);
  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  console.log(NL + (problems.length ? '结果: ' + problems.length + ' 项不通过' : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
