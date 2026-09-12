#!/usr/bin/env node
/**
 * 个人战绩 / 对局详情弹窗的 UI 回归检查（无头 Edge + CDP）
 *
 * 覆盖 2026-09-13 修复的三个"只在真实数据下才暴露"的问题：
 *   1. 历史列表把 <button> 塞进 <table><tbody> → HTML 解析器 foster parenting 把按钮
 *      挪到表格之前，表头「时间 对手 结果 局内日志」孤立在列表最下方；
 *   2. 胜负配色被第 3 节通用 button 规则的 background-image 渐变盖掉，三行全蓝；
 *   3. 人机对手显示成裸 ID（vs ai-4530c8）、以及点开胜局时「对手」栏显示成自己。
 *
 * 用法：
 *   node tools/stats_modal_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
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
const USERNAME = argOf('--username', '');
// 登录态检查用：传入 Flask session 值即可（未登录时「个人战绩」入口不会渲染，点击检查会跳过）
const COOKIE = argOf('--cookie', '');
const PORT = 9334;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/stats_modal_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过战绩弹窗检查'); process.exit(0); }

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

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// ---------- 页面内探针：用真实渲染函数造出弹窗内容并测量 ----------
function statsProbe() {
  var me = { id: 'u1', username: 'z1w6qn', wins: 2, losses: 1, current_streak: 1, longest_streak: 2 };
  var history = [
    { winner_id: 'u1', loser_id: 'ai-4530c8', winner_name: 'z1w6qn', loser_name: null, timestamp: 1789201720, logs: [] },
    { winner_id: 'u1', loser_id: 'u2', winner_name: 'z1w6qn', loser_name: 'bravo_u', timestamp: 1789201372, logs: [] },
    { winner_id: 'u3', loser_id: 'u1', winner_name: 'charlie_u', loser_name: 'z1w6qn', timestamp: 1789200912, logs: [{ ts: 1789201000, text: '第一回合 · 你获胜' }] }
  ];
  var content = document.getElementById('user-stats-content');
  var modal = document.getElementById('user-stats-modal');
  content.innerHTML = window.renderUserStatsHTML(me, history, { hasMore: false });
  modal.classList.remove('hidden');

  function rect(el) { var b = el.getBoundingClientRect(); return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height), right: Math.round(b.right) }; }
  var head = content.querySelector('.history-head');
  var rows = [].slice.call(content.querySelectorAll('.match-history-btn'));
  var cols = function (el) { return [].slice.call(el.children).map(function (c) { var b = c.getBoundingClientRect(); return { cls: c.className, x: Math.round(b.x), right: Math.round(b.right) }; }); };

  // 对局详情：赢的那一局，对手应当是 loser_name 而不是自己
  var detailWin = document.getElementById('match-detail-content');
  detailWin.innerHTML = window.renderMatchDetailHTML(history[1], 'u1');
  var detailOppWin = (detailWin.querySelector('.match-detail-value') || {}).textContent || '';
  detailWin.innerHTML = window.renderMatchDetailHTML(history[2], 'u1');
  var detailOppLose = (detailWin.querySelector('.match-detail-value') || {}).textContent || '';
  detailWin.innerHTML = window.renderMatchDetailHTML(history[0], 'u1');
  var detailOppAi = (detailWin.querySelector('.match-detail-value') || {}).textContent || '';

  return {
    tbodyButtons: content.querySelectorAll('tbody button').length,
    headerExists: !!head,
    headerAboveRows: !!(head && rows.length && head.getBoundingClientRect().top < rows[0].getBoundingClientRect().top),
    // 表头必须排在数据行之前（compareDocumentPosition: 4 = FOLLOWING）
    headerBeforeFirstRow: !!(head && rows.length && (head.compareDocumentPosition(rows[0]) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0),
    rowCount: rows.length,
    headCols: head ? cols(head) : [],
    rowCols: rows.map(cols),
    rowTexts: rows.map(function (r) { return r.innerText.replace(/\s+/g, ' ').trim(); }),
    rowClasses: rows.map(function (r) { return r.className; }),
    rowBg: rows.map(function (r) { return getComputedStyle(r).backgroundColor; }),
    rowBgImage: rows.map(function (r) { return getComputedStyle(r).backgroundImage; }),
    resultTexts: [].slice.call(content.querySelectorAll('.match-history-btn .hist-result')).map(function (e) { return e.textContent; }),
    hasAiTag: !!content.querySelector('.hist-tag'),
    hasNote: !!content.querySelector('.user-stats-note'),
    statsRowCount: content.querySelectorAll('.user-stats-table tr').length,
    detailOppWin: detailOppWin.trim(),
    detailOppLose: detailOppLose.trim(),
    detailOppAi: detailOppAi.trim()
  };
}

// ---------- 页面内探针 B：真实账号数据（--username 时使用） ----------
function realProbe(username) {
  return fetch('/user_stats?username=' + encodeURIComponent(username)).then(function (r) { return r.json(); }).then(function (data) {
    if (!data.stats) return { error: 'no stats' };
    var content = document.getElementById('user-stats-content');
    var modalEl = document.getElementById('user-stats-modal');
    modalEl.classList.remove('hidden');
    content.innerHTML = window.renderUserStatsHTML(data.stats, data.history || [], { hasMore: false });
    var mr = modalEl.getBoundingClientRect();
    var modalInfo = {
      cls: modalEl.className,
      display: getComputedStyle(modalEl).display,
      rect: { x: Math.round(mr.x), y: Math.round(mr.y), w: Math.round(mr.width), h: Math.round(mr.height) },
      cardText: (modalEl.innerText || '').replace(/s+/g, ' ').trim().slice(0, 120),
      cardBg: getComputedStyle(modalEl.querySelector('.modal-content')).backgroundColor
    };
    var head = content.querySelector('.history-head');
    var rows = [].slice.call(content.querySelectorAll('.match-history-btn'));
    return {
      username: data.stats.username,
      wins: data.stats.wins,
      losses: data.stats.losses,
      streak: data.stats.current_streak,
      rows: rows.length,
      rowTexts: rows.map(function (r) { return r.innerText.replace(/\s+/g, ' ').trim(); }),
      rowBg: rows.map(function (r) { return getComputedStyle(r).backgroundColor; }),
      tbodyButtons: content.querySelectorAll('tbody button').length,
      headerAboveRows: !!(head && rows.length && head.getBoundingClientRect().top < rows[0].getBoundingClientRect().top),
      hasNote: !!content.querySelector('.user-stats-note'),
      rawAiIds: rows.filter(function (r) { return r.innerText.indexOf('ai-') >= 0; }).length,
      modal: modalInfo
    };
  });
}

// ---------- 页面内探针 C：窄屏（移动端）不变量 ----------
function compactStatsProbe() {
  var me = { id: 'u1', username: 'z1w6qn', wins: 2, losses: 1, current_streak: 1, longest_streak: 2 };
  var history = [];
  for (var i = 0; i < 6; i++) {
    history.push({ winner_id: i % 3 === 2 ? 'u9' : 'u1', loser_id: i % 3 === 2 ? 'u1' : 'ai-x' + i,
                   winner_name: i % 3 === 2 ? 'charlie_u' : 'z1w6qn', loser_name: null,
                   timestamp: 1789201720 - i * 600, logs: [] });
  }
  var content = document.getElementById('user-stats-content');
  document.getElementById('user-stats-modal').classList.remove('hidden');
  content.innerHTML = window.renderUserStatsHTML(me, history, { hasMore: true });
  var modalBox = content.closest('.modal-content');
  var rows = [].slice.call(content.querySelectorAll('.match-history-btn'));
  var head = content.querySelector('.history-head');
  function overflow(el) { return Math.round(el.scrollWidth - el.clientWidth); }
  return {
    vw: window.innerWidth,
    headerHidden: head ? getComputedStyle(head).display === 'none' : null,
    modalOverflow: overflow(modalBox),
    bodyOverflow: document.documentElement.scrollWidth - window.innerWidth,
    rowOverflows: rows.map(overflow),
    timeOverflows: rows.map(function (r) { return overflow(r.querySelector('.hist-time')); }),
    resultVisible: rows.every(function (r) { return r.querySelector('.hist-result').getBoundingClientRect().width > 4; }),
    moreVisible: !!content.querySelector('.history-more')
  };
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
  if (COOKIE) {
    await send('Network.enable');
    const ok = await send('Network.setCookie', { name: 'session', value: COOKIE, url: new URL(APP).origin + '/' });
    console.log('已注入登录态 cookie: ' + JSON.stringify(ok));
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  await waitFor(async () => await ev('typeof window.renderUserStatsHTML === "function" && typeof window.renderMatchDetailHTML === "function"'), 20000, '战绩渲染函数就绪');

  const m = await ev('(' + statsProbe.toString() + ')()');
  console.log('历史行: ' + JSON.stringify(m.rowTexts, null, 0));
  console.log('表头列: ' + JSON.stringify(m.headCols));
  console.log('行背景: ' + JSON.stringify(m.rowBg) + ' 背景图: ' + JSON.stringify(m.rowBgImage));

  check(m.rowCount === 3, '渲染出 3 条历史记录', m.rowCount);
  check(m.tbodyButtons === 0, '没有 <button> 落在 <tbody> 里（否则会被解析器挪出表格）', m.tbodyButtons);
  check(m.headerExists && m.headerAboveRows && m.headerBeforeFirstRow,
    '表头位于数据行上方（原先 foster parenting 让它跑到列表最下面）',
    { exists: m.headerExists, above: m.headerAboveRows, domOrder: m.headerBeforeFirstRow });
  check(m.headCols.length === 3, '表头是三列（不再多出没有内容的「局内日志」列）', m.headCols);

  const aligned = m.rowCols.every((r) => r.length === 3
    && Math.abs(r[0].x - m.headCols[0].x) <= 2
    && Math.abs(r[2].right - m.headCols[2].right) <= 2);
  check(aligned, '表头与数据行的列宽逐列对齐', { head: m.headCols, first: m.rowCols[0] });

  check(m.rowBgImage.every((v) => v === 'none'), '历史行不再带通用 button 的渐变背景', m.rowBgImage);
  check(m.rowBg[0] !== m.rowBg[2] && m.rowBg[1] !== m.rowBg[2],
    '胜局与负局底色不同（此前三行全是蓝色）', m.rowBg);
  check(m.resultTexts.join('') === '胜胜负', '结果列顺序为 胜/胜/负', m.resultTexts);

  check(m.rowTexts[0].indexOf('电脑') >= 0 && m.rowTexts[0].indexOf('ai-4530c8') < 0,
    '人机对手显示为「电脑」而不是裸 ID', m.rowTexts[0]);
  check(m.hasAiTag, '人机对局带「人机」标签');
  check(m.hasNote, '存在人机不计入战绩的说明');

  check(m.detailOppWin === 'bravo_u', '赢的局「对手」显示对方而不是自己', m.detailOppWin);
  check(m.detailOppLose === 'charlie_u', '输的局「对手」显示对方', m.detailOppLose);
  check(m.detailOppAi.indexOf('电脑') >= 0, '人机局的「对手」显示为电脑', m.detailOppAi);

  // 窄屏（移动端）：三列装不下时必须降级为两行，且不产生水平溢出
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await sleep(400);
  const c = await ev('(' + compactStatsProbe.toString() + ')()');
  console.log('窄屏 ' + c.vw + 'px: 表头display=' + (c.headerHidden ? 'none' : 'shown') + ' 弹窗溢出=' + c.modalOverflow + ' 行溢出=' + JSON.stringify(c.rowOverflows));
  check(c.bodyOverflow <= 1, '窄屏下页面无水平溢出', c.bodyOverflow);
  check(c.modalOverflow <= 1, '窄屏下战绩弹窗无水平溢出', c.modalOverflow);
  check(c.rowOverflows.every(function (v) { return v <= 1; }), '窄屏下每条历史行不被内容撑破', c.rowOverflows);
  check(c.timeOverflows.every(function (v) { return v <= 1; }), '窄屏下时间列不被截断', c.timeOverflows);
  check(c.resultVisible, '窄屏下「结果」仍可见', c.resultVisible);
  check(c.moreVisible, '历史超过一页时有「加载更多」', c.moreVisible);
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });

  // 真实数据端到端：拿指定账号的 /user_stats 结果直接喂给页面渲染函数
  if (USERNAME) {
    const r = await ev('(' + realProbe.toString() + ')(' + JSON.stringify(USERNAME) + ')');
    console.log('真实数据 [' + USERNAME + ']: 胜场=' + r.wins + ' 负场=' + r.losses + ' 当前连胜=' + r.streak + ' 历史=' + r.rows);
    console.log('  ' + JSON.stringify(r.rowTexts));
    check(!r.error, '真实账号 ' + USERNAME + ' 有战绩数据', r.error);
    check(r.tbodyButtons === 0, '真实数据下没有 <button> 落在 <tbody> 里', r.tbodyButtons);
    check(r.headerAboveRows, '真实数据下表头仍在数据行上方', r.headerAboveRows);
    check(r.rawAiIds === 0, '真实数据下不出现裸 AI ID', r.rawAiIds);
    check(r.rows > 0 ? r.hasNote : true, '含人机对局时给出「不计入战绩」说明', r.hasNote);
  }

  // 真实入口接线：点导航栏的「个人战绩」必须能打开弹窗并渲染出内容。
  // 注意：该入口 <a id="show-user-stats"> 只在登录态渲染（index.html 的 {% if username %}），
  // 未登录访问时跳过这一步 —— 渲染链路本身已由上面的 fixture / 真实数据探针覆盖。
  const hasEntry = await ev('!!document.getElementById("show-user-stats")');
  if (hasEntry) {
    await ev('document.getElementById("user-stats-modal").classList.add("hidden")');
    await ev('document.getElementById("show-user-stats").click()');
    await sleep(1500);
    const w = await ev('(function(){var m=document.getElementById("user-stats-modal");var c=document.getElementById("user-stats-content");return {hidden:m.classList.contains("hidden"), text:(c.innerText||"").replace(/\\s+/g," ").trim().slice(0,60)};})()');
    console.log('入口接线: 弹窗隐藏=' + w.hidden + ' 内容="' + w.text + '"');
    check(w.hidden === false && w.text.length > 0, '点「个人战绩」能打开弹窗并渲染内容', w);
  } else {
    console.log('入口接线: 当前页面未登录（无 #show-user-stats），跳过点击检查');
  }

  if (SHOT) { const s = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(SHOT, Buffer.from(s.data, 'base64')); console.log('截图已保存: ' + SHOT); }
  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  console.log(NL + (problems.length ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL) : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
