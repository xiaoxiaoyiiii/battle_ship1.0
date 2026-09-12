#!/usr/bin/env node
/**
 * 手牌「选中态」不残留 —— 无头 Edge + CDP 断言
 *
 * 覆盖的问题：`gameState.selectedCardIndex` 以前从不重置。
 *   · 出牌被拒后卡仍算「已选中」 → 下一次单击是【立刻重试】而不是先选中，
 *     提示连弹两遍，看起来像「重复投递」
 *   · 手牌一增一减，同一个下标就指向别的牌 → 那张牌被【自动标成选中】，
 *     点一下直接进出牌流程，少了一次确认
 *
 * 断言的是一条不变量：**任何会让选中失效的变化之后，selectedCardIndex 必须是 -1，
 * 且手牌里不能有任何一张带着 selected 类**。
 *
 * 用法：
 *   node tools/card_selection_check.mjs --url http://127.0.0.1:5000/
 *
 * 被检查的服务端必须放行该来源：
 *   PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 python server.py
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9336;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/card_selection_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过手牌选中态检查'); process.exit(0); }

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

// 走完真实前端流程进入对局（人机对战最快，不需要第二个人）
async function enterGame() {
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="选中态检查"; document.getElementById("ai-match").click(); return true;})()');
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

// 快照：选中下标 + 手牌里有没有带 selected 类的卡 + 手牌长度
const SNAP = '(function(){ return { idx: gameState.selectedCardIndex,'
  + ' key: gameState.selectedCardKey,'
  + ' selected: document.querySelectorAll("#magic-hand .magic-card.selected").length,'
  + ' hand: (gameState.hand||[]).length }; })()';

// 给手牌里塞一张确定的卡，避免依赖随机抽到什么
function giveCard(name, speed) {
  return '(function(){ gameState.hand.push({ name: ' + JSON.stringify(name) + ', speed: ' + speed
    + ', type: "普通", description: "测试用" }); updateHandUI(); return gameState.hand.length; })()';
}

function clickCard(name) {
  return '(function(){ var el = Array.prototype.slice.call(document.querySelectorAll("#magic-hand .magic-card"))'
    + '.filter(function(e){ return e.textContent.indexOf(' + JSON.stringify(name) + ') >= 0; })[0];'
    + ' if (!el) return "no-card"; el.click(); return "clicked"; })()';
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

  // 拦截出牌请求，避免真的把卡打出去影响后续断言
  const stub = await ev('(function(){ window.__cap = []; var s = gameState.socket;'
    + ' if (!s) return "no-socket"; s.emit = function (ev2, data, cb) { window.__cap.push(ev2);'
    + ' if (typeof cb === "function") { try { cb({status:"success"}); } catch (e) {} } }; return "stubbed"; })()');
  check(stub === 'stubbed', 'A0 成功拦截 emit（后续不真的出牌）', stub);

  // ---------- A. 单击只「选中」，不该触发任何请求 ----------
  await ev(giveCard('测试卡甲', 2));
  await ev(clickCard('测试卡甲'));
  await sleep(300);
  let s = await ev(SNAP);
  check(s.selected === 1 && s.idx >= 0, 'A1 单击卡牌 → 只进入选中态', s);
  check((await ev('window.__cap.length')) === 0, 'A2 单击不该发出任何 socket 请求');

  // ---------- B. 手牌变化（下标含义变了）→ 选中态必须作废 ----------
  const before = await ev(SNAP);
  await ev('(function(){ gameState.hand.shift(); updateHandUI(); return true; })()');
  await sleep(200);
  s = await ev(SNAP);
  check(s.idx === -1 && s.selected === 0,
    'B 手牌变化后选中态自动作废（不会让别的牌顶替成「已选中」）', { before: before, after: s });

  // ---------- C. 出牌被拒 → 选中态必须清掉，且再点一下只是重新选中 ----------
  // 把当前攻击者改成别人，让 canPlayCard 必然返回 false
  await ev('(function(){ gameState.__backupAttacker = gameState.currentAttacker;'
    + ' gameState.currentAttacker = "__not_me__"; return true; })()');
  await ev(giveCard('测试卡乙', 2));
  await ev(clickCard('测试卡乙'));           // 第一次：选中
  await sleep(200);
  await ev(clickCard('测试卡乙'));           // 第二次：尝试出牌 → 被拒
  await sleep(300);
  s = await ev(SNAP);
  check(s.idx === -1 && s.selected === 0, 'C1 出牌被拒 → 选中态清掉（这是「提示弹两遍」的根因）', s);

  const alertsBefore = await ev('window.__cap.length');
  await ev(clickCard('测试卡乙'));           // 只点一次
  await sleep(300);
  s = await ev(SNAP);
  check(s.selected === 1, 'C2 被拒后再单击 → 只是重新选中，不会立刻重试', s);
  check((await ev('window.__cap.length')) === alertsBefore,
    'C3 被拒后再单击不该再发一次请求（提示不会弹两遍）');

  await ev('(function(){ gameState.currentAttacker = gameState.__backupAttacker;'
    + ' clearCardSelection(); return true; })()');

  // ---------- D. 出牌成功 → 选中态必须清掉 ----------
  await ev(giveCard('测试卡丙', 2));
  await ev(clickCard('测试卡丙'));
  await sleep(150);
  await ev(clickCard('测试卡丙'));           // 真正出牌（emit 被拦，回调直接回 success）
  await sleep(400);
  s = await ev(SNAP);
  check(s.idx === -1 && s.selected === 0, 'D 出牌成功后选中态清掉（不会自动选中下一张）', s);

  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  console.log('');
  if (problems.length) {
    console.log('结果: ' + problems.length + ' 项不通过');
    problems.forEach((p) => console.log('  - ' + p));
    process.exit(1);
  }
  console.log('结果: 全部通过');
  process.exit(0);
}
