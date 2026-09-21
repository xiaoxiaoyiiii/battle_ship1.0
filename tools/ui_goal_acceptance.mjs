#!/usr/bin/env node
/**
 * 目标验收探针（goal AC3 / AC5 / AC6）。
 *
 * 与 tools/ui_layout_check.mjs 的分工：
 *   · ui_layout_check 是「布局不变量」回归网（宽屏 4 档 + 紧凑 6 档 + 首页）；
 *   · 本脚本是**这批修复的验收清单**，逐条打印 AC 编号与实测值，便于人工核对。
 *
 * 用法：
 *   BATTLESHIP_DB_PATH=.tmp/x.db CORS_ORIGINS=http://127.0.0.1:5079 PORT=5079 \
 *     ENABLE_TEST_EVENTS=1 python server.py
 *   node tools/ui_goal_acceptance.mjs --url http://127.0.0.1:5079/
 *
 * 退出码：0 = 全部通过；1 = 有未通过项。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5079/');
const PORT = 9355;
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
if (!EDGE) { console.error('找不到 Edge/Chrome'); process.exit(2); }
const PROFILE = 'C:/Windows/Temp/ui_goal_acceptance_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let ws = null; let browser = null; let seq = 0; const pending = new Map(); const problems = [];
function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
  });
}
async function ev(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}
async function setViewport(w, h, dsf) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dsf, mobile: !!dsf && dsf > 1 });
  await send('Emulation.setTouchEmulationEnabled', { enabled: !!(dsf > 1), maxTouchPoints: 5 });
  await sleep(500);
}

// 手牌「真的能点」的计数（与 ui_layout_check 同一口径）
const HAND_PROBE = function () {
  var hand = document.getElementById('magic-hand');
  if (!hand) return { cards: 0, clickable: 0, rect: null };
  var cards = hand.querySelectorAll('.magic-card');
  var n = 0;
  [].slice.call(cards).forEach(function (c) {
    var b = c.getBoundingClientRect();
    if (b.width <= 0 || b.height <= 0) return;
    var cx = (b.left + b.right) / 2, cy = (b.top + b.bottom) / 2;
    if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) return;
    var t = document.elementFromPoint(cx, cy);
    if (t && (t === c || c.contains(t) || t.contains(c))) n++;
  });
  var sys = document.getElementById('magic-system');
  var sr = sys ? sys.getBoundingClientRect() : null;
  return { cards: cards.length, clickable: n, rect: sr ? { y: Math.round(sr.top), h: Math.round(sr.height), bottom: Math.round(sr.bottom) } : null };
};

const HUD_PROBE = function () {
  var ids = [['阶段按钮', 'enter-battle-phase'], ['结束阶段', 'enter-end-phase'], ['交回合', 'end-turn-btn'],
             ['投降', 'surrender-btn'], ['阶段时点', 'phase-timing-toggle'], ['日志折叠', 'toggle-log'],
             ['弃牌堆', 'view-discard-pile'], ['快捷语', 'quick-chat-btn'], ['手牌区', 'magic-system']];
  var blocked = [];
  ids.forEach(function (p) {
    var el = document.getElementById(p[1]);
    if (!el) return;
    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    var b = el.getBoundingClientRect();
    if (!b.width || !b.height) return;
    var t = document.elementFromPoint((b.left + b.right) / 2, (b.top + b.bottom) / 2);
    if (!t) { blocked.push(p[0] + '=null'); return; }
    if (t === el || el.contains(t) || t.contains(el)) return;
    blocked.push(p[0] + '<-' + (t.id || t.className || t.tagName));
  });
  var board = document.getElementById('game-player-board');
  var bb = board ? board.getBoundingClientRect() : null;
  return { blocked: blocked,
    boardInView: !!bb && bb.bottom <= window.innerHeight + 1 && bb.top >= -1,
    boardBottom: bb ? Math.round(bb.bottom) : null, vh: window.innerHeight };
};

// 键盘可达：棋盘格与手牌的可聚焦数
const KEYBOARD_PROBE = function () {
  function focusable(el) {
    if (!el) return false;
    if (el.tabIndex >= 0) return true;
    var tag = el.tagName;
    return (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT' || tag === 'SELECT') && !el.disabled;
  }
  var cells = [].slice.call(document.querySelectorAll('#game-player-board .cell'));
  var cards = [].slice.call(document.querySelectorAll('#magic-hand .magic-card'));
  return {
    cells: cells.length, cellsFocusable: cells.filter(focusable).length,
    cards: cards.length, cardsFocusable: cards.filter(focusable).length,
    cellRole: cells[0] ? (cells[0].getAttribute('role') || null) : null
  };
};

async function enterGame() {
  await ev('document.readyState === "complete"');
  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="验收"; document.getElementById("ai-match").click(); return 1;})()');
  for (let i = 0; i < 40; i++) {
    if (await ev('document.getElementById("ship-placement-screen").classList.contains("active")')) break;
    await sleep(500);
  }
  await ev('document.getElementById("random-ships").click()');
  await sleep(400);
  await ev('document.getElementById("confirm-ships").click()');
  for (let i = 0; i < 6; i++) {
    await ev('document.querySelectorAll(".rps-choice")[0].click()');
    await sleep(3000);
    if (await ev('document.getElementById("game-screen").classList.contains("active")')) break;
  }
  for (let i = 0; i < 40; i++) {
    if (await ev('!!document.querySelector("#game-player-board .cell")')) break;
    await sleep(500);
  }
  await sleep(1000);
}

try {
  browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE, '--window-size=1600,1000', 'about:blank'], { stdio: 'ignore' });
  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 等浏览器起来 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接调试端口');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('ws 连接失败')); });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });   // 必须：否则读到旧 CSS/JS
  await setViewport(1600, 1000, 1);
  await send('Page.navigate', { url: APP });
  await sleep(2500);

  // ---------- AC6：等级条轨道宽度（登录态） ----------
  const uname = 'goalachk' + Math.floor(Math.random() * 1e9);
  await ev(`fetch('/register', {method:'POST', credentials:'same-origin',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:'username=' + encodeURIComponent(${JSON.stringify(uname)}) + '&password=pass123456',
    redirect:'follow'}).then(function(r){return r.status;}).catch(function(){return 0;})`);
  await send('Page.navigate', { url: APP });
  await sleep(2500);
  const loggedIn = await ev('!!window.__USERNAME');
  console.log('登录态: ' + (loggedIn ? '已登录 (' + uname + ')' : '仍是游客'));
  for (const [label, w, h, dsf] of [['1600x1000', 1600, 1000, 1], ['390x844', 390, 844, 3]]) {
    await setViewport(w, h, dsf);
    const bar = await ev('(function(){var s=document.getElementById("my-level-strip");' +
      ' var b=document.querySelector("#my-level-strip .mls-bar");' +
      ' var vis = !!s && getComputedStyle(s).display !== "none" && s.getBoundingClientRect().width > 0;' +
      ' return { visible: vis, barW: b ? Math.round(b.getBoundingClientRect().width * 100) / 100 : null }; })()');
    check(loggedIn && bar.visible && bar.barW > 0,
      'AC6 ' + label + ' 等级条进度轨道宽度 > 0', bar);
  }

  // ---------- AC3-5：难度下拉内容盒 ----------
  for (const [label, w, h, dsf] of [['1600x1000', 1600, 1000, 1], ['390x844', 390, 844, 3], ['320x568', 320, 568, 2]]) {
    await setViewport(w, h, dsf);
    const sel = await ev('(function(){var s=document.getElementById("ai-difficulty"); if(!s) return null;' +
      ' var cs=getComputedStyle(s), b=s.getBoundingClientRect();' +
      ' var pad=(parseFloat(cs.paddingLeft)||0)+(parseFloat(cs.paddingRight)||0)+(parseFloat(cs.borderLeftWidth)||0)+(parseFloat(cs.borderRightWidth)||0);' +
      ' var contentW=b.width-pad;' +
      ' var c=document.createElement("canvas").getContext("2d"); var maxT=0;' +
      ' if(c){ c.font=cs.fontStyle+" "+cs.fontWeight+" "+cs.fontSize+"/"+cs.lineHeight+" "+cs.fontFamily;' +
      '   for(var i=0;i<s.options.length;i++) maxT=Math.max(maxT,c.measureText(s.options[i].textContent).width); }' +
      ' return { contentW: Math.round(contentW*100)/100, maxTextW: Math.round(maxT*100)/100 }; })()');
    check(!!sel && sel.contentW >= sel.maxTextW,
      'AC3-5 ' + label + ' 难度下拉内容盒放得下最长选项文字', sel);
  }

  // ---------- 进对局 ----------
  await setViewport(1600, 1000, 1);
  await send('Page.navigate', { url: APP });
  await sleep(1500);
  await enterGame();

  // AC3-1/2/3：宽屏 4 档
  for (const [label, w, h] of [['1600x1000', 1600, 1000], ['1440x900', 1440, 900],
                               ['1366x768', 1366, 768], ['1280x800', 1280, 800]]) {
    await setViewport(w, h, 1);
    await ev('window.scrollTo(0,0)');
    const hud = await ev('(' + HUD_PROBE.toString() + ')()');
    const hand = await ev('(' + HAND_PROBE.toString() + ')()');
    check(hud.boardInView, 'AC3-1 ' + label + ' 棋盘完整落在首屏内', { bottom: hud.boardBottom, vh: hud.vh });
    check(hud.blocked.length === 0, 'AC3-2 ' + label + ' HUD 控件未被浮窗盖住', hud.blocked);
    check(hand.cards > 0 && hand.clickable > 0, 'AC3-3 ' + label + ' 手牌可见且可点', hand);
  }

  // AC3-4：紧凑矮屏
  for (const [label, w, h, dsf] of [['320x568', 320, 568, 2], ['664x336', 664, 336, 2]]) {
    await setViewport(w, h, dsf);
    const hand = await ev('(' + HAND_PROBE.toString() + ')()');
    check(hand.cards > 0 && hand.clickable > 0, 'AC3-4 ' + label + ' 手牌可见且可点', hand);
  }

  // AC3-6：键盘可达
  await setViewport(1600, 1000, 1);
  const kb = await ev('(' + KEYBOARD_PROBE.toString() + ')()');
  check(kb.cells === 36 && kb.cellsFocusable === 36, 'AC3-6 对局棋盘 36 格全部可聚焦', kb);
  check(kb.cards > 0 && kb.cardsFocusable === kb.cards,
    'AC3-6 手牌每张都可聚焦', { cards: kb.cards, focusable: kb.cardsFocusable });

  // AC3-7：模态框 dialog 语义
  const ax = await (async () => {
    const modals = await ev('[].slice.call(document.querySelectorAll(".modal-overlay")).map(function(m){return m.id;})');
    let dialogCount = 0;
    for (const id of modals) {
      await ev(`(function(){var m=document.getElementById(${JSON.stringify(id)}); if(m) m.classList.remove('hidden'); return 1;})()`);
      await sleep(300);
      const tree = await send('Accessibility.getFullAXTree', {});
      const n = (tree.nodes || []).filter((x) => (x.role && x.role.value) === 'dialog').length;
      if (n > 0) dialogCount++;
      await ev(`(function(){var m=document.getElementById(${JSON.stringify(id)}); if(m) m.classList.add('hidden'); return 1;})()`);
      await sleep(200);
    }
    return { modals: modals.length, dialogs: dialogCount };
  })();
  check(ax.dialogs === ax.modals, 'AC3-7 每个模态框在 AX 树里都有 dialog 节点', ax);

  console.log(NL + (problems.length
    ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL)
    : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
} catch (err) {
  console.error('验收中断: ' + err.message);
  process.exit(1);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
}
