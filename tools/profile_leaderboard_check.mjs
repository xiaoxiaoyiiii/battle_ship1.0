#!/usr/bin/env node
/**
 * 个人信息 / 排行榜头像与跳转 回归检查（无头 Edge + CDP）
 *
 * 作者要求（2026-09-17）：
 *   10. 对局内点对手战绩 / 对手头像看到的个人信息要更详细
 *       （历史战绩、排行榜名次、头像、个性签名…）
 *   11. 排行榜里也要有头像，点名字或头像能跳到那个人的个人信息
 *
 * 数据源用桩：`/api/leaderboard` 与 `/user_stats` 都换成确定性的假响应，
 * 这样断言不依赖本机数据库里恰好有多少条战绩。
 *
 * 用法：
 *   node tools/profile_leaderboard_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9345;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = new URL('../.tmp/profile_leaderboard_profile', import.meta.url).pathname.replace(/^\//, '');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过个人信息检查'); process.exit(0); }

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

const BOARD = [
  { id: 'u1', username: 'z1w6qn', wins: 12, losses: 4, current_streak: 3, longest_streak: 6,
    avatar: '/static/avatars/u1_avatar.png' },
  { id: 'u2', username: 'bravo_u', wins: 7, losses: 9, current_streak: 0, longest_streak: 3,
    avatar: null },
];

const STATS = {
  stats: {
    id: 'u2', username: 'bravo_u', wins: 7, losses: 9, current_streak: 0, longest_streak: 3,
    signature: '今天也要赢一局', avatar: '/static/avatars/u2_avatar.png', rank: 7,
  },
  history: [
    { match_id: 1, winner_id: 'u2', loser_id: 'u1', winner_name: 'bravo_u', loser_name: 'z1w6qn',
      timestamp: 1789201720, logs: [{ ts: 1789201800, text: '第一回合 · 你获胜' }] },
    { match_id: 2, winner_id: 'u1', loser_id: 'u2', winner_name: 'z1w6qn', loser_name: 'bravo_u',
      timestamp: 1789200000, logs: [] },
  ],
};

const INSTALL_STUB = '(function(){' +
  ' window.__origFetch = window.fetch;' +
  ' var mk = function (obj) { return Promise.resolve({ ok: true, json: function () { return Promise.resolve(obj); } }); };' +
  ' window.fetch = function (url) {' +
  '   var u = String(url);' +
  '   if (u.indexOf("/api/leaderboard") === 0) return mk(' + JSON.stringify(BOARD) + ');' +
  '   if (u.indexOf("/user_stats") === 0) return mk(' + JSON.stringify(STATS) + ');' +
  '   return window.__origFetch.apply(this, arguments); };' +
  ' return "stubbed"; })()';

const BOARD_STATE = '(function(){' +
  ' var rows = [].slice.call(document.querySelectorAll("#leaderboard-table tbody tr"));' +
  ' var heads = [].slice.call(document.querySelectorAll("#leaderboard-table thead th")).map(function (t) { return t.textContent.trim(); });' +
  ' return { rows: rows.length, heads: heads,' +
  '   avatars: rows.map(function (r) { var i = r.querySelector(".leaderboard-avatar"); return i ? i.getAttribute("src") : null; }),' +
  '   users: rows.map(function (r) { var b = r.querySelector(".leaderboard-user"); return b ? b.dataset.username : null; }),' +
  '   texts: rows.map(function (r) { return r.innerText.replace(/\\s+/g, " ").trim(); }) }; })()';

const MODAL_STATE = '(function(){' +
  ' var modal = document.getElementById("opponent-stats-modal");' +
  ' var content = document.getElementById("opponent-stats-content");' +
  ' var q = function (sel) { return content.querySelector(sel); };' +
  ' var rows = [].slice.call(content.querySelectorAll(".user-stats-table tr")).map(function (tr) {' +
  '   return [].slice.call(tr.querySelectorAll("td")).map(function (td) { return td.textContent.trim(); }); });' +
  ' return { hidden: modal.classList.contains("hidden"),' +
  '   title: (document.getElementById("opponent-stats-title") || {}).textContent,' +
  '   hasHead: !!q(".profile-head"),' +
  '   avatar: (q(".profile-avatar") || {}).getAttribute ? q(".profile-avatar").getAttribute("src") : null,' +
  '   name: (q(".profile-name") || {}).textContent,' +
  '   signature: (q(".profile-signature") || {}).textContent,' +
  '   rank: (q(".profile-rank") || {}).textContent,' +
  '   rows: rows,' +
  '   historyRows: content.querySelectorAll(".match-history-btn").length }; })()';

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
      target = list.find((t) => t.type === 'page' && /^(https?|about|file):/.test(t.url || ''))
        || list.find((t) => t.type === 'page');
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
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete" && typeof fetchLeaderboard === "function"'), 20000, '页面加载');

  const stub = await ev(INSTALL_STUB);
  check(stub === 'stubbed', 'L0 桩掉 /api/leaderboard 与 /user_stats（确定性数据）', stub);

  // ---------- 排行榜 ----------
  await ev('(function(){ if (typeof showLeaderboard === "function") showLeaderboard(); else fetchLeaderboard(); return true; })()');
  await waitFor(async () => await ev('document.querySelectorAll("#leaderboard-table tbody tr").length') >= 2, 10000, '排行榜渲染');

  const b = await ev(BOARD_STATE);
  check(b && b.rows === 2, 'L1 排行榜渲染出全部行', b && b.rows);
  check(b && b.heads.length === 6 && b.heads[1] === '玩家', 'L2 表头仍 6 列（头像与名字同一格）', b && b.heads);
  check(b && b.avatars[0] === '/static/avatars/u1_avatar.png', 'L3 第一行显示该玩家的头像', b && b.avatars[0]);
  check(b && b.avatars[1] === '/static/avatars/default.png', 'L3b 没设头像时回退默认头像', b && b.avatars[1]);
  check(b && b.users[0] === 'z1w6qn' && b.users[1] === 'bravo_u', 'L4 每行都有可点的玩家按钮（带 data-username）', b && b.users);
  check(b && /z1w6qn/.test(b.texts[0] || ''), 'L4b 名字仍显示在头像旁', b && b.texts[0]);

  // 点头像/名字 → 打开个人信息
  const clicked = await ev('(function(){ var b = document.querySelectorAll("#leaderboard-table .leaderboard-user")[1]; if (!b) return "no-btn"; b.click(); return "clicked"; })()');
  await waitFor(async () => await ev('!document.getElementById("opponent-stats-modal").classList.contains("hidden")'), 10000, '个人信息弹窗打开');
  const m = await ev(MODAL_STATE);
  check(clicked === 'clicked', 'L5 点排行榜里的名字/头像', clicked);
  check(m && m.hidden === false, 'L5b 弹出个人信息弹窗（不再跳走页面）', m && !m.hidden);
  check(m && (m.title || '').indexOf('bravo_u') >= 0, 'L5c 弹窗标题写明是谁', m && m.title);
  check(m && m.hasHead === true, 'P1 有头像区块（.profile-head）', m && m.hasHead);
  // 注意：桩里的头像 URL 在本机并不存在，img 的 onerror 会把它换成默认头像，
  // 所以"用了服务端下发的 URL"要按纯渲染结果断言（不经过图片加载）。
  const rendered = await ev('(function(){ return window.renderUserStatsHTML(' + JSON.stringify(STATS.stats) + ', [], {}); })()');
  check(typeof rendered === 'string' && rendered.indexOf('/static/avatars/u2_avatar.png') >= 0,
    'P2 渲染时使用服务端下发的头像 URL', (rendered || '').indexOf('profile-avatar') >= 0);
  check(m && !!m.avatar && m.avatar.length > 0, 'P2b 头像 img 一定有个可用的 src（缺图时回退默认头像）', m && m.avatar);
  check(m && m.name === 'bravo_u', 'P3 显示用户名', m && m.name);
  check(m && m.signature === '今天也要赢一局', 'P4 显示个性签名', m && m.signature);
  check(m && (m.rank || '').indexOf('第 7 名') >= 0, 'P5 显示排行榜名次', m && m.rank);
  const rowMap = {};
  (m && m.rows || []).forEach((r) => { rowMap[r[0]] = r[1]; });
  check(rowMap['排行榜名次'] === '第 7 名', 'P6 信息表里有名次行', rowMap['排行榜名次']);
  check(rowMap['胜率'] === '44%', 'P7 信息表里有胜率行（7 胜 9 负 → 44%）', rowMap['胜率']);
  check(rowMap['胜场'] === '7' && rowMap['负场'] === '9', 'P8 胜负场仍在', { w: rowMap['胜场'], l: rowMap['负场'] });
  check(m && m.historyRows === 2, 'P9 带历史战绩列表', m && m.historyRows);

  // 历史行仍可点开对局详情
  const detailClick = await ev('(function(){ var b = document.querySelector("#opponent-stats-content .match-history-btn"); if (!b) return "no-btn"; b.click(); return "clicked"; })()');
  await sleep(300);
  const detailShown = await ev('(function(){ var el = document.getElementById("match-detail-content"); return { open: !document.getElementById("match-detail-modal").classList.contains("hidden"), text: el ? el.innerText.replace(/\\s+/g, " ").slice(0, 80) : "" }; })()');
  check(detailClick === 'clicked' && detailShown && detailShown.open, 'P10 历史行仍能点开对局详情', detailShown);

  if (SHOT) {
    await ev('(function(){ document.getElementById("match-detail-modal").classList.add("hidden"); return true; })()');
    await sleep(200);
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(png.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }

  // ---------- 对局内的入口 ----------
  await ev('(function(){ document.getElementById("opponent-stats-modal").classList.add("hidden");' +
    ' window.gameState = window.gameState || gameState; gameState.opponentName = "bravo_u"; return true; })()');
  const corner = await ev('(function(){ var c = document.getElementById("opponent-avatar-corner");' +
    ' return { exists: !!c, bound: c ? c.dataset.profileBound : null, title: c ? c.title : null }; })()');
  check(corner && corner.exists === true, 'G1 右上角对手头像容器存在', corner);
  check(corner && corner.bound === '1' && /个人信息/.test(corner.title || ''), 'G2 对手头像已绑定点开个人信息的入口', corner);
  await ev('(function(){ document.getElementById("opponent-avatar-corner").click(); return true; })()');
  await waitFor(async () => await ev('!document.getElementById("opponent-stats-modal").classList.contains("hidden")'), 10000, '点头像打开弹窗');
  const m2 = await ev(MODAL_STATE);
  check(m2 && m2.hasHead === true && (m2.rank || '').indexOf('第 7 名') >= 0,
    'G3 对局内点对手头像 → 同一份详细信息（含名次/头像/签名）', m2 && { rank: m2.rank, avatar: m2.avatar });

  // 「查看对手战绩」按钮走同一入口
  await ev('(function(){ document.getElementById("opponent-stats-modal").classList.add("hidden"); document.getElementById("show-opponent-stats").click(); return true; })()');
  await waitFor(async () => await ev('!document.getElementById("opponent-stats-modal").classList.contains("hidden")'), 10000, '按钮打开弹窗');
  const m3 = await ev(MODAL_STATE);
  check(m3 && m3.hasHead === true && m3.historyRows === 2, 'G4「查看对手战绩」按钮也走同一份详情',
    m3 && { head: m3.hasHead, rows: m3.historyRows });

  // ---------- 工具兼容：renderUserStatsHTML 收到精简对象也不能抛 ----------
  const lean = await ev('(function(){ var c = document.getElementById("user-stats-content");' +
    ' try { c.innerHTML = window.renderUserStatsHTML({ id: "x", username: "lean", wins: 1, losses: 0, current_streak: 1, longest_streak: 1 }, [], {}); }' +
    ' catch (e) { return "throw: " + e.message; }' +
    ' var img = c.querySelector(".profile-avatar");' +
    ' return { src: img ? img.getAttribute("src") : null, rank: (c.querySelector(".profile-rank") || {}).textContent || null,' +
    '   sig: (c.querySelector(".profile-signature") || {}).textContent || null, rows: c.querySelectorAll(".user-stats-table tr").length }; })()');
  check(typeof lean === 'object' && lean !== null, 'T1 renderUserStatsHTML 兼容精简数据（不抛异常）', lean);
  check(lean && lean.src === '/static/avatars/default.png', 'T2 缺 avatar 时回退默认头像', lean && lean.src);
  check(lean && lean.rows === 7, 'T3 信息表仍是 .user-stats-table（7 行）', lean && lean.rows);

  check(jsProblems.length === 0, '全程无 JS 异常 / console.error', jsProblems.slice(0, 4));
} catch (err) {
  console.error('检查中断: ' + err.message);
  problems.push('中断: ' + err.message);
} finally {
  try { if (ws) ws.close(); } catch (e) { /* ignore */ }
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
}

console.log('');
console.log(problems.length ? ('✗ ' + problems.length + ' 项未通过: ' + problems.join(' | ')) : '✓ 全部通过');
process.exit(problems.length ? 1 : 0);
