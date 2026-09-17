#!/usr/bin/env node
/**
 * 第 4 批「局内快捷语 / 表情」端到端回归检查（无头 Edge + CDP，真实双客户端）
 *
 * 依据：`docs/BATCH_2_3_4_PLAN.md` §4（需求 / 设计要点 / 冻结的快捷语表 §4.3 / DOM §4.4 / 本工具 §4.5）。
 *
 * 这一批要守住的四件事（作者需求里点名的就是前两件）：
 *   1. **「快点儿吧，我等的花都谢了」必须存在且逐字一致**（作者指定，一个字都不能错）；
 *   2. 快捷语**只发给对手 + 记进双方对局日志**，收到时对局界面别的部分一个字都不许变；
 *   3. **不打断回合流程**：发送前后 `attacks_remaining` / `state` / `current_phase` / `room.chain` 全都不变；
 *   4. 频率与白名单是**服务端**裁决（连点刷屏、越界 id 都不许发出去），不是前端灰一下。
 *
 * 文案**不信前端**：工具自己从 `GET /api/quick_chat` 拿一遍，再和页面上渲染出来的按钮文案、
 * 以及对手真的收到的那条 payload 逐字对比 —— 三处必须完全一致（前后端各写一份文案必然漂移）。
 *
 * 用法：
 *   node tools/quick_chat_check.mjs --url http://127.0.0.1:5000/
 *
 * ⚠️ 需要服务端带 `ENABLE_TEST_EVENTS=1`（读服务端真值要用 `test_get_game_state`）。
 *    本地跑法（隔离库）：
 *      $env:PORT='5000'; $env:CORS_ORIGINS='http://127.0.0.1:5000'
 *      $env:BATTLESHIP_DB_PATH="$PWD\.tmp\quick_chat_check.db"; $env:ENABLE_TEST_EVENTS='1'
 *      $env:TURN_TIMEOUT_SECONDS='0'; python server.py
 * ⚠️ 只注册**游客**房间（create_room/join_room），不写任何账号数据。
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
// `--size 390x844`：同一套断言换手机视口再跑一遍。
// 为什么需要：浮层在宽屏是"左下角浮标"、在紧凑/矮屏是**另一套定位**（另一组 CSS 分支），
// 只测 1600×1000 等于只测了其中一条分支 —— 本项目恰好在窄屏上翻过车
// （40px 触控目标塞不进紧凑阶段卡片，只能改成固定浮标）。
const SIZE = (argOf('--size', '1600x1000') || '1600x1000').split('x').map((n) => parseInt(n, 10));
const VIEW_W = SIZE[0] > 0 ? SIZE[0] : 1600;
const VIEW_H = SIZE[1] > 0 ? SIZE[1] : 1000;
const PORT = 9371;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(HERE, '..', '.tmp', 'quick_chat_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 作者指定的那句，**必须逐字一致**（契约 §4.3 的 hurry_flowers）
const REQUIRED_ID = 'hurry_flowers';
const REQUIRED_TEXT = '快点儿吧，我等的花都谢了';

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过快捷语检查'); process.exit(0); }

// 预清理：残留的无头 Edge 会占着调试端口 + 锁住 profile，新浏览器静默起不来
try {
  execSync('powershell -NoProfile -Command "' +
    'Get-CimInstance Win32_Process -Filter \\"Name=\'msedge.exe\'\\" | ' +
    'Where-Object { $_.CommandLine -like \'*quick_chat_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没残留就够了 */ }

const problems = [];
const jsProblems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

let browser = null;

async function openTab(url) {
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let seq = 0; const pend = new Map();
  ws.onmessage = (m) => {
    const x = JSON.parse(m.data);
    if (x.id && pend.has(x.id)) {
      const { res, rej } = pend.get(x.id); pend.delete(x.id);
      x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result);
      return;
    }
    if (x.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(x.params.exceptionDetails).slice(0, 200));
    if (x.method === 'Runtime.consoleAPICalled' && x.params.type === 'error') {
      jsProblems.push('console.error: ' + x.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
    }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const id = ++seq; pend.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + method)); } }, 25000);
  });
  await send('Runtime.enable');
  const ev = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 300) };
    return r.result && r.result.value;
  };
  return {
    ev, ws, id: t.id, send,
    /**
     * 把这一页切到前台。**凡是读几何 / 做命中测试 / 派发鼠标事件之前都必须先调它。**
     *
     * 本工具开了 3 个标签页，无头浏览器里**只有前台那个页有正常布局**：
     * 后台页会拿到 0×0 的 body（实测 `topDesc: BODY < HTML`、rect 全 0），
     * 于是 `getBoundingClientRect` / `elementFromPoint` 全是垃圾值 ——
     * 表现会是千奇百怪的假红（我先后看到过"面板尺寸 0"和"被 #magic-card-preview 压住"两种，
     * 其实都是同一个原因：那一页根本没被排版）。
     * 与本项目既有的记录一致：`priority_live_check.mjs` 的倒计时也栽在
     * "后台标签页被节流" 上，修法同样是先 bringToFront。
     */
    front: async () => { try { await send('Page.bringToFront'); } catch (e) {} await sleep(200); },
    ready: async () => {
      const t0 = Date.now();
      while (Date.now() - t0 < 20000) {
        if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true;
        await sleep(200);
      }
      return false;
    },
  };
}

/**
 * **真的点一下**：先做命中测试（元素中心点上最上面的是不是它），再用 CDP 派发真实鼠标事件。
 *
 * 为什么不能用 `el.click()`：它**完全绕过命中测试**，会直接调用元素的 click 处理器。
 * 于是「按钮被别的元素盖住 → 点在重叠处事件被上层接走 → 看着在、点不动」这类缺陷
 * 在 `el.click()` 下**永远测不出来**（本项目已栽过这个形状："工具全绿、线上全坏"）。
 * 第 4 批开工时就出现过一次真实的：回合标题的 h2 是 display:block 横跨整张阶段卡片（866px），
 * 把绝对定位的新按钮压住 64×30 —— 靠肉眼审查 CSS 才发现，`el.click()` 一点反应都没有。
 */
/**
 * **多点命中测试**：不只测中心，还测内缩 25% 的四个角。
 *
 * 为什么不能只测中心点：本项目记录过一种真实缺陷 —— 控件被**部分**盖住
 * （当时的实测描述就是"重叠 64×11"）。中心没被盖住、边缘被盖住时，
 * 只测中心的断言全绿，而玩家点在边缘那一片就是点不动。
 * 所以判据是"**五个采样点全部命中自己**"，任何一点被别人接走都算失败。
 */
async function hitTest(tab, selector) {
  await tab.front();
  return tab.ev(`(function () {
    var e = document.querySelector(${JSON.stringify(selector)});
    if (!e) return { missing: true };
    var r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return { zero: true, rect: { w: Math.round(r.width), h: Math.round(r.height) } };
    var pts = [
      ['center', r.left + r.width / 2, r.top + r.height / 2],
      ['tl', r.left + r.width * 0.25, r.top + r.height * 0.25],
      ['tr', r.left + r.width * 0.75, r.top + r.height * 0.25],
      ['bl', r.left + r.width * 0.25, r.top + r.height * 0.75],
      ['br', r.left + r.width * 0.75, r.top + r.height * 0.75]
    ];
    var bad = [];
    pts.forEach(function (p) {
      var top = document.elementFromPoint(p[1], p[2]);
      if (!(top === e || e.contains(top))) {
        bad.push(p[0] + '->' + (top ? (top.tagName + (top.id ? '#' + top.id : '') +
          (top.className ? '.' + String(top.className).split(' ')[0] : '')) : 'null'));
      }
    });
    return { total: pts.length, covered: bad.length, bad: bad,
      rect: { l: Math.round(r.left), t: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) } };
  })()`);
}

/**
 * 等"对手收到的条数"到齐，再断言**恰好等于**期望值。
 *
 * 为什么不能 `sleep(300)` 之后直接读：跨页面的 socket 投递是异步的，
 * 手机上（三标签页 + 小视口）实测会慢过 300ms —— 我因此吃过一次**假红**
 * （check 29 读到 2，而几百毫秒后的 check 30 读到 3，其实第三条只是还没到）。
 * 注意这里**只等"到齐或多于"**，最终仍然用 `=== expected` 断言：
 * 真出现重复/泄露（多于期望）时会被断言判红，不会被这个循环掩盖。
 */
async function settleCount(tab, expected, ms) {
  const t0 = Date.now();
  let last = -1;
  while (Date.now() - t0 < ms) {
    last = await tab.ev('(window.__qc || []).length');
    if (typeof last === 'number' && last >= expected) return last;
    await sleep(150);
  }
  return last;
}

async function realClick(tab, selector) {
  await tab.front();          // 几何与命中测试都要求这一页在前台（后台页是 0×0 布局）
  const box = await tab.ev(`(function () {
    var e = document.querySelector(${JSON.stringify(selector)});
    if (!e) return 'missing';
    e.scrollIntoView({ block: 'center' });
    var r = e.getBoundingClientRect();
    var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    var top = document.elementFromPoint(cx, cy);
    // 诊断信息：被挡住时要知道"到底是谁挡的、它是不是在浮层里、那个点还在不在浮层框内"
    var chain = [], n = top;
    for (var i = 0; i < 4 && n; i++) {
      chain.push(n.tagName + (n.id ? '#' + n.id : '') + (n.className ? '.' + String(n.className).split(' ')[0] : ''));
      n = n.parentElement;
    }
    var pr = null;
    try { var p = e.closest('#quick-chat-panel'); if (p) pr = p.getBoundingClientRect(); } catch (err) {}
    var tcs = top ? getComputedStyle(top) : null;
    return { x: cx, y: cy, w: r.width, h: r.height,
      rect: { l: Math.round(r.left), t: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
      panelRect: pr ? { l: Math.round(pr.left), t: Math.round(pr.top), w: Math.round(pr.width), h: Math.round(pr.height) } : null,
      pointInPanel: pr ? (cx >= pr.left && cx <= pr.right && cy >= pr.top && cy <= pr.bottom) : null,
      covered: !(top === e || e.contains(top)),
      topDesc: chain.join(' < '),
      topZ: tcs ? tcs.zIndex : null, topPE: tcs ? tcs.pointerEvents : null,
      topVis: tcs ? (tcs.display + '/' + tcs.visibility + '/op' + tcs.opacity) : null };
  })()`);
  if (!box || box === 'missing') return { ok: false, reason: '元素不存在' };
  if (box.w <= 0 || box.h <= 0) return { ok: false, reason: '尺寸为 0', box };
  await tab.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 });
  await tab.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 });
  return { ok: true, covered: box.covered, topDesc: box.topDesc, box };
}

// 把服务端推来的 quick_chat 原样记下来（照 hand_play_check 的做法裹一层 socket.onevent，
// 与"真的收到事件"等价，不依赖任何 UI 是否把它渲染出来了）
const HOOK = `(function () {
  if (!window.__qc) {
    window.__qc = [];
    var s = gameState.socket;
    var orig = s.onevent.bind(s);
    s.onevent = function (packet) {
      try {
        var name = packet && packet.data && packet.data[0];
        if (name === 'quick_chat') window.__qc.push(packet.data[1]);
      } catch (e) {}
      return orig(packet);
    };
  }
  return 'hooked';
})()`;

// 对局界面其他部分的"指纹"：收到快捷语前后必须一模一样
const FINGERPRINT = `(function () {
  var pick = function (sel) { var e = document.querySelector(sel); return e ? e.innerHTML.length + ':' + e.querySelectorAll('*').length : 'none'; };
  var phaseBtns = [].slice.call(document.querySelectorAll('.phase-btn, #enter-battle-phase, #end-turn-btn'))
    .map(function (b) { return (b.id || b.className) + '=' + (b.disabled ? 'd' : 'e'); }).join(',');
  return { board: pick('#game-opponent-board'), mine: pick('#game-player-board'),
    hand: pick('#magic-system'), phase: phaseBtns,
    phaseText: (document.getElementById('current-phase') || {}).textContent || '' };
})()`;

try {
  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=' + VIEW_W + ',' + VIEW_H, '--force-device-scale-factor=1',
    APP], { stdio: 'ignore' });
  await sleep(3500);

  const A = await openTab(APP);
  const B = await openTab(APP);
  const C = await openTab(APP);   // 房间外的第三个客户端：用来验"快捷语不会漏给外人"
  check(await A.ready() && await B.ready() && await C.ready(), '0 三个客户端都进到对局界面');

  // ---------- 1. 文案的单一来源：接口 ----------
  const cat = await A.ev(`fetch('/api/quick_chat').then(r => r.json()).catch(e => ({ __err: String(e) }))`);
  check(cat && cat.success === true && Array.isArray(cat.items) && cat.items.length >= 10,
    '★ 1 GET /api/quick_chat 返回快捷语表', cat && { n: (cat.items || []).length, groups: (cat.groups || []).length });
  const required = (cat.items || []).find((x) => x.id === REQUIRED_ID);
  check(!!required, '★ 2 表里有 ' + REQUIRED_ID, required);
  check(required && required.text === REQUIRED_TEXT,
    '★ 3 「' + REQUIRED_TEXT + '」逐字一致（作者点名的那句）', required && required.text);
  check(required && !!required.group, '4 它带分组（界面上要能归到一组）', required && required.group);
  const texts = (cat.items || []).map((x) => x.text);
  check(new Set(texts).size === texts.length, '5 表里没有重复文案', texts.length);

  // ---------- 2. 进房间（两个游客） ----------
  const created = await A.ev(`new Promise(function(res){
    ensureSocket(); gameState.playerName = 'QcA';
    gameState.socket.emit('create_room', { player_name: 'QcA' }, function(r){ res(r); });
  })`);
  const roomId = created && created.room_id;
  check(!!roomId, '6 建房成功', roomId);
  const joined = await B.ev(`new Promise(function(res){
    ensureSocket(); gameState.playerName = 'QcB';
    gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name: 'QcB' }, function(r){ res(r); });
  })`);
  const bPid = joined && joined.player_id;
  check(!!bPid, '7 对手入座', bPid);
  await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
  await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);

  const st0 = await A.ev(`new Promise(function(res){
    gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
  })`);
  const ok0 = st0 && st0.status === 'success' && st0.game_state;
  check(ok0, '8 能读到服务端真值（需要 ENABLE_TEST_EVENTS=1）', st0 && st0.status);
  const aPid = ok0 ? Object.keys(st0.game_state.players).find((p) => p !== bPid) : null;
  await A.ev(`gameState.playerId = ${JSON.stringify(aPid)}; true`);
  await B.ev(`gameState.playerId = ${JSON.stringify(bPid)}; true`);

  // 摆船 + 猜拳，进到「有攻击次数」的回合里 —— 这样「不消耗攻击次数」才验得出来
  const ships = (seed) => Array.from({ length: 6 }, (_, i) => ({ positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [] }));
  await A.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(aPid)}, ships: ${JSON.stringify(ships(0))} }, function(r){ res(r); }); })`);
  await B.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(bPid)}, ships: ${JSON.stringify(ships(1))} }, function(r){ res(r); }); })`);
  let attacker = null;
  for (let i = 0; i < 12 && !attacker; i++) {
    await A.ev(`new Promise(function(res){ gameState.socket.emit('rps_choice', { room_id: gameState.roomId,
      player_id: ${JSON.stringify(aPid)}, choice: 'rock' }, function(r){ res(r); }); })`);
    await B.ev(`new Promise(function(res){ gameState.socket.emit('rps_choice', { room_id: gameState.roomId,
      player_id: ${JSON.stringify(bPid)}, choice: 'paper' }, function(r){ res(r); }); })`);
    await sleep(400);
    const s = await A.ev(`new Promise(function(res){
      gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
    })`);
    attacker = s && s.game_state && s.game_state.current_attacker;
  }
  check(!!attacker, '9 猜拳分出先手（进到正常回合）', attacker);

  const readState = async (tab) => {
    const s = await tab.ev(`new Promise(function(res){
      gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
    })`);
    const g = (s && s.game_state) || {};
    return { state: g.state, phase: g.current_phase, attacks: g.attacks_remaining,
      chain: Array.isArray(g.chain) ? g.chain.length : (g.chain === undefined ? 'n/a' : g.chain),
      pending: !!g.pending_placement };
  };

  await A.ev(HOOK); await B.ev(HOOK); await C.ev(HOOK);
  const before = await readState(A);
  const fpBefore = await A.ev(FINGERPRINT);

  // ---------- 3. 面板与按钮（前端契约） ----------
  const btn = await A.ev(`!!document.getElementById('quick-chat-btn')`);
  check(btn === true, '★ 10 对局界面有 #quick-chat-btn 入口', btn);
  // 用**真实鼠标事件**点开（不是 el.click()）：顺带把"按钮被别的元素压住、点不动"这条一起验了
  const clickBtn = await realClick(A, '#quick-chat-btn');
  check(clickBtn.ok === true, '★ 10b 按钮可点（尺寸非 0；真实鼠标事件已派发）', clickBtn);
  check(clickBtn.covered === false,
    '★ 10c 按钮在最上层 —— 中心点上没有别的元素压着（"看着在、点不动"就是这么来的）',
    { covered: clickBtn.covered, top: clickBtn.topDesc });
  // 中心点绿不代表边缘绿：**五个采样点全部**必须命中按钮自己
  const btnHit = await hitTest(A, '#quick-chat-btn');
  check(btnHit && btnHit.total === 5 && btnHit.covered === 0,
    '★ 10d 按钮五个采样点（中心 + 四个角）全都没被压住（部分遮挡也要抓出来）', btnHit);
  await sleep(500);
  let panelOpened = await A.ev(`(function () { var p = document.getElementById('quick-chat-panel'); return !!(p && !p.hidden); })()`);
  // 真实点击没打开 → 再用合成 click 兜一次：两者结果不同本身就是诊断信息
  // （合成能开、真实开不了 = 命中测试/遮挡问题；两者都开不了 = 处理器问题）
  let opened = clickBtn.ok ? 'real-click' : 'no-click';
  if (!panelOpened) {
    opened = 'real-click-failed';
    await A.ev(`(function () { var b = document.getElementById('quick-chat-btn'); if (b) b.click(); return true; })()`);
    await sleep(400);
    panelOpened = await A.ev(`(function () { var p = document.getElementById('quick-chat-panel'); return !!(p && !p.hidden); })()`);
    if (panelOpened) opened = 'real-click-failed/synthetic-ok';
  }
  const panel = await A.ev(`(function () {
    var p = document.getElementById('quick-chat-panel');
    if (!p) return { missing: true };
    var items = [].slice.call(p.querySelectorAll('.quick-chat-item')).map(function (b) {
      return { id: b.dataset.msgId, text: b.textContent.trim() };
    });
    var r = p.getBoundingClientRect();
    return { hiddenAttr: p.hidden === true, visible: r.width > 0 && r.height > 0,
      modal: !!p.closest('.modal-overlay'), items: items,
      groups: [].slice.call(p.querySelectorAll('[data-group]')).map(function (g) { return g.dataset.group; }) }; })()`);
  check(panelOpened === true, '★ 11 点入口打开 #quick-chat-panel（真实鼠标点击）', { how: opened, panelOpened: panelOpened });
  check(panel && panel.visible === true, '12 面板真的可见（按尺寸判，不认哪个 class / 属性）', panel && { hiddenAttr: panel.hiddenAttr, visible: panel.visible });
  check(panel && panel.modal === false, '★ 13 面板**不是** .modal-overlay（全屏遮罩会挡棋盘）', panel && panel.modal);
  // ★ "非模态"的实际含义不是"没有 .modal-overlay 这个类名"，而是**棋盘照样点得到**。
  // 只查类名会被"自己写了个全屏遮罩"糊弄过去，所以这里直接在面板**开着**的时候
  // 拿棋盘中心点做命中测试：那一点上不能是面板（否则被盖住的格子就点不动了）。
  const boardHit = await A.ev(`(function () {
    // ⚠️ 棋盘容器的真实 id 是 #game-player-board / #opponent-board（第一版写成
    //    #game-opponent-board —— 那个 id 根本不存在，于是这里永远返回 'missing'，
    //    是**工具自己的 bug**，不是产品缺陷）。
    var board = document.getElementById('opponent-board') || document.getElementById('game-player-board');
    var panel = document.getElementById('quick-chat-panel');
    if (!board || !panel) return 'missing';
    var r = board.getBoundingClientRect();
    var top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { coveredByPanel: !!(top && panel.contains(top)),
      coveredByButton: (function () { var b = document.getElementById('quick-chat-btn');
        return !!(top && b && (top === b || b.contains(top))); })(),
      topDesc: top ? (top.tagName + (top.id ? '#' + top.id : '') + (top.className ? '.' + String(top.className).split(' ')[0] : '')) : 'null' }; })()`);
  check(boardHit && boardHit !== 'missing' && boardHit.coveredByPanel === false
    && boardHit.coveredByButton === false,
    '★ 13b 面板开着时**不挡棋盘**（棋盘中心点的命中结果不是浮层/按钮 —— 这才是"非模态"）', boardHit);
  // 浮层从右上角搬到左下角之后，风险就跟着搬到"左下角都住着谁"。
  // 棋盘中心**只是一个采样点**：日志 / 手牌 / 阶段按钮同样是玩家要点的东西，
  // 所以面板开着的时候把它们的中点也逐个扫一遍，任何一处被浮层或按钮接走都算失败。
  const spots = await A.ev(`(function () {
    var panel = document.getElementById('quick-chat-panel');
    var btn = document.getElementById('quick-chat-btn');
    var body = document.body.className || '';
    // 窄屏（compact/tight）下棋盘几乎铺满屏幕，任何像样的浮层都会压住它 ——
    // 这与"用全屏遮罩把整个界面锁住"是两码事（那是契约明令禁止的 .modal-overlay）。
    // 所以这里分开判：宽屏**一处都不许压**；窄屏允许压棋盘，但必须①不是遮罩②选完自动收（16b）
    // ③点外面/按 Esc 能关掉（下面 15c/15d 两条断言），否则玩家就被困在菜单里了。
    var narrow = /layout-compact|layout-tight/.test(body);
    var sels = [['日志', '#game-logs'], ['手牌', '#magic-system'],
                ['进战斗', '#enter-battle-phase'], ['结束回合', '#end-turn-btn'],
                ['对手棋盘', '#opponent-board'], ['我的棋盘', '#game-player-board']];
    var rows = sels.map(function (s) {
      var el = document.querySelector(s[1]);
      if (!el) return { name: s[0], state: '缺元素', isBoard: /棋盘/.test(s[0]) };
      var r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return { name: s[0], state: '不可见', isBoard: /棋盘/.test(s[0]) };
      var top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      var pr = panel.getBoundingClientRect();
      // 浮层与该控件矩形相交的面积占比（用来判断"压住"是擦边还是整个盖住）
      var ox = Math.max(0, Math.min(r.right, pr.right) - Math.max(r.left, pr.left));
      var oy = Math.max(0, Math.min(r.bottom, pr.bottom) - Math.max(r.top, pr.top));
      var ratio = Math.round((ox * oy) / (r.width * r.height) * 100);
      var state = (top && panel.contains(top)) ? ('被浮层盖(' + ratio + '%)')
        : ((top && btn && (top === btn || btn.contains(top))) ? '被按钮盖' : 'ok');
      return { name: s[0], state: state, isBoard: /棋盘/.test(s[0]) };
    });
    return { narrow: narrow, rows: rows }; })()`);
  const rows = (spots && spots.rows) || [];
  const badRows = rows.filter((r) => {
    if (!/被浮层盖|被按钮盖/.test(r.state)) return false;
    // 窄屏下"压住棋盘"是允许的（见上面的说明），其余一律算失败
    if (spots.narrow && r.isBoard) return false;
    return true;
  });
  check(rows.length > 0 && badRows.length === 0,
    '★ 13c 面板开着时没压住关键控件（窄屏允许压棋盘，但必须可关闭 —— 见 15c/15d）',
    { narrow: spots && spots.narrow, rows: rows, bad: badRows });
  check(panel && panel.items.length === (cat.items || []).length,
    '★ 14 面板条目数 = 接口下发的条目数（文案来自接口，不是前端写死）', panel && { dom: panel.items.length, api: (cat.items || []).length });
  const domReq = panel && panel.items.find((x) => x.id === REQUIRED_ID);
  check(domReq && domReq.text === REQUIRED_TEXT,
    '★ 15 页面上那句「' + REQUIRED_TEXT + '」与接口逐字一致', domReq && domReq.text);
  // 入口按钮的可访问状态：契约里要求它是"可展开"的开关
  const ariaOpen = await A.ev(`(function () { var b = document.getElementById('quick-chat-btn');
    return b ? b.getAttribute('aria-expanded') : 'no-btn'; })()`);
  check(ariaOpen === 'true', '★ 15b 打开后 #quick-chat-btn 的 aria-expanded 变 "true"', ariaOpen);

  // ---------- 4. 发一条（作者点名的那句）—— 同样用真实鼠标事件 ----------
  const itemSel = '#quick-chat-panel .quick-chat-item[data-msg-id=' + JSON.stringify(REQUIRED_ID) + ']';
  const itemHit = await hitTest(A, itemSel);
  check(itemHit && itemHit.total === 5 && itemHit.covered === 0,
    '★ 16a 该条目的五个采样点全都没被压住（部分遮挡会让玩家点边缘没反应）', itemHit);
  const clickItem = await realClick(A, itemSel);
  check(clickItem.ok === true && clickItem.covered === false,
    '★ 16 点「' + REQUIRED_TEXT + '」（真实鼠标事件，且该按钮没被面板内其他元素压住）', clickItem);
  if (clickItem.ok !== true || clickItem.covered === true) {
    await A.ev(`(function () { var b = document.querySelector('#quick-chat-panel .quick-chat-item[data-msg-id=${JSON.stringify(REQUIRED_ID)}]');
      if (b) b.click(); return true; })()`);
  }
  await sleep(900);
  // 点完一条要自动收起（否则浮层一直盖在棋盘上）—— 这也是"面板不该挡住对局"的一部分
  const closedAfterSend = await A.ev(`(function () { var p = document.getElementById('quick-chat-panel');
    if (!p) return 'missing';
    var r = p.getBoundingClientRect();
    return { hiddenAttr: p.hidden === true, visible: r.width > 0 && r.height > 0 }; })()`);
  check(closedAfterSend && closedAfterSend !== 'missing' && closedAfterSend.visible === false,
    '★ 16b 发完一条后面板自动收起（不再盖着棋盘）', closedAfterSend);

  // 窄屏下浮层**允许**压住棋盘（棋盘铺满屏幕，压不住是不可能的），
  // 但前提是玩家**关得掉** —— 否则就被困在菜单里了。这两条是 13c 放宽的交换条件，
  // 少了它们，13c 的放宽就变成了"把不方便的断言删掉"。
  const panelVisible = () => A.ev(`(function () { var p = document.getElementById('quick-chat-panel');
    if (!p) return 'missing'; var r = p.getBoundingClientRect();
    return r.width > 0 && r.height > 0; })()`);
  const reopen = async () => {
    await realClick(A, '#quick-chat-btn');
    await sleep(400);
    return panelVisible();
  };
  // 16c：点浮层外面应当收起。
  // ⚠️ "外面"要挑一个**公平**的点：视口最角落可能根本不在 app 容器里（点是点到了，
  //    但那种点的语义和"玩家点界面别处"不一样）。所以这里在 game-screen 里取若干候选点，
  //    挑第一个**确实落在浮层之外**的点来点。
  const open1 = await reopen();
  const outside = await A.ev(`(function () {
    var panel = document.getElementById('quick-chat-panel');
    var pr = panel.getBoundingClientRect();
    var host = document.getElementById('game-screen') || document.querySelector('.game-content') || document.body;
    var hr = host.getBoundingClientRect();
    var cands = [
      [hr.left + hr.width / 2, hr.top + hr.height / 2],
      [hr.left + hr.width * 0.75, hr.top + hr.height * 0.5],
      [hr.left + hr.width * 0.5, hr.top + hr.height * 0.85],
      [hr.left + hr.width * 0.85, hr.top + hr.height * 0.8],
      [hr.left + hr.width * 0.15, hr.top + hr.height * 0.5]
    ];
    for (var i = 0; i < cands.length; i++) {
      var x = cands[i][0], y = cands[i][1];
      if (x < 2 || y < 2 || x > window.innerWidth - 2 || y > window.innerHeight - 2) continue;
      if (x >= pr.left && x <= pr.right && y >= pr.top && y <= pr.bottom) continue;
      var top = document.elementFromPoint(x, y);
      if (top && panel.contains(top)) continue;
      return { x: x, y: y, topDesc: top ? (top.tagName + (top.id ? '#' + top.id : '')) : 'null' };
    }
    return null; })()`);
  if (outside) {
    await A.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: outside.x, y: outside.y, button: 'left', clickCount: 1 });
    await A.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: outside.x, y: outside.y, button: 'left', clickCount: 1 });
    await sleep(400);
  }
  const afterOutside = await panelVisible();
  check(open1 === true && !!outside && afterOutside === false,
    '★ 16c 点浮层外面（界面别处）能把它关掉（不会被困在菜单里）',
    { opened: open1, outside: outside, afterOutsideClick: afterOutside });
  // 16d：按 Esc 也应当收起（先确保它是开着的，别把上一条的残留状态当成结论）
  let open2 = await panelVisible();
  if (open2 !== true) open2 = await reopen();
  await A.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await A.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(400);
  const afterEsc = await panelVisible();
  check(open2 === true && afterEsc === false, '★ 16d 按 Esc 能关掉浮层', { opened: open2, afterEsc: afterEsc });

  await B.front();
  const gotB = await B.ev('window.__qc || []');
  check(gotB && gotB.length === 1, '★ 17 对手**收到了**这条快捷语（且只收到一条）', gotB && gotB.length);
  const recv = (gotB || [])[0] || {};
  check(recv.msg_id === REQUIRED_ID && recv.text === REQUIRED_TEXT,
    '★ 18 收到的 payload 文案逐字一致（三处一致：接口 / 页面 / 对手收到的）', { id: recv.msg_id, text: recv.text });
  check(!!recv.player_id && !!recv.name, '19 payload 带发送者身份与名字', { pid: !!recv.player_id, name: recv.name });
  await A.front();
  const gotA = await A.ev('window.__qc || []');
  // ⚠️ 契约 §4.3 是「广播给房间双方」：发送方自己也收一份，前端靠 player_id 认出"这条是我发的"。
  // （第一版这里断言"发送方收不到"，是照 §4.1 那句「只发给对手」的字面读法写的 —— 文档自相矛盾，
  //   已按 §4.2/§4.3 收敛口径。真正要守的是**不泄露给房间外**，见 20b。）
  check(gotA && gotA.length === 1 && gotA[0].player_id === aPid,
    '20 发送方自己也收到一份（广播给双方），且 player_id 是发送者（前端据此标成"我发的"）',
    gotA && gotA.map((x) => x.player_id));
  await C.front();
  const gotC = await C.ev('window.__qc || []');
  check(gotC && gotC.length === 0,
    '★ 20b 房间外的第三个客户端**一条都收不到**（"只发给对手"= 不泄露给外人）', gotC && gotC.length);

  // ⚠️ 判据是「**恰好 1 次**」，不是 `indexOf >= 0`。服务端同时做了两件事：广播 quick_chat、
  // 又把 game_log 推给房间 —— 两个 handler 各插一条日志就是**重复两行**（后端 agent 实测到的真缺陷）。
  // 只断言"能找到这句话"是抓不到重复的（第一版就是这么写的，属于假绿）。
  const logCount = (tab) => tab.ev(`(function () {
    var box = document.getElementById('game-logs');
    if (!box) return -1;
    var t = box.textContent || '';
    return t.split(${JSON.stringify(REQUIRED_TEXT)}).length - 1; })()`);
  const logsB = await logCount(B);
  check(logsB === 1, '★ 21 对手的对局日志里**恰好 1 行**（不是 0 行、也不是重复 2 行）', logsB);
  const logsA = await logCount(A);
  check(logsA === 1, '★ 22 发送方自己的日志里也恰好 1 行（回显不许再加一条）', logsA);
  // 服务端那条日志走的是既有的 game_log push → renderServerLog；它的 type 是 quick_chat，
  // 映射表里漏了就会渲染成「信息」徽标（不该出现"快捷语被标成信息"这种张冠李戴）。
  const badgeText = await B.ev(`(function () { var box = document.getElementById('game-logs');
    return box ? (box.textContent || '').indexOf('快捷语') >= 0 : 'no-box'; })()`);
  check(badgeText === true, '★ 22b 日志里带「快捷语」标识（game_log 的 type 有映射，不是「信息」）', badgeText);
  const toast = await B.ev(`(function () { var t = document.getElementById('quick-chat-toast');
    if (!t) return 'no-el';
    var r = t.getBoundingClientRect(); var cs = getComputedStyle(t);
    return { hiddenAttr: t.hidden === true,
      // 四种"看不见"的写法全都要算进去：hidden 属性 / display:none / visibility:hidden / opacity:0。
      // 本条实测用的是「opacity:0 + visibility:hidden」+ .is-show 切换（style.css §26），
      // 只认 hidden 属性或 class 都会假绿。
      visible: r.width > 0 && r.height > 0 && cs.display !== 'none'
        && cs.visibility !== 'hidden' && cs.opacity !== '0',
      text: (t.textContent || '').trim() }; })()`);
  // ⚠️ 判据必须是**真的可见**（尺寸 + computed style），不能只看某个 class / 属性：
  // 元素既可能用 `hidden` 属性隐藏、也可能用 `.hidden` 类，认错一个就是**假绿**
  // （本工具第一版读的是 classList，而实现用的是 `hidden` 属性 → 即使提示从没出现过也会 PASS）。
  check(toast && toast !== 'no-el' && toast.visible === true && toast.text.indexOf(REQUIRED_TEXT) >= 0,
    '★ 23 对手那边真的弹出了 #quick-chat-toast（可见）且含这句', toast);

  // ---------- 5. 不打断回合流程 ----------
  const after = await readState(A);
  check(after.state === before.state && after.phase === before.phase,
    '★ 24 发送前后 state / current_phase 完全不变', { before: before, after: after });
  check(after.attacks === before.attacks, '★ 25 攻击次数没有变（发快捷语不消耗回合资源）', { before: before.attacks, after: after.attacks });
  check(after.chain === 0 || after.chain === 'n/a', '★ 26 没有打开连锁窗口（room.chain 仍为空）', after.chain);
  check(after.pending === false, '27 没有产生任何待处理状态', after.pending);

  await A.front();
  const fpAfter = await A.ev(FINGERPRINT);
  check(JSON.stringify(fpAfter) === JSON.stringify(fpBefore),
    '★ 28 收到/发出快捷语后，棋盘 / 手牌 / 阶段按钮一个字都没变',
    { before: fpBefore, after: fpAfter });

  // ---------- 6. 频率与白名单（服务端裁决） ----------
  const sendVia = (tab, msgId) => tab.ev(`new Promise(function(res){
    gameState.socket.emit('quick_chat', { room_id: gameState.roomId, player_id: gameState.playerId,
      msg_id: ${JSON.stringify(msgId)} }, function(r){ res(r); });
  })`);
  const others = (cat.items || []).filter((x) => x.id !== REQUIRED_ID).map((x) => x.id);
  const r1 = await sendVia(A, others[0]);
  const r2 = await sendVia(A, others[1]);
  const gotB2 = await settleCount(B, 3, 15000);
  check(gotB2 === 3, '29 第 2、3 条正常发出（对手累计收到 3 条）', { got: gotB2, r1: r1 && r1.status, r2: r2 && r2.status });
  const r4 = await sendVia(A, others[2]);
  const gotB3 = await settleCount(B, 3, 4000);
  check(gotB3 === 3, '★ 30 第 4 条被频率限制挡下（10 秒内最多 3 条），对手收不到',
    { got: gotB3, resp: r4 && (r4.status || r4.error), msg: r4 && r4.message });
  const dup = await sendVia(A, others[0]);
  const gotB4 = await settleCount(B, 3, 4000);
  check(gotB4 === 3, '★ 31 同一句 10 秒内重复也被挡（连点不会变成刷屏）',
    { got: gotB4, resp: dup && (dup.status || dup.error), msg: dup && dup.message });

  const bad = await sendVia(A, 'hack_not_in_whitelist');
  const gotB5 = await settleCount(B, 3, 4000);
  check(gotB5 === 3 && bad && bad.status !== 'success',
    '★ 32 白名单外的 msg_id 被拒且**没有广播**', { got: gotB5, resp: bad && (bad.status || bad.error) });

  const after2 = await readState(A);
  check(after2.attacks === before.attacks && after2.phase === before.phase && (after2.chain === 0 || after2.chain === 'n/a'),
    '★ 33 连发 4 条（含被拒的）之后回合状态依然没变（被拒的也不许有副作用）', after2);

  check(jsProblems.length === 0, 'Z1 全程零 JS 异常 / 零 console.error', jsProblems.slice(0, 4));
} catch (e) {
  check(false, '工具执行异常', e.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) {}
}

console.log('');
if (problems.length) {
  console.log('QUICK CHAT CHECK FAILED (' + problems.length + '): ' + problems.join(' | '));
  process.exit(1);
}
console.log('QUICK CHAT CHECK PASSED');
process.exit(0);
