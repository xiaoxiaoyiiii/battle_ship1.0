#!/usr/bin/env node
/**
 * 连锁响应窗口「选目标」回归检查（无头 Edge + CDP）
 *
 * 覆盖的问题：`showChainRequestPrompt` 点速阶3卡后固定发 `targets: []`，
 * 而神威！/轰炸/冻结/硫磺火焰/探测雷达 的服务端分支缺目标会直接失败 ——
 * 等于这些卡在连锁响应窗口里根本打不出来。
 *
 * 修法：需要目标的卡先走目标选择器，确认后再把 targets 回填给 chain_response。
 * 本脚本用真实页面 + 真实 socket 监听器（`socket._callbacks['$chain_request']`）
 * 驱动这条链路，逐项断言，不依赖任何测试专用全局变量。
 *
 * 用法：
 *   node tools/chain_target_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
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
const PORT = 9335;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/chain_target_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过连锁目标检查'); process.exit(0); }

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

// 走完真实前端流程进入对局（人机对战）
async function enterGame() {
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="连锁检查"; document.getElementById("ai-match").click(); return true;})()');
  await waitFor(async () => await ev('document.getElementById("ship-placement-screen").classList.contains("active")'), 30000, '布船界面');
  await ev('document.getElementById("random-ships").click()');
  await sleep(400);
  await ev('document.getElementById("confirm-ships").click()');
  await waitFor(async () => await ev('document.getElementById("rps-screen").classList.contains("active")'), 30000, '猜拳界面');
  for (let i = 0; i < 5; i++) {
    await ev('document.querySelectorAll(".rps-choice")[0].click()');
    await sleep(3000);
    if (await ev('document.getElementById("game-screen").classList.contains("active")')) break;
  }
  await waitFor(async () => await ev('document.getElementById("game-screen").classList.contains("active")'), 20000, '对局界面');
  await sleep(800);
}

// 用真实监听器触发 chain_request（socket.io v4: socket._callbacks）
function fireChain(cards) {
  return '(function(){ var s = gameState.socket; var cbs = s && s._callbacks && s._callbacks["$chain_request"];' +
    ' if (!cbs || !cbs.length) return "no-handler";' +
    ' var payload = { speed3_cards: ' + JSON.stringify(cards) +
    ', card: { name: "无中生有", speed: 1, type: "普通", description: "对手刚打出的卡" },' +
    ' caster: "opponent-x", countdown: 10 };' +
    ' cbs.slice().forEach(function (f) { f(payload); }); return "ok"; })()';
}

const CLICK_CHAIN_ITEM = '(function(){ var el = document.querySelector(".chain-card-item"); if(!el) return "no-item"; el.click(); return "clicked"; })()';

function snapshotEmit() {
  return '(function(){ if (!window.__cap) return "no-cap";' +
    ' var last = window.__cap[window.__cap.length - 1] || null;' +
    ' return { count: window.__cap.length, last: last, events: window.__cap.map(function(c){return c.ev;}),' +
    '   pendingChainCard: !!gameState.pendingChainCard,' +
    '   pickers: document.querySelectorAll(".magic-target-prompt, #confirm-magic-ships, #area-confirm").length,' +
    '   chainItems: document.querySelectorAll(".chain-card-item").length }; })()';
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
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await enterGame();

  // 拦截 socket.emit，捕获前端真实发出的 payload
  const stub = await ev('(function(){ window.__cap = []; var s = gameState.socket;' +
    ' if (!s) return "no-socket"; s.emit = function (ev, data, cb) { window.__cap.push({ ev: ev, data: data }); if (typeof cb === "function") { try { cb({status:"success"}); } catch (e) {} } };' +
    ' return "stubbed"; })()');
  check(stub === 'stubbed', '成功拦截前端 emit（用于断言真实 payload）', stub);

  const hasHandler = await ev('(function(){ var cbs = gameState.socket._callbacks && gameState.socket._callbacks["$chain_request"]; return !!(cbs && cbs.length); })()');
  check(hasHandler === true, '页面注册了 chain_request 监听器（用真实监听器驱动，不依赖测试专用全局）', hasHandler);

  // ---------- A. 需要目标的卡：冻结（3x3 区域） ----------
  const a1 = await ev(fireChain([{ name: '冻结', speed: 3, type: '普通', description: '冻结 3x3 区域' }]));
  check(a1 === 'ok', 'A1 触发 chain_request（冻结）', a1);
  check(await ev('document.querySelectorAll(".chain-card-item").length') === 1, 'A2 弹出连锁选择框并列出速阶3卡');

  const a3 = await ev(CLICK_CHAIN_ITEM);
  check(a3 === 'clicked', 'A3 点击速阶3卡', a3);
  await sleep(300);
  const a4 = await ev(snapshotEmit());
  check(a4 && a4.pendingChainCard === true, 'A4 记住「连锁待选」状态，未直接发 chain_response', a4 && a4.events);
  check(a4 && a4.chainItems === 0, 'A5 连锁选择框已关闭');
  check(a4 && a4.pickers > 0, 'A6 弹出目标选择器（此前直接以 targets: [] 出牌）', a4 && a4.pickers);

  // 真实交互：先在对方棋盘点一格定位 3x3 区域，再点「确认」
  const a6b = await ev('(function(){ var cell = document.querySelector(\'#opponent-board .cell[data-x="1"][data-y="1"]\');' +
    ' if (!cell) return "no-cell"; cell.click(); var btn = document.getElementById("area-confirm");' +
    ' if (!btn) return "no-confirm"; if (btn.disabled) return "confirm-disabled"; btn.click(); return "confirmed"; })()');
  check(a6b === 'confirmed', 'A6b 真实点选棋盘上的 3x3 区域并点确认', a6b);
  await sleep(300);
  const a7 = await ev(snapshotEmit());
  const lastA = a7 && a7.last;
  check(!!lastA && lastA.ev === 'chain_response', 'A7 确认目标后发的是 chain_response（不是 use_magic_card）', lastA && lastA.ev);
  check(!!lastA && lastA.data && lastA.data.chain === true && lastA.data.card && lastA.data.card.name === '冻结',
    'A8 payload 带 chain:true 与所选卡牌', lastA && lastA.data && lastA.data.card);
  check(!!lastA && lastA.data && lastA.data.targets && lastA.data.targets.target_area
    && lastA.data.targets.target_area.x1 === 1 && lastA.data.targets.target_area.y1 === 1
    && lastA.data.targets.target_area.x2 === 3 && lastA.data.targets.target_area.y2 === 3,
    'A9 targets 里带上玩家点选的区域（点中的格子 = 区域左上角）', lastA && lastA.data && lastA.data.targets);
  check(a7 && a7.pendingChainCard === false, 'A10 结算后清理连锁待选状态');

  // ---------- B. 无需目标的卡：失灵！ ----------
  const pickersBeforeB = (await ev(snapshotEmit())).pickers;
  const b1 = await ev(fireChain([{ name: '失灵！', speed: 3, type: '普通', description: '无效化上一张' }]));
  check(b1 === 'ok', 'B1 触发 chain_request（失灵！）', b1);
  const b2 = await ev(CLICK_CHAIN_ITEM);
  await sleep(300);
  const b3 = await ev(snapshotEmit());
  const lastB = b3 && b3.last;
  check(!!lastB && lastB.ev === 'chain_response' && lastB.data && lastB.data.card && lastB.data.card.name === '失灵！',
    'B2 无目标卡仍直接响应连锁（不弹选择器）', lastB && lastB.data && lastB.data.card);
  check(b3 && b3.pickers <= pickersBeforeB && b3.pendingChainCard === false,
    'B3 无目标卡不弹选择器、不残留状态',
    { pickersBefore: pickersBeforeB, pickersAfter: b3 && b3.pickers, pending: b3 && b3.pendingChainCard });

  // ---------- C. 神之宣告：先选效果、再点选两艘自己船 ----------
  const c1 = await ev(fireChain([{ name: '神之宣告', speed: 3, type: '普通', description: '牺牲两艘' }]));
  check(c1 === 'ok', 'C1 触发 chain_request（神之宣告）', c1);
  const c2 = await ev(CLICK_CHAIN_ITEM);
  await sleep(300);
  // 注意：猜拳按钮也带 data-choice（rock/scissors/paper），必须限定在弹窗内查询
  const c3 = await ev('document.querySelectorAll(".divine-decree-options button[data-choice]").length');
  check(c2 === 'clicked' && c3 >= 2, 'C2 先弹出效果选择框', { click: c2, choices: c3 });

  await ev('document.querySelector(\'.divine-decree-options button[data-choice="2"]\').click()');
  await sleep(300);
  const c4 = await ev('(function(){ return { pending: !!gameState.pendingChainCard, ships: document.querySelectorAll("#confirm-magic-ships").length, selected: (gameState.currentMagicCard||{}).name }; })()');
  check(c4 && c4.ships === 1, 'C3 效果选完后弹出「点选两艘自己的战舰」', c4);

  const c4b = await ev('(function(){ var ships = (gameState.ships || []).slice(0, 2);' +
    ' if (ships.length < 2) return "no-ships";' +
    ' var cells = [];' +
    ' ships.forEach(function (sh) { var p = (sh.positions || [])[0]; if (p) cells.push(p); });' +
    ' if (cells.length < 2) return "no-cells";' +
    ' cells.forEach(function (pt) { var el = document.querySelector(\'#game-player-board .cell[data-x="\' + pt.x + \'"][data-y="\' + pt.y + \'"]\'); if (el) el.click(); });' +
    ' var btn = document.getElementById("confirm-magic-ships"); if (!btn) return "no-confirm"; btn.click(); return "confirmed"; })()');
  check(c4b === 'confirmed', 'C3b 真实点选两艘自己的战舰并确认', c4b);
  await sleep(300);
  const c5 = await ev(snapshotEmit());
  const lastC = c5 && c5.last;
  check(!!lastC && lastC.ev === 'chain_response' && lastC.data && lastC.data.card && lastC.data.card.name === '神之宣告',
    'C4 神之宣告在连锁窗口内也走 chain_response', lastC && lastC.data && lastC.data.card);
  check(!!lastC && lastC.data && lastC.data.targets && lastC.data.targets.effect_choice === 2
    && Array.isArray(lastC.data.targets.selected_cells) && lastC.data.targets.selected_cells.length === 2,
    'C5 同时带上 effect_choice 与 selected_cells', lastC && lastC.data && lastC.data.targets);
  check(await ev('gameState.pendingChainCard === null || gameState.pendingChainCard === undefined'), 'C6 状态已清理');

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
