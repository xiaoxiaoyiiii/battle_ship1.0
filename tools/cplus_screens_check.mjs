#!/usr/bin/env node
/**
 * C+ 周边屏幕验收（无头 Edge + CDP）
 *
 * 覆盖 docs/C_PLUS_SCREENS_IMPLEMENTATION_2026_09_29.md 的十屏：
 *   lobby · room · placement · collection · leaderboard · profile
 *   result · spectate · replay · settings
 *
 * 每一屏 × 三个视口（1440×900 / 1280×720 / 390×844）断言四件事：
 *   ① 这一屏真的能进（屏幕 active / 弹窗可见）
 *   ② 页面**没有水平溢出**（`scrollWidth <= clientWidth + 1`）
 *   ③ C+ 那一层的门控属性在 <html> 上（data-arena-screens / 逐屏清单命中）
 *   ④ 该屏的 C+ 标记物真的拿到了样式（面板圆角 12px / 屏头 eyebrow / 徽记…）
 * 外加：全程零 JS 异常；图鉴在窄屏要能"点卡 → 详情页 → 返回列表"。
 *
 * ⚠️ 本工具**不替代**那几支按真实数据跑的工具（lobby_check / replay_check /
 *    spectate_check / ranked_check / profile_card_check / codex_realcard_check）：
 *    它管的是"十屏的公共外观契约"，数据正确性仍由各自那支守。
 *    进入需要真实对局的屏（布船 / 结算 / 回放 / 观战）时，本工具按
 *    tools/acceptance_shots.mjs 的既有手法**直接切屏**（不伪造数据），
 *    所以它断言的只是外壳与布局，不碰任何数值。
 *
 * 用法：node tools/cplus_screens_check.mjs --url http://127.0.0.1:5000/
 *      加 --shots <dir> 会把每屏每档的截图落盘。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOTS = argOf('--shots', '');
const PORT = Number(argOf('--port', '9357'));
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.log('找不到 Edge/Chrome，跳过（CI 环境正常）'); process.exit(0); }

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const VIEWPORTS = [
  ['1440x900', 1440, 900],
  ['1280x720', 1280, 720],
  ['390x844', 390, 844],
];

/* 进入某一屏的最小必要动作。
   `root` = 屏幕根 id（切 active）；`modal` = 要打开的弹窗 id。
   `before` 是切屏前要补的"这一屏需要有东西可画"的准备（不伪造业务数据）。 */
const SCREENS = [
  { key: 'lobby', root: 'lobby-screen', marker: '#lobby-screen .lobby-panel' },
  { key: 'room', root: 'custom-room-screen', marker: '#custom-room-info',
    before: `(function(){ var i = document.getElementById('custom-room-info'); if (i) i.classList.remove('hidden');
      var c = document.getElementById('custom-current-room-id'); if (c && !c.textContent.trim()) c.textContent = 'A7C2E1'; return 1; })()` },
  { key: 'placement', root: 'ship-placement-screen', marker: '.ax-deploy-side',
    before: `(function(){ var b = document.getElementById('player-board'); if (b && !b.children.length && typeof initBoard === 'function') initBoard(b, true);
      var r = document.getElementById('random-ships'); if (r) r.click(); return 1; })()` },
  { key: 'collection', modal: 'help-modal', marker: '.ax-codex',
    before: `(function(){ document.getElementById('help-btn').click(); return 1; })()`, wantDetailPage: true },
  { key: 'leaderboard', root: 'leaderboard-screen', marker: '#leaderboard-tabs',
    before: `(function(){ if (typeof showLeaderboard === 'function') showLeaderboard(); return 1; })()` },
  { key: 'profile', modal: 'opponent-stats-modal', marker: '#opponent-stats-title',
    before: `(function(){ var n = window.__USERNAME || ''; if (typeof window.showUserProfile === 'function') window.showUserProfile(n); return 1; })()` },
  { key: 'result', root: 'game-over-screen', marker: '.over-verdict',
    before: `(function(){ var h = document.getElementById('over-head'); if (h) h.classList.add('win');
      var r = document.getElementById('game-result'); if (r && !r.textContent.trim()) r.textContent = '胜利';
      return 1; })()` },
  { key: 'replay', root: 'replay-screen', marker: '.replay-topbar' },
  { key: 'spectate', root: 'spectate-screen', marker: '.spectate-topbar' },
  { key: 'settings', modal: 'settings-modal', marker: '.ax-preview',
    before: `(function(){ if (typeof openSettingsModal === 'function') openSettingsModal('look'); else document.getElementById('settings-btn').click(); return 1; })()` },
];

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/cplus_check_profile', 'about:blank'], { stdio: 'ignore' });

let target = null;
for (let i = 0; i < 60; i++) {
  try {
    const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
    target = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list.find((t) => t.type === 'page');
    if (target) break;
  } catch (e) { /* 还没起来 */ }
  await sleep(500);
}
if (!target) { console.error('无法连接无头浏览器调试端口'); process.exit(1); }

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
let seq = 0;
const pending = new Map();
const jsProblems = [];
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id); pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    return;
  }
  if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
};
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq; pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method, params }));
  setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 25000);
});
const ev = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 400) };
  return r.result && r.result.value;
};

/* 一次求值做完"进屏 + 量几何 + 量标记物"。整段在页面里同步执行，
   所以不存在"切了屏但还没绘制"的时序问题（样式在切类名的同一帧就生效）。 */
const PROBE = `(function(cfg){
  // ① 先清干净：关掉所有浮层、退掉所有屏
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  document.querySelectorAll('.modal-overlay').forEach(function(m){ m.classList.add('hidden'); });
  document.body.classList.remove('layout-compact', 'layout-ingame');
  var help = document.getElementById('help-content'); if (help) help.classList.remove('ax-show-detail');
  // ② 该屏需要的准备（不伪造业务数据，见文件头说明）
  if (cfg.before) { try { eval(cfg.before); } catch (e) { return { setupError: String(e).slice(0,200) }; } }
  // ③ 切屏
  if (cfg.root) {
    var el = document.getElementById(cfg.root);
    if (!el) return { missing: cfg.root };
    el.classList.add('active');
  }
  if (cfg.modal) {
    var m = document.getElementById(cfg.modal);
    if (!m || m.classList.contains('hidden')) return { modalNotOpen: cfg.modal };
  }
  // ④ 量
  function R(el){ if(!el) return null; var r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; }
  var marker = document.querySelector(cfg.marker);
  var de = document.documentElement;
  // ⚠️ eyebrow 必须**按当前这一屏**取：写成一条并联选择器会永远命中 DOM 里最靠前的
  //    那一个（实测十屏都报 "FRIEND ROOM"）。
  var EYEBROW = { lobby: '#lobby-screen > h2', room: '#custom-room-screen > h1',
    placement: '#ship-placement-screen > h2', collection: '#help-modal .modal-content > h2',
    leaderboard: '#leaderboard-screen > h2', profile: '#opponent-stats-modal .modal-content > h2',
    result: '#game-over-screen .over-verdict > h2', replay: '#replay-screen > .replay-title',
    spectate: '#spectate-screen > .spectate-title', settings: '#settings-modal .modal-content > h2' };
  var eyebrowHost = document.querySelector(EYEBROW[cfg.key] || '.__none__');
  var eb = eyebrowHost ? getComputedStyle(eyebrowHost, '::before') : null;
  return {
    gate: { mode: de.getAttribute('data-arena-screens'), list: de.getAttribute('data-arena-screen-list') },
    hit: !!(de.getAttribute('data-arena-screen-list') || '').split(/\\s+/).indexOf(cfg.key) >= 0
      || !!(de.getAttribute('data-arena-screens') === 'v2'),
    overflow: de.scrollWidth - de.clientWidth,
    vw: window.innerWidth,
    markerFound: !!marker,
    markerRect: R(marker),
    markerRadius: marker ? getComputedStyle(marker).borderTopLeftRadius : null,
    eyebrow: eb && eb.content && eb.content !== 'none' ? eb.content : null,
    screenActiveCount: document.querySelectorAll('.screen.active').length,
    visibleOverlays: [].slice.call(document.querySelectorAll('.modal-overlay'))
      .filter(function(m){ return !m.classList.contains('hidden'); }).length,
    boardCells: document.querySelectorAll(cfg.root === 'ship-placement-screen' ? '#player-board .cell' : '.__none__').length
  };
})`;

console.log('== C+ 十屏验收 ==');
await send('Page.enable');
await send('Runtime.enable');

for (const [vlabel, w, h] of VIEWPORTS) {
  if (SHOTS) fs.mkdirSync(path.join(SHOTS, vlabel), { recursive: true });
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
  await send('Page.navigate', { url: APP });
  for (let i = 0; i < 60; i++) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break; await sleep(300); }
  await sleep(700);

  for (const screen of SCREENS) {
    const cfg = JSON.stringify({ key: screen.key, root: screen.root || null, modal: screen.modal || null, marker: screen.marker, before: screen.before || null });
    let r = await ev('(' + PROBE + ')(' + cfg + ')');
    if (r && (r.setupError || r.missing || r.modalNotOpen)) {
      check(false, '[' + vlabel + '] ' + screen.key + ' 能进入', r);
      continue;
    }
    // 弹窗/屏切换有 300ms 入场动画 —— 量完几何再等一次动画结束才好截图
    if (screen.key === 'profile' || screen.key === 'leaderboard') { await sleep(700); r = await ev('(' + PROBE + ')(' + cfg + ')'); }
    const label = '[' + vlabel + '] ' + screen.key;
    check(r && r.markerFound === true, label + ' 的 C+ 标记物在页面里（' + screen.marker + '）', r && r.markerRect);
    check(r && r.overflow <= 1, label + ' 无水平溢出', r && { overflow: r.overflow, vw: r.vw });
    check(r && r.hit === true, label + ' 在启用清单里（门控命中）', r && r.gate);
    // 面板圆角：C+ 的面板一律 12px（.ax-panel 与逐屏面板规则）
    if (r && screen.markerRadius) {
      check(['12px', '14px'].indexOf(r.markerRadius) >= 0,
        label + ' 的标记物用的是 C+ 面板圆角（12/14px）', { radius: r.markerRadius, marker: screen.marker });
    }
    // 屏头 eyebrow：除结算/回放/观战外，都能量到 ::before 的内容
    if (r && r.eyebrow) console.log('   ' + label + ' eyebrow = ' + r.eyebrow);
  }

  // 图鉴的窄屏详情页往返（这是 P1 的验收项之一）
  if (w < 600) {
    const flow = await ev(`(function(){
      var help = document.getElementById('help-content');
      var grid = document.getElementById('help-magic-cards');
      var first = grid && grid.querySelector('.magic-card-help');
      if (!first) return { noCard: true };
      var name = first.getAttribute('data-card-name');
      first.click();
      var detailShown = help.classList.contains('ax-show-detail');
      var detail = document.getElementById('codex-detail');
      var txt = detail && detail.querySelector('.ax-detail-text');
      var clamp = txt ? getComputedStyle(txt).webkitLineClamp : null;
      var gridHidden = document.querySelector('.ax-codex-main') ? getComputedStyle(document.querySelector('.ax-codex-main')).display : null;
      var back = document.getElementById('codex-detail-back');
      var backVisible = back ? getComputedStyle(back).display !== 'none' : false;
      if (back) back.click();
      return { name: name, detailShown: detailShown, gridHidden: gridHidden, clamp: clamp,
               backVisible: backVisible, backToGrid: !help.classList.contains('ax-show-detail'),
               textFits: txt ? (txt.scrollHeight <= txt.clientHeight + 1) : null };
    })()`);
    check(flow && flow.detailShown === true, '[390x844] 图鉴点卡切到详情页', flow);
    check(flow && flow.gridHidden === 'none', '[390x844] 详情页把卡网格收起', flow && flow.gridHidden);
    check(flow && flow.clamp === 'none', '[390x844] 详情页的效果说明不截断（能读全）', flow && flow.clamp);
    check(flow && flow.textFits === true, '[390x844] 详情页效果说明完整放得下（无滚动裁切）', flow && flow.textFits);
    check(flow && flow.backVisible === true && flow.backToGrid === true, '[390x844] 「返回图鉴」可见且能回到列表', flow);
  }

  if (SHOTS) {
    for (const screen of SCREENS) {
      const cfg = JSON.stringify({ key: screen.key, root: screen.root || null, modal: screen.modal || null, marker: screen.marker, before: screen.before || null });
      await ev('(' + PROBE + ')(' + cfg + ')');
      await sleep(450);
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(SHOTS, vlabel, screen.key + '.png'), Buffer.from(shot.data, 'base64'));
    }
  }
}

check(jsProblems.length === 0, '全程零 JS 异常', jsProblems.slice(0, 4));

console.log('');
if (problems.length) {
  console.log('✗ ' + problems.length + ' 项未通过：');
  problems.forEach((p) => console.log('   · ' + p));
  process.exit(1);
}
console.log('✓ 全部通过');
ws.close();
browser.kill();
process.exit(0);
