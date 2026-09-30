#!/usr/bin/env node
/**
 * C+ 布船屏 · **定向检查**（W2 / A04 + W3）
 *
 * 覆盖的是 `confirmShipPlacement` 那套提交状态机，以及 W3 新加的三件东西
 * （六槽 / 清空 / 常驻确认）。这些行为**都不是"看一眼截图"能验的**：
 * 双击确认、ack 被拒、ack 永远不来、提交中再点棋盘 —— 全都要有确定的时序。
 *
 * 做法：在**页面里**把 `gameState.socket` 换成一个受控的假 socket ——
 *   · 记录每一次 emit（于是"双击只发一枪"可以直接数出来）
 *   · ack 由测试决定何时、以什么结果回调（hold / ok / reject / 永不回调）
 *   · `once` 注册的处理器留在表里，测试可以手动投递一个 room_sync
 * 这样既不依赖真实对局，也不碰产品代码；服务端契约（事件名、字段）仍按真实的那份写。
 *
 * 用法：node tools/cplus_deploy_check.mjs --url http://127.0.0.1:5097/
 * 退出码：0 全过；1 有 FAIL；2 SKIP（没有浏览器）。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..');
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = Number(argOf('--port', '9361'));
const SHOTS = argOf('--shots', '');
const KNOWN_BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const EDGE_EXPLICIT = argOf('--browser', '');
const EDGE = EDGE_EXPLICIT ? (fs.existsSync(EDGE_EXPLICIT) ? EDGE_EXPLICIT : null)
  : KNOWN_BROWSERS.find((p) => fs.existsSync(p));
const PROFILE = argOf('--profile', path.join(REPO, '.tmp', 'cplus-deploy', 'profile'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

if (!EDGE) {
  console.log('SKIP  没有找到可用的 Edge/Chrome —— 这**不是通过**，是未验收。');
  process.exit(2);
}
fs.mkdirSync(PROFILE, { recursive: true });
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
  '--user-data-dir=' + PROFILE, 'about:blank'], { stdio: 'ignore' });

/* 页面里装的假 socket 与一组探测器。整段作为字符串注入一次，之后各用例复用。 */
const HARNESS = `(function(){
  if (window.__deployHarness) return window.__deployHarness;
  var H = { emits: [], ackMode: 'hold', ackResult: null, handlers: {}, alerts: [] };
  window.__alerts = [];
  window.showAlert = function(t){ window.__alerts.push(String(t)); };
  window.showMessage = function(t){ window.__alerts.push(String(t)); };
  H.install = function(){
    H.emits = []; H.handlers = {};
    gameState.socket = {
      connected: true,
      emit: function(name, payload, cb){
        H.emits.push({ name: name, payload: payload });
        if (name === 'place_ships' && typeof cb === 'function') H.pendingAck = cb;
        return true;
      },
      once: function(name, fn){ H.handlers[name] = fn; },
      on: function(){}, off: function(){}, disconnect: function(){}
    };
    return H.emits.length;
  };
  /* 进屏：不造假业务数据，只把"已经在房间里、正在布船"这个前提摆好 —— 
     与 cplus_screens_check 的既有手法一致（切屏 + 初始化棋盘）。 */
  H.enter = function(maxShips){
    document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
    document.querySelectorAll('.modal-overlay').forEach(function(m){ m.classList.add('hidden'); });
    gameState.roomId = 'ROOM-TEST'; gameState.playerId = 'P-TEST';
    gameState.maxShips = maxShips || 6; gameState.placedShips = 0; gameState.ships = [];
    document.getElementById('ship-placement-screen').classList.add('active');
    initBoard(document.getElementById('player-board'), true);
    if (typeof newDeployPhase === 'function') newDeployPhase('test');
    document.getElementById('total-ships').textContent = gameState.maxShips;
    document.getElementById('placed-count').textContent = '0';
    updateDeployControls();
    H.install();
    return H.snapshot();
  };
  /* 点 n 个**还没放船**的格子（跳过已放置的）。
     ⚠️ 不能简单地"点前 n 个"：handleCellClick 对已放置的格是**撤回**，
        第一版就是这么写的 —— 先点了 5 格、再"点 6 个"会把前 5 格全撤掉，
        于是快照里只剩 1 格，看着像产品坏了，其实是工具点错了。 */
  H.clickCells = function(n, row){
    var cells = [].slice.call(document.querySelectorAll('#player-board .cell'))
      .filter(function(c){ return Number(c.dataset.y) === (row || 0); })
      .filter(function(c){ return !c.classList.contains('ship'); });
    var clicked = 0;
    for (var i = 0; i < n && i < cells.length; i++) { cells[i].click(); clicked++; }
    return clicked;
  };
  H.snapshot = function(){
    var b = document.getElementById('confirm-ships');
    var c = document.getElementById('clear-ships');
    var r = document.getElementById('random-ships');
    var h = document.getElementById('deploy-hint');
    var board = document.getElementById('player-board');
    var slots = [].slice.call(document.querySelectorAll('#deploy-slots .ax-slot'));
    return {
      ships: (gameState.ships || []).length,
      placed: gameState.placedShips,
      confirm: { present: !!b, disabled: b ? b.disabled : null, hidden: b ? b.classList.contains('hidden') : null },
      clear: { present: !!c, disabled: c ? c.disabled : null },
      random: { disabled: r ? r.disabled : null },
      hint: h ? h.textContent : null,
      slots: slots.length,
      slotsOn: slots.filter(function(s){ return s.classList.contains('on'); }).length,
      slotLabels: slots.map(function(s){ return s.textContent.trim(); }),
      boardLocked: board ? board.classList.contains('deploy-locked') : null,
      submitted: (typeof deploySubmitted !== 'undefined') ? deploySubmitted : null,
      pending: (typeof deployPending !== 'undefined') ? !!deployPending : null,
      emits: H.emits.map(function(e){ return e.name; }),
      alerts: window.__alerts.slice()
    };
  };
  window.__deployHarness = H;
  return H;
})()`;

console.log('== C+ 布船定向检查（A04 / W3）==');
console.log('   目标 ' + APP);

let ws = null;
let exitCode = 0;
try {
  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还没起来 */ }
    await sleep(500);
  }
  if (!target) { console.error('无法连接无头浏览器调试端口 ' + PORT); process.exit(3); }
  ws = new WebSocket(target.webSocketDebuggerUrl);
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
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
  });
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 400) };
    return r.result && r.result.value;
  };
  await send('Page.enable');
  await send('Runtime.enable');

  for (const [vlabel, w, h] of [['1440x900', 1440, 900], ['390x844', 390, 844]]) {
    console.log('');
    console.log('-- 视口 ' + vlabel + ' --');
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
    await send('Page.navigate', { url: APP });
    for (let i = 0; i < 60; i++) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break; await sleep(300); }
    await sleep(500);
    await ev(HARNESS);

    // ① 初始态：常驻 + 禁用 + 六槽空 + 清空禁用
    const s0 = await ev('(function(){ return window.__deployHarness.enter(6); })()');
    check(s0 && s0.confirm.present === true && s0.confirm.hidden === false,
      '[' + vlabel + '] 「确认放置」常驻（不再 hidden）', s0 && s0.confirm);
    check(s0 && s0.confirm.disabled === true, '[' + vlabel + '] 空棋盘时确认不可提交', s0 && s0.confirm);
    check(s0 && s0.slots === 6 && s0.slotsOn === 0, '[' + vlabel + '] 六槽是 6 格且全空', s0 && { slots: s0.slots, on: s0.slotsOn });
    check(s0 && s0.clear.disabled === true, '[' + vlabel + '] 空棋盘时「清空」禁用', s0 && s0.clear);
    check(s0 && /还差 6 格/.test(s0.hint || ''), '[' + vlabel + '] 状态行说明还差几格', s0 && s0.hint);

    // ② 五格：仍不可提交
    const s5 = await ev('(function(){ var H = window.__deployHarness; H.clickCells(5, 0); return H.snapshot(); })()');
    check(s5 && s5.slotsOn === 5 && s5.placed === 5, '[' + vlabel + '] 放 5 格：六槽亮 5 格', s5 && { on: s5.slotsOn, placed: s5.placed });
    check(s5 && s5.confirm.disabled === true, '[' + vlabel + '] 放 5 格时仍不可提交', s5 && s5.confirm);
    check(s5 && /还差 1 格/.test(s5.hint || ''), '[' + vlabel + '] 状态行说还差 1 格', s5 && s5.hint);

    // ③ 六格：可提交；六槽坐标从 gameState 派生（不是另一份状态）
    const s6 = await ev('(function(){ var H = window.__deployHarness; H.clickCells(1, 0); return H.snapshot(); })()');
    check(s6 && s6.slotsOn === 6 && s6.confirm.disabled === false, '[' + vlabel + '] 放满 6 格可提交', s6 && { on: s6.slotsOn, confirm: s6.confirm });
    check(s6 && s6.slotLabels.join('|') === '1,1|2,1|3,1|4,1|5,1|6,1',
      '[' + vlabel + '] 六槽显示的是 gameState 里那 6 个格子的坐标', s6 && s6.slotLabels);
    check(s6 && s6.clear.disabled === false, '[' + vlabel + '] 放满后「清空」可用', s6 && s6.clear);

    // ④ 清空：回到 0 格
    const sClear = await ev('(function(){ document.getElementById("clear-ships").click(); return window.__deployHarness.snapshot(); })()');
    check(sClear && sClear.placed === 0 && sClear.slotsOn === 0 && sClear.confirm.disabled === true,
      '[' + vlabel + '] 「清空」把棋盘与六槽一起归零', sClear && { placed: sClear.placed, on: sClear.slotsOn });

    // ⑤ 随机摆满：可提交（randomizeShips 走的是同一份 gameState）
    const sRand = await ev('(function(){ document.getElementById("random-ships").click(); return window.__deployHarness.snapshot(); })()');
    check(sRand && sRand.slotsOn === 6 && sRand.confirm.disabled === false,
      '[' + vlabel + '] 「随机摆放」之后六槽与确认同步就绪', sRand && { on: sRand.slotsOn, confirm: sRand.confirm });

    // ⑥ 双击确认：只发一枪
    const dbl = await ev(`(function(){
      var H = window.__deployHarness;
      var b = document.getElementById('confirm-ships');
      b.click(); b.click(); b.click();
      return H.snapshot();
    })()`);
    const placeEmits = (dbl.emits || []).filter((n) => n === 'place_ships').length;
    check(placeEmits === 1, '[' + vlabel + '] 连点三次确认只发出 1 个 place_ships', { emits: dbl.emits });
    check(dbl && dbl.pending === true, '[' + vlabel + '] 提交中：pending 已置上', dbl && { pending: dbl.pending });

    // ⑦ 提交中：棋盘 / 随机 / 清空 / 确认全锁
    const locked = await ev('(function(){ var H = window.__deployHarness;'
      + ' H.clickCells(1, 3); document.getElementById("random-ships").click();'
      + ' document.getElementById("clear-ships").click(); document.getElementById("confirm-ships").click();'
      + ' return H.snapshot(); })()');
    check(locked && locked.placed === 6, '[' + vlabel + '] 提交中点棋盘不改变布船', locked && { placed: locked.placed });
    check(locked && locked.random.disabled === true && locked.clear.disabled === true
      && locked.confirm.disabled === true, '[' + vlabel + '] 提交中随机/清空/确认都禁用',
      locked && { random: locked.random.disabled, clear: locked.clear.disabled, confirm: locked.confirm.disabled });
    check((locked.emits || []).filter((n) => n === 'place_ships').length === 1,
      '[' + vlabel + '] 提交中再点确认不会重发', locked && locked.emits);
    check(locked && locked.boardLocked === true, '[' + vlabel + '] 提交中棋盘有锁定样式（deploy-locked）', locked && locked.boardLocked);

    // ⑧ ack 成功 → 已提交、保持锁定、状态行改口
    const ackOk = await ev(`(function(){
      var H = window.__deployHarness;
      if (H.pendingAck) H.pendingAck({ status: 'success' });
      return H.snapshot();
    })()`);
    check(ackOk && ackOk.submitted === true && ackOk.pending === false,
      '[' + vlabel + '] ack 成功后进入"已提交"状态', ackOk && { submitted: ackOk.submitted, pending: ackOk.pending });
    check(ackOk && ackOk.confirm.disabled === true && /等待对手/.test(ackOk.hint || ''),
      '[' + vlabel + '] 已提交后仍锁着并提示等待对手', ackOk && { hint: ackOk.hint, confirm: ackOk.confirm.disabled });

    if (SHOTS) {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(SHOTS, 'deploy-' + vlabel + '.png'), Buffer.from(shot.data, 'base64'));
    }

    // ⑨ 被拒：恢复可修改
    const rejected = await ev(`(function(){
      var H = window.__deployHarness;
      H.enter(6); H.clickCells(6, 0);
      document.getElementById('confirm-ships').click();
      if (H.pendingAck) H.pendingAck({ status: 'error', message: '测试用的拒绝理由' });
      return H.snapshot();
    })()`);
    check(rejected && rejected.submitted === false && rejected.pending === false
      && rejected.confirm.disabled === false,
      '[' + vlabel + '] 被拒后解锁、可再次编辑与提交', rejected && { submitted: rejected.submitted, confirm: rejected.confirm.disabled });
    check(rejected && (rejected.alerts || []).some((t) => t.indexOf('测试用的拒绝理由') >= 0),
      '[' + vlabel + '] 被拒时把服务端给的原因转达给玩家', rejected && rejected.alerts);
    const canResubmit = await ev('(function(){ document.getElementById("confirm-ships").click();'
      + ' return window.__deployHarness.snapshot(); })()');
    check((canResubmit.emits || []).filter((n) => n === 'place_ships').length === 2,
      '[' + vlabel + '] 被拒之后确实能再提交一次（没有被永久锁死）', canResubmit && canResubmit.emits);

    // ⑩ 超时（ack 永不回调）：先同步房间状态，再决定能不能重试 —— 不许盲目重发
    const timedOut = await ev(`(function(){
      var H = window.__deployHarness;
      H.emits = []; H.handlers = {};
      gameState.socket = {
        connected: true,
        emit: function(name, payload){ H.emits.push({ name: name, payload: payload }); },
        once: function(name, fn){ H.handlers[name] = fn; },
        on: function(){}, off: function(){}, disconnect: function(){}
      };
      H.enter(6); H.clickCells(6, 0);
      document.getElementById('confirm-ships').click();
      return H.snapshot();
    })()`);
    check(timedOut && timedOut.pending === true, '[' + vlabel + '] 提交后 ack 未到：处于 pending', timedOut && { pending: timedOut.pending });
    await sleep(7000);   // DEPLOY_ACK_TIMEOUT_MS = 6000
    const afterTimeout = await ev('(function(){ return window.__deployHarness.snapshot(); })()');
    check((afterTimeout.emits || []).filter((n) => n === 'rejoin_room').length >= 1,
      '[' + vlabel + '] 超时后先发 rejoin_room 同步房间状态（而不是盲目重发 place_ships）',
      afterTimeout && afterTimeout.emits);
    check((afterTimeout.emits || []).filter((n) => n === 'place_ships').length === 1,
      '[' + vlabel + '] 超时后没有自动重发 place_ships', afterTimeout && afterTimeout.emits);

    // ⑪ 同步回来的事实是"还没开始" → 允许重试；是"已经推进" → 保持已提交
    const resyncFree = await ev(`(function(){
      var H = window.__deployHarness;
      if (H.handlers.room_sync) H.handlers.room_sync({ room_id: 'ROOM-TEST', current_phase: 'placing_ships' });
      return H.snapshot();
    })()`);
    check(resyncFree && resyncFree.pending === false && resyncFree.submitted === false
      && resyncFree.confirm.disabled === false,
      '[' + vlabel + '] 同步结果是"仍未提交"→ 解锁可重试', resyncFree && { pending: resyncFree.pending, submitted: resyncFree.submitted });
    /* "已经推进"这一档必须**等超时真的发生**再投递 room_sync：
       room_sync 的处理器是在 requestDeployResync() 里注册的，而它只在超时那一刻才跑。
       第一版在这里立刻投递，处理器还不存在，于是这条断言其实什么都没验到
       （"通过"的那一版也是同样的空转 —— 顺序反了的用例比没有用例更糟）。 */
    await ev(`(function(){
      var H = window.__deployHarness;
      H.enter(6); H.clickCells(6, 0);
      document.getElementById('confirm-ships').click();
      return true;
    })()`);
    await sleep(7000);
    const resyncDone = await ev(`(function(){
      var H = window.__deployHarness;
      var registered = !!H.handlers.room_sync;
      if (H.handlers.room_sync) H.handlers.room_sync({ room_id: 'ROOM-TEST', current_phase: 'rock_paper_scissors' });
      var s = H.snapshot();
      s.handlerRegistered = registered;
      return s;
    })()`);
    check(resyncDone && resyncDone.handlerRegistered === true,
      '[' + vlabel + '] 超时后 room_sync 的处理器确实注册上了（说明确实在等同步）', resyncDone && { registered: resyncDone.handlerRegistered });
    check(resyncDone && resyncDone.submitted === true && resyncDone.pending === false,
      '[' + vlabel + '] 同步结果是"已经推进"→ 保持已提交（不重发）',
      resyncDone && { submitted: resyncDone.submitted, emits: resyncDone.emits });
    const noResend = await ev('(function(){ document.getElementById("confirm-ships").click();'
      + ' return window.__deployHarness.snapshot(); })()');
    check((noResend.emits || []).filter((n) => n === 'place_ships').length === 1,
      '[' + vlabel + '] "已经推进"之后点确认也不会重发 place_ships', noResend && noResend.emits);

    // ⑫ 卡牌重摆（新部署阶段）：不能被"已经提交过"锁死
    const redeploy = await ev(`(function(){
      var H = window.__deployHarness;
      H.enter(6); H.clickCells(6, 0);
      document.getElementById('confirm-ships').click();
      if (H.pendingAck) H.pendingAck({ status: 'success' });
      var afterSubmit = H.snapshot();
      // 模拟 reset_gameboard（绝处逢生 / 回光返照那条路）
      gameState.ships = []; gameState.placedShips = 0;
      initBoard(document.getElementById('player-board'), true);
      newDeployPhase('test_redeploy');
      var afterRedeploy = H.snapshot();
      H.clickCells(6, 2);
      var placed = H.snapshot();
      document.getElementById('confirm-ships').click();
      return { afterSubmit: afterSubmit.submitted, afterRedeploy: afterRedeploy.submitted,
               confirmEnabled: placed.confirm.disabled === false,
               emits: H.emits.map(function(e){ return e.name; }) };
    })()`);
    check(redeploy && redeploy.afterSubmit === true && redeploy.afterRedeploy === false,
      '[' + vlabel + '] 新部署阶段会清掉"已提交"标记（卡牌重摆不被锁死）', redeploy);
    check(redeploy && redeploy.confirmEnabled === true
      && (redeploy.emits || []).filter((n) => n === 'place_ships').length === 2,
      '[' + vlabel + '] 重摆之后能再次提交（第二次 place_ships）', redeploy && redeploy.emits);

    // ⑬ 坐标：棋盘首行/首列有 1 起算的标签（::after/::before 的 content）
    const coords = await ev(`(function(){
      var H = window.__deployHarness; H.enter(6);
      function content(sel, pseudo){ var e = document.querySelector(sel); return e ? getComputedStyle(e, pseudo).content : null; }
      return { topLeft: content('#player-board .cell[data-y="0"], #player-board .cell[data-x="0"]', '::after'),
               colFirst: content('#player-board .cell[data-y="0"]', '::after'),
               rowFirst: content('#player-board .cell[data-x="0"]', '::before') };
    })()`);
    check(coords && coords.colFirst && /"1"|1/.test(coords.colFirst),
      '[' + vlabel + '] 棋盘首行有列坐标（1 起算）', coords);
    check(coords && coords.rowFirst && /"1"|1/.test(coords.rowFirst),
      '[' + vlabel + '] 棋盘首列有行坐标（1 起算）', coords);

    // ⑭ 手机档：棋盘可点（不被顶栏/按钮盖住）且主确认在视口内
    if (w < 600) {
      const mobile = await ev(`(function(){
        var hit = window.__deployHarness; hit.enter(6);
        var cell = document.querySelector('#player-board .cell[data-x="2"][data-y="2"]');
        var r = cell.getBoundingClientRect();
        var cx = Math.round(r.left + r.width / 2), cy = Math.round(r.top + r.height / 2);
        var top = document.elementFromPoint(cx, cy);
        var b = document.getElementById('confirm-ships');
        var br = b.getBoundingClientRect();
        var board = document.getElementById('player-board').getBoundingClientRect();
        return { cellOk: !!(top && (top === cell || cell.contains(top))),
                 blocker: top ? (top.tagName + (top.id ? '#' + top.id : '')) : null,
                 confirmInView: br.top >= 0 && br.bottom <= window.innerHeight && br.width > 0,
                 boardConfirmOverlap: Math.max(0, Math.min(br.right, board.right) - Math.max(br.left, board.left))
                   * Math.max(0, Math.min(br.bottom, board.bottom) - Math.max(br.top, board.top)),
                 confirmRect: { top: Math.round(br.top), bottom: Math.round(br.bottom) },
                 vh: window.innerHeight,
                 overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
      })()`);
      check(mobile && mobile.cellOk === true, '[390x844] 布船棋盘格子可点（没被顶栏/按钮挡住）', mobile);
      check(mobile && mobile.overflow <= 1, '[390x844] 布船屏没有横向溢出', mobile && { overflow: mobile.overflow });
      check(mobile && mobile.confirmInView === true, '[390x844] 主确认按钮在首屏视口内', mobile);
      check(mobile && mobile.boardConfirmOverlap === 0, '[390x844] 主确认按钮不遮住棋盘', mobile);
    }
  }

  check(jsProblems.length === 0, '全程零 JS 异常', jsProblems.slice(0, 4));

  console.log('');
  if (problems.length) {
    console.log('✗ ' + problems.length + ' 项未通过：');
    problems.slice(0, 40).forEach((p) => console.log('   · ' + p));
    exitCode = 1;
  } else {
    console.log('✓ 全部通过');
  }
} finally {
  try { if (ws) ws.close(); } catch (e) { /* 已断 */ }
  try { browser.kill(); } catch (e) { /* 已经退了 */ }
}
process.exit(exitCode);
