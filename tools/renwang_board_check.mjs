#!/usr/bin/env node
/**
 * 仁王之盾「在自己棋盘上点船」回归检查（无头 Edge + CDP）
 *
 * 2026-09-17 改版：旧实现弹一个「选择船 1 (3,4) / 选择船 2 …」的按钮列表，
 * 玩家得自己从坐标里猜哪艘是哪艘。改为与克苏鲁之眼同一套交互 ——
 * 直接在自己棋盘上点绿色高亮的格子，选满 3 艘点确认。
 *
 * 断言（逐项打印 PASS/FAIL）：
 *   R1  弹出点选面板
 *   R2  存活的战舰格被标成可点（.pick-ship）
 *   R3  已沉的战舰格被灰掉（.pick-disabled）且点了不生效
 *   R4  连点 3 艘 → 计数 3/3 且确认按钮可用
 *   R5  点第 4 艘 → 提示「最多选择 3 艘战舰」，选择数不变
 *   R6  再点一次已选格 → 取消选择（计数回到 2）
 *   R7  确认 → emit confirm_magic_target，带 shield_choice 与正确的原始下标
 *   R8  面板与高亮类全部清干净
 *   R9  取消 → emit cancel_magic_selection（服务端待选择状态不会残留）
 *
 * 用法：
 *   node tools/renwang_board_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 *
 * 被检查的服务端必须放行该来源：
 *   PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 python server.py
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9341;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
// profile 固定放项目内 .tmp（C:/Windows/Temp 在本机出现过 ACL 损坏）
const PROFILE = new URL('../.tmp/renwang_board_profile', import.meta.url).pathname.replace(/^\//, '');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过仁王之盾选船检查'); process.exit(0); }

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

// 走真实流程进入对局（人机对战），拿到一份真实的 gameState.ships
async function enterGame() {
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="盾检查"; document.getElementById("ai-match").click(); return true;})()');
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
  await sleep(600);
}

// 把一艘船标成"已沉"，用来验证沉船格不可点（服务端也会跳过沉船）
const MARK_ONE_DEAD = '(function(){' +
  ' var ships = gameState.ships || [];' +
  ' if (ships.length < 2) return "too-few";' +
  ' ships[1].alive = false;' +
  ' var p = (ships[1].positions || [])[0];' +
  ' if (typeof initGameBoards === "function") initGameBoards();' +
  ' return p ? (p.x + "," + p.y) : "no-pos"; })()';

function cellSelector(xy) {
  const [x, y] = String(xy).split(',');
  return `#game-player-board .cell[data-x="${x}"][data-y="${y}"]`;
}

const ALIVE_CELLS = '(function(){' +
  ' var out = [];' +
  ' (gameState.ships || []).forEach(function (sh, idx) {' +
  '   if (sh.alive === false) return;' +
  '   var p = (sh.positions || [])[0]; if (p) out.push({ idx: idx, x: p.x, y: p.y }); });' +
  ' return out; })()';

const SELECTION_STATE = '(function(){' +
  ' var info = document.getElementById("renwang-info");' +
  ' var btn = document.getElementById("renwang-confirm");' +
  ' return { prompt: !!document.getElementById("renwang-prompt"),' +
  '   info: info ? info.textContent.trim() : null,' +
  '   confirmDisabled: btn ? btn.disabled : null,' +
  '   selected: document.querySelectorAll("#game-player-board .cell.pick-selected").length,' +
  '   pickShip: document.querySelectorAll("#game-player-board .cell.pick-ship").length,' +
  '   pickDisabled: document.querySelectorAll("#game-player-board .cell.pick-disabled").length,' +
  '   toast: (document.querySelector("#game-message-container .game-message") || {}).textContent || "" }; })()';

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
      // headless Edge 自带 edge://sync-confirmation-dialog 且排在最前，必须挑 http 页面
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
  await enterGame();

  const deadCell = await ev(MARK_ONE_DEAD);
  check(deadCell !== 'too-few' && deadCell !== 'no-pos', '准备：标记一艘已沉战舰用于反证', deadCell);

  const alive = await ev(ALIVE_CELLS);
  check(Array.isArray(alive) && alive.length >= 3, '准备：拿到至少 3 艘存活战舰', alive && alive.length);

  // 拦截 socket.emit，断言真实 payload
  const stub = await ev('(function(){ window.__cap = []; var s = gameState.socket;' +
    ' if (!s) return "no-socket"; s.emit = function (ev, data, cb) { window.__cap.push({ ev: ev, data: data }); if (typeof cb === "function") { try { cb({status:"success", message:"ok"}); } catch (e) {} } };' +
    ' return "stubbed"; })()');
  check(stub === 'stubbed', 'R0 拦截前端 emit（走真实函数、断言真实 payload）', stub);

  const opened = await ev('(function(){ try { showRenwangChoice(); return "opened"; } catch (e) { return "throw: " + e.message; } })()');
  check(opened === 'opened', 'R1 弹出仁王之盾点选面板', opened);

  const st0 = await ev(SELECTION_STATE);
  check(st0 && st0.prompt === true, 'R1b 面板存在（#renwang-prompt）', st0 && st0.prompt);
  check(st0 && st0.pickShip >= 3, 'R2 存活战舰格标成可点（.pick-ship）', st0 && st0.pickShip);
  check(st0 && st0.pickDisabled >= 1, 'R3 已沉战舰格被灰掉（.pick-disabled）', st0 && st0.pickDisabled);
  check(st0 && st0.confirmDisabled === true, 'R3b 一艘都没选时确认按钮禁用', st0 && st0.confirmDisabled);

  // 点沉船格：不应被选中
  const deadClick = await ev(`(function(){ var e = document.querySelector('${cellSelector(deadCell)}'); if (!e) return "no-cell"; e.click(); return document.querySelectorAll("#game-player-board .cell.pick-selected").length; })()`);
  check(deadClick === 0, 'R3c 点沉船格不生效（选中数仍为 0）', deadClick);

  // 连点 3 艘存活船
  for (let i = 0; i < 3; i++) {
    await ev(`(function(){ var e = document.querySelector('${cellSelector(alive[i].x + ',' + alive[i].y)}'); if (e) e.click(); return true; })()`);
  }
  const st3 = await ev(SELECTION_STATE);
  check(st3 && st3.selected === 3, 'R4 连点 3 艘都被选中', st3 && st3.selected);
  check(st3 && st3.confirmDisabled === false, 'R4b 选中后确认按钮可用', st3 && st3.confirmDisabled);
  check(st3 && /已选\s*3\s*\/\s*3/.test(st3.info || ''), 'R4c 面板实时显示已选 3 / 3', st3 && st3.info);

  // 点第 4 艘：必须被拒（至多 3 艘）
  const fourth = alive[3] || alive[0];
  await ev('(function(){ var c = document.querySelector("#game-message-container"); if (c) c.innerHTML = ""; return true; })()');
  await ev(`(function(){ var e = document.querySelector('${cellSelector(fourth.x + ',' + fourth.y)}'); if (e) e.click(); return true; })()`);
  const st4 = await ev(SELECTION_STATE);
  check(st4 && st4.selected === 3, 'R5 第 4 艘被拒（选中数仍是 3）', st4 && st4.selected);
  check(st4 && /最多选择\s*3\s*艘战舰/.test(st4.toast || ''), 'R5b 给出「最多选择 3 艘战舰」提示', st4 && st4.toast);

  // 再点一次已选格 → 取消
  const first = alive[0];
  await ev(`(function(){ var e = document.querySelector('${cellSelector(first.x + ',' + first.y)}'); if (e) e.click(); return true; })()`);
  const st5 = await ev(SELECTION_STATE);
  check(st5 && st5.selected === 2, 'R6 再点一次可取消选择（3 → 2）', st5 && st5.selected);

  // 把刚才取消掉的那艘补回来再确认，验证原始下标（此时应为 alive[0..2] 三艘）
  const third = alive[0];
  await ev(`(function(){ var e = document.querySelector('${cellSelector(third.x + ',' + third.y)}'); if (e) e.click(); return true; })()`);
  const expected = [alive[0].idx, alive[1].idx, alive[2].idx].sort((a, b) => a - b);
  const confirmed = await ev('(function(){ var b = document.getElementById("renwang-confirm"); if (!b) return "no-btn"; b.click(); return "clicked"; })()');
  check(confirmed === 'clicked', 'R7 点确认提交', confirmed);
  await sleep(300);

  const cap = await ev('(function(){ var last = window.__cap[window.__cap.length - 1] || null; return last; })()');
  check(!!cap && cap.ev === 'confirm_magic_target', 'R7b 发的是 confirm_magic_target', cap && cap.ev);
  check(!!cap && cap.data && cap.data.temp_data_id === 'shield_choice', 'R7c temp_data_id = shield_choice', cap && cap.data && cap.data.temp_data_id);
  const gotIdx = cap && cap.data && cap.data.target_data && cap.data.target_data.ship_indices;
  check(Array.isArray(gotIdx) && gotIdx.length === 3, 'R7d 带上 3 个 ship_indices', gotIdx);
  check(JSON.stringify((gotIdx || []).slice().sort((a, b) => a - b)) === JSON.stringify(expected),
    'R7e ship_indices 是 player.ships 的原始下标（与棋盘格子一一对应）', { got: gotIdx, expected });

  const st6 = await ev(SELECTION_STATE);
  check(st6 && st6.prompt === false, 'R8 确认后面板关闭', st6 && st6.prompt);
  check(st6 && st6.pickShip === 0 && st6.pickDisabled === 0 && st6.selected === 0,
    'R8b 棋盘上的可点/灰格/选中类全部清干净', st6 && { s: st6.pickShip, d: st6.pickDisabled, sel: st6.selected });

  // 取消路径
  await ev('(function(){ window.__cap = []; showRenwangChoice(); return true; })()');
  await ev(`(function(){ var e = document.querySelector('${cellSelector(alive[1].x + ',' + alive[1].y)}'); if (e) e.click(); return true; })()`);
  const cancelled = await ev('(function(){ var b = document.getElementById("renwang-cancel"); if (!b) return "no-btn"; b.click(); return "clicked"; })()');
  await sleep(200);
  const cap2 = await ev('(function(){ var last = window.__cap[window.__cap.length - 1] || null; return last; })()');
  check(cancelled === 'clicked', 'R9 点取消', cancelled);
  check(!!cap2 && cap2.ev === 'cancel_magic_selection', 'R9b 取消要向服务端释放待选择状态', cap2 && cap2.ev);
  const st7 = await ev(SELECTION_STATE);
  check(st7 && st7.prompt === false && st7.selected === 0, 'R9c 取消后同样清干净', st7 && { p: st7.prompt, sel: st7.selected });

  check(jsProblems.length === 0, '全程无 JS 异常 / console.error', jsProblems.slice(0, 4));

  if (SHOT) {
    await ev('(function(){ showRenwangChoice(); return true; })()');
    await sleep(300);
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(png.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }
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
