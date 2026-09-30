#!/usr/bin/env node
/**
 * C+ 十屏 · **一条连续路径**的跨屏验收（无头 Edge + CDP，双浏览器）
 *
 * 为什么单独一支（实施方案 §4 P5 的最后一条）：
 *   "跨屏验证从首页到大厅、部署、对局、结算、回放、返回首页的**完整路径**" ——
 *   其余工具都是**分段**覆盖（大厅归 lobby_check、部署→开局归 friend_invite_battle、
 *   结算→回放归 replay_check），没有一支把这条链**一次走完**。
 *   分段全绿 ≠ 拼接起来能走通：路径断点几乎总在"上一屏退出时没收尾"这类地方。
 *
 * 覆盖（一次会话，按真实按钮走）：
 *   ① 首页            #start-screen.active（C+ 首页标记在）
 *   ② → 大厅          导航 a[href="/lobby"] → #lobby-screen.active + 订阅就位 + 4 块面板
 *   ③ → 自定义房      A 用大厅的「创建房间」建房 → 拿到房号
 *   ④ → 部署          **B 在大厅的房间列表里点「加入」**（这就是"大厅 → 部署"那一段）
 *   ⑤ 部署            双方各 36 格 → 各摆 6 格 → 确认 → 双方进猜拳
 *   ⑥ → 对局          出拳定先后 → 双方 #game-screen.active → 攻方真开两炮
 *   ⑦ → 结算          守方投降（真实 `_finalize_match`）→ 双方 #game-over-screen.active
 *   ⑧ → 回放          结算「返回主菜单」→ 首页 → 个人战绩 → 历史第一条 → 小局详情 →
 *                     「对局回放」→ #replay-screen.active 且步骤数 > 0
 *   ⑨ → 返回首页      #replay-leave → #start-screen.active
 *
 * ⚠️ 收尾的"返回主菜单/退出回放"在本项目里是**整页重载**（`resetGame()` 里
 *    `window.location.href='/'`）—— 那是真实路径的一部分，不是工具在绕路。
 * ⚠️ 必须带 `ENABLE_TEST_EVENTS=1` 吗？**不需要**：这条路径只走真实动作
 *    （建房/加入/摆船/出拳/开炮/投降），一个调试事件都不发。
 *    这是刻意的 —— 它验的就是"玩家真能走通"，用桩就失去意义了。
 *
 * 用法：
 *   node tools/cplus_path_check.mjs --url http://127.0.0.1:5000/ [--shots <dir>]
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOTS = argOf('--shots', '');
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const TMP = path.join(HERE, '..', '.tmp');
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.log('找不到 Edge/Chrome，跳过（CI 环境正常）'); process.exit(0); }

const PW = 'cpluspath123456';
const SUFFIX = String(Date.now() % 1000000);
const USER_A = 'cpath_a' + SUFFIX;
const USER_B = 'cpath_b' + SUFFIX;

const problems = [];
const jsProblems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}
function step(n, text) { console.log('\n-- ' + n + '. ' + text + ' --'); }

function preClean(tag) {
  try {
    execSync('powershell -NoProfile -Command "' +
      'Get-CimInstance Win32_Process -Filter \"Name=\'msedge.exe\'\" | ' +
      'Where-Object { $_.CommandLine -like \'*' + tag + '*\' } | ' +
      'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
      { stdio: 'ignore', timeout: 20000 });
  } catch (e) { /* 没有残留就够了 */ }
}
function pickPage(list) {
  const isApp = (t) => t.type === 'page' && /^(https?|file):/.test(t.url || '');
  return list.find(isApp) || list.find((t) => t.type === 'page' && t.url !== 'about:blank'
    && !/^(edge|chrome|devtools):/.test(t.url || '')) || list.find((t) => t.type === 'page');
}

/* 两个实例各有自己的 --user-data-dir 与调试端口：共用一个 profile 时第二个浏览器
   会**静默起不来**，工具连上第一个实例，于是"两个玩家"其实是同一个人
   （lobby_check 的注释里记着这条，这里照抄）。 */
async function launch(tag, port) {
  preClean(tag);
  const profile = path.join(TMP, tag);
  fs.mkdirSync(profile, { recursive: true });
  const proc = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + port,
    '--user-data-dir=' + profile, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
      target = pickPage(list);
      if (target) break;
    } catch (e) { /* still starting */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口 ' + port);

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败 ' + port)); });
  let seq = 0;
  const pending = new Map();
  const dialogs = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    // ⚠️ 原生对话框（`confirm()`）会**阻塞**该页面的 Runtime.evaluate，直到有人应答 ——
    //    本项目「投降」就是 `if (!confirm('确定要投降吗？…'))`（static/game.js 的
    //    handleSurrender）。不自动应答的话，点了投降之后那次求值会一直挂到 20s 超时，
    //    工具报"timeout Runtime.evaluate"，看起来像服务端卡死。
    if (m.method === 'Page.javascriptDialogOpening') {
      dialogs.push(m.params && m.params.message ? String(m.params.message).slice(0, 80) : '(dialog)');
      send('Page.handleJavaScriptDialog', { accept: true }).catch(() => {});
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push(tag + ' JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 180));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      jsProblems.push(tag + ' console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 150));
    }
  };
  function send(method, params) {
    const id = ++seq;
    ws.send(JSON.stringify({ id: id, method: method, params: params || {} }));
    return new Promise((res, rej) => {
      pending.set(id, { res: res, rej: rej });
      setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
    });
  }
  async function ev(expression) {
    const r = await send('Runtime.evaluate', { expression: expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(tag + ' page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
    return r.result && r.result.value;
  }
  async function waitFor(fn, timeout, label) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      try { if (await fn()) return true; } catch (e) { /* keep polling */ }
      await sleep(200);
    }
    throw new Error(tag + ' 等待超时: ' + label);
  }
  async function shot(name) {
    if (!SHOTS) return;
    fs.mkdirSync(SHOTS, { recursive: true });
    const s = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOTS, tag + '-' + name + '.png'), Buffer.from(s.data, 'base64'));
  }
  return {
    tag: tag, ev: ev, send: send, waitFor: waitFor, shot: shot, dialogs: dialogs,
    close: () => {
      try { ws.close(); } catch (e) { /* ignore */ }
      try { proc.kill(); } catch (e) { /* ignore */ }
      preClean(tag);
    },
  };
}

// 页面里的状态探针（一次求值取全，避免多次往返之间状态漂移）
const SNAP = `(function(){
  function on(id){ var e = document.getElementById(id); return !!(e && e.classList.contains('active')); }
  return {
    screens: [].slice.call(document.querySelectorAll('.screen.active')).map(function(s){ return s.id; }),
    start: on('start-screen'), lobby: on('lobby-screen'), room: on('custom-room-screen'),
    placement: on('ship-placement-screen'), rps: on('rps-screen'), game: on('game-screen'),
    over: on('game-over-screen'), replay: on('replay-screen'),
    roomId: (window.gameState || {}).roomId || null,
    subscribed: (window.gameState || {}).lobbySubscribed || false,
    panels: document.querySelectorAll('#lobby-screen .lobby-panel').length,
    cells: document.querySelectorAll('#player-board .cell').length,
    confirmHidden: (function(){ var b = document.getElementById('confirm-ships');
      return b ? b.classList.contains('hidden') : null; })(),
    stepTotal: (document.getElementById('replay-step-total') || {}).textContent || null,
    result: (document.getElementById('game-result') || {}).textContent || null,
    historyRows: document.querySelectorAll('#user-stats-content .match-history-btn').length,
    visibility: (function(){ var out = {};
      ['user-stats-modal','match-detail-modal','opponent-stats-modal'].forEach(function(id){
        var e = document.getElementById(id); out[id] = !!(e && !e.classList.contains('hidden')); });
      return out; })()
  };
})()`;

const A = await launch('cplus_path_a', 9361);
const B = await launch('cplus_path_b', 9362);
let roomId = '';
try {
  console.log('=== C+ 十屏 · 一条连续路径（双浏览器，全走真实按钮）===');
  console.log('    A=' + USER_A + '  B=' + USER_B);

  // ---------- ① 首页 ----------
  step(1, '首页');
  for (const P of [A, B]) {
    await P.send('Page.enable');
    await P.send('Runtime.enable');
    await P.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await P.send('Page.navigate', { url: APP });
    await P.waitFor(async () => await P.ev('document.readyState === "complete" && typeof window.gameState === "object"'), 30000, '页面加载');
  }
  // 两个**不同**的登录身份（同一账号两个标签页会因为"房间容量按 user_id 计"而永远开不了局）
  for (const [P, name] of [[A, USER_A], [B, USER_B]]) {
    await P.ev('fetch("/register", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"},'
      + ' body:"username=' + name + '&password=' + PW + '"}).then(function(){return 1;})');
    await P.send('Page.navigate', { url: APP });
    await P.waitFor(async () => await P.ev('document.readyState === "complete" && typeof window.gameState === "object"'), 30000, '重载后页面就绪');
    await P.waitFor(async () => await P.ev('window.__USERNAME === "' + name + '"'), 20000, name + ' 登录态生效');
  }
  let sA = await A.ev(SNAP);
  check(sA.start === true, '① A 落在首页（#start-screen.active）', sA.screens);
  check(await A.ev('!!document.querySelector(".home-wrap") && !!document.getElementById("home-commander")'
    + ' && !!document.querySelector(".home-mid") && !!document.querySelector(".home-right")'),
    '① 首页的 C+ 三栏标记在（.home-wrap 的 左中右三栏 + #home-commander）');
  await A.shot('01-home');

  // ---------- ② 首页 → 大厅 ----------
  step(2, '首页 → 大厅（导航）');
  await A.ev('document.querySelector(\'a[href="/lobby"]\').click()');
  await B.ev('document.querySelector(\'a[href="/lobby"]\').click()');
  for (const P of [A, B]) {
    await P.waitFor(async () => (await P.ev(SNAP)).lobby === true, 15000, '进入大厅');
  }
  sA = await A.ev(SNAP);
  check(sA.lobby === true && sA.subscribed === true, '② 大厅激活且**订阅就位**（lobbySubscribed=true）',
    { screens: sA.screens, subscribed: sA.subscribed });
  check(sA.panels === 4, '② 四块面板都在（在线玩家/房间列表/进行中/公屏）', sA.panels);
  await A.shot('02-lobby');

  // ---------- ③ 大厅 → 建房 ----------
  step(3, 'A 用大厅的「创建房间」建房');
  await A.ev('(function(){ var n = document.getElementById("lobby-room-name"); if (n) n.value = "cplus路径房";'
    + ' document.getElementById("lobby-create-room").click(); return 1; })()');
  await A.waitFor(async () => { const s = await A.ev(SNAP); return s.room === true && !!s.roomId; }, 20000, 'A 进入自定义房等待面板');
  sA = await A.ev(SNAP);
  roomId = String(sA.roomId || '');
  check(!!roomId, '③ A 建出了房并拿到房号（gameState.roomId）', { roomId: roomId, screens: sA.screens });

  // ---------- ④ 大厅 → 部署（B 从房间列表加入） ----------
  step(4, 'B 在大厅的房间列表里点「加入」→ 双方进部署');
  await B.waitFor(async () => await B.ev('!!document.querySelector(\'#lobby-rooms-list .lobby-room-join[data-room="'
    + roomId + '"]\')'), 25000, 'B 的大厅列表出现这间房');
  check(true, '④ B 的大厅房间列表里真的出现了这间房（广播到了别人那边）', { roomId: roomId });
  await B.ev('document.querySelector(\'#lobby-rooms-list .lobby-room-join[data-room="' + roomId + '"]\').click()');
  for (const P of [A, B]) {
    await P.waitFor(async () => (await P.ev(SNAP)).placement === true, 30000, '进入布船屏');
  }
  check(true, '④ 双方经「大厅 → 房间 → 部署」进入布船屏（不是靠首页直达）');

  // ---------- ⑤ 部署 ----------
  /* ⚠️ 判据 2026-09-29 换过（W3 / A04）。旧判据是「摆满 6 格后 #confirm-ships
     从 hidden 变可见」；新约定是**确认按钮常驻**，可用性由 disabled 表达，
     不可用的原因写在旁边的 #deploy-hint 里（旧写法下按钮整块消失，
     玩家看不出是"没摆够"还是"卡住了"）。
     产品不变量没变、而且验得更细：
       · 没摆满 → 不能提交（disabled=true）
       · 摆满且数据合法 → 可以提交（disabled=false） */
  step(5, '双方各摆 6 格 → 确认');
  const place = (row) => '(function(){ var n = 0;'
    + ' document.querySelectorAll("#player-board .cell").forEach(function(c){'
    + '   if (Number(c.dataset.y) === ' + row + ' && n < 6) { c.click(); n++; } });'
    + ' var b = document.getElementById("confirm-ships");'
    + ' var h = document.getElementById("deploy-hint");'
    + ' return { clicked: n, ships: (window.gameState.ships || []).length,'
    + '          confirmDisabled: b ? b.disabled : null,'
    + '          confirmHidden: b ? b.classList.contains("hidden") : null,'
    + '          hint: h ? h.textContent : null }; })()';
  // 先记一次"没摆满时不能提交"，再摆满（同一屏，顺序不能反）
  const beforeA = await A.ev('(function(){ var b = document.getElementById("confirm-ships");'
    + ' var h = document.getElementById("deploy-hint");'
    + ' return { disabled: b ? b.disabled : null, hint: h ? h.textContent : null }; })()');
  check(beforeA && beforeA.disabled === true, '⑤ A 未摆满 6 格时「确认放置」不可提交', beforeA);
  const pa = await A.ev(place(0));
  const pb = await B.ev(place(5));
  check(pa.cells === undefined && pa.clicked === 6 && pa.confirmDisabled === false,
    '⑤ A 摆满 6 格后「确认放置」可提交（常驻 + disabled 表达可用性）', pa);
  check(pb.clicked === 6 && pb.confirmDisabled === false, '⑤ B 摆满 6 格后「确认放置」可提交', pb);
  check((await A.ev(SNAP)).cells === 36, '⑤ 布船棋盘 36 格', (await A.ev(SNAP)).cells);
  await A.shot('05-placement');
  await A.ev('document.getElementById("confirm-ships").click()');
  await B.ev('document.getElementById("confirm-ships").click()');
  for (const P of [A, B]) {
    await P.waitFor(async () => (await P.ev(SNAP)).rps === true, 30000, '进入猜拳');
  }

  // ---------- ⑥ 猜拳 → 对局 ----------
  step(6, '出拳定先后 → 双方进对局屏');
  // 不同手势一定有胜负：A 出剪刀、B 出石头 → A 赢（先手）。
  await A.ev('document.querySelector(\'.rps-choice[data-choice="scissors"]\').click()');
  await B.ev('document.querySelector(\'.rps-choice[data-choice="rock"]\').click()');
  for (const P of [A, B]) {
    await P.waitFor(async () => (await P.ev(SNAP)).game === true, 30000, '进入对局屏');
  }
  check(true, '⑥ 双方都进了对局屏（#game-screen.active）');
  await A.shot('06-game');

  // 攻方真开两炮（让回放里真的有行动步；也顺带验一下"对局屏能打"）
  const shots = await A.ev('(function(){ var cs = document.querySelectorAll("#opponent-board .cell");'
    + ' var fired = 0;'
    + ' for (var i = 0; i < cs.length && fired < 2; i++) { cs[i].click(); fired++; }'
    + ' return { fired: fired }; })()');
  check(shots.fired === 2, '⑥ 攻方在对手海域上真开了两炮（回放才有步骤可放）', shots);
  await sleep(1500);

  // ---------- ⑦ 对局 → 结算 ----------
  step(7, '守方投降 → 双方进结算屏（走真实 _finalize_match）');
  await B.ev('(function(){ var b = document.getElementById("surrender-btn"); if (b) b.click(); return 1; })()');
  for (const P of [A, B]) {
    await P.waitFor(async () => (await P.ev(SNAP)).over === true, 40000, '进入结算屏');
  }
  sA = await A.ev(SNAP);
  // `#over-head` 在 P4 之后带 C+ 判定徽记；这里顺带验它真的在
  // ⚠️ 判定文案在大字里是**带空格的**（game.js:2948 写的是 '胜 利' / '失 败' / '平 局'，
  //    那是排版选择不是缺陷）—— 判据要先把空白去掉再比对，否则专门为这个空格红一次。
  const verdict = String(sA.result || '').replace(/\s+/g, '');
  check(['胜利', '失败', '平局'].indexOf(verdict) >= 0, '⑦ 结算屏给出了判定文案（胜/负/平之一）',
    { raw: sA.result, normalized: verdict });
  check(await A.ev('!!document.querySelector("#game-over-screen .over-head")'),
    '⑦ 结算屏的 C+ 判定头在（.over-head）');
  await A.shot('07-result');

  // ---------- ⑧ 结算 → 首页 → 回放 ----------
  step(8, '结算「返回主菜单」→ 首页 → 个人战绩 → 历史 → 小局详情 → 对局回放');
  await A.ev('document.getElementById("return-to-menu").click()');
  await A.waitFor(async () => {
    const s = await A.ev(SNAP);
    return s.start === true;
  }, 40000, '整页重载后回到首页');
  check(true, '⑧ 结算「返回主菜单」回到首页（这一步在本项目里是整页重载，属真实路径）');
  await A.ev('document.getElementById("show-user-stats").click()');
  await A.waitFor(async () => (await A.ev(SNAP)).visibility['user-stats-modal'] === true, 15000, '战绩弹窗打开');
  await A.waitFor(async () => (await A.ev(SNAP)).historyRows > 0, 20000, '历史列表出现这一局');
  sA = await A.ev(SNAP);
  check(sA.historyRows > 0, '⑧ 个人战绩里出现了刚才那一局（真实战绩落库）', { rows: sA.historyRows });

  await A.ev('document.querySelectorAll("#user-stats-content .match-history-btn")[0].click()');
  await A.waitFor(async () => (await A.ev(SNAP)).visibility['match-detail-modal'] === true, 20000, '小局详情打开');
  const btn = await A.ev('(function(){ var b = document.getElementById("match-detail-content").querySelector(".match-replay-btn");'
    + ' return { present: !!b, disabled: b ? b.disabled : null }; })()');
  check(btn.present === true && btn.disabled === false, '⑧ 小局详情里「对局回放」按钮可点（has_replay 为真）', btn);
  await A.ev('document.getElementById("match-detail-content").querySelector(".match-replay-btn").click()');
  await A.waitFor(async () => (await A.ev(SNAP)).replay === true, 20000, '回放屏激活');
  await A.waitFor(async () => {
    const t = await A.ev('(function(){ return (document.getElementById("replay-step-total")||{}).textContent; })()');
    return !!t && t !== '0';
  }, 20000, '回放数据加载完成');
  sA = await A.ev(SNAP);
  check(sA.replay === true && !!sA.stepTotal && sA.stepTotal !== '0',
    '⑧ 回放屏激活且步骤数 > 0（回放真的能放）', { stepTotal: sA.stepTotal, screens: sA.screens });
  await A.shot('08-replay');

  // ---------- ⑨ 回放 → 首页 ----------
  step(9, '退出回放 → 返回首页');
  await A.ev('document.getElementById("replay-leave").click()');
  await A.waitFor(async () => (await A.ev(SNAP)).start === true, 20000, '退出回放回到首页');
  check(true, '⑨ 「退出回放」回到首页 —— 整条路径首尾闭合');

  check(jsProblems.length === 0, '全程零 JS 异常 / console.error（两个页面）', jsProblems.slice(0, 4));
  // 路径里出现的原生确认框（投降那次）如实记出来，不假装没发生
  const seen = A.dialogs.concat(B.dialogs);
  check(seen.length === 0 || seen.every((d) => /投降/.test(d)),
    '整条路径只出现一次原生确认框，且就是「投降」那一次', seen);
} catch (err) {
  check(false, '路径走通（中断：' + err.message + '）');
} finally {
  A.close();
  B.close();
}

console.log('');
if (problems.length) {
  console.log('✗ ' + problems.length + ' 项未通过：');
  problems.forEach((p) => console.log('   · ' + p));
  process.exit(1);
}
console.log('✓ 全部通过（首页 → 大厅 → 部署 → 对局 → 结算 → 回放 → 返回首页）');
process.exit(0);
