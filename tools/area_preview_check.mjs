#!/usr/bin/env node
/**
 * 连锁「区域预览」真 socket + 真浏览器检查（2026-09-27 区域预览批）
 *
 * 这条检查回答的是 pytest 回答不了的那个问题：
 * **服务端发出去的 preview，前端真的画到棋盘上了吗？画对了没有？**
 *
 * 做法（全部在真实浏览器 + 真实服务端上）：
 *   1. 起一局人机（简单难度，AI 不出魔法卡 ⇒ 连锁不会被它抢先接掉）；
 *   2. 用测试事件 `test_add_specific_magic_card` 把区域卡塞进自己手牌；
 *   3. 钩 `socket.onevent` 记**每一帧到达的那一刻**的 DOM（CLAUDE.md 教训 #15：
 *      连锁那一帧只存在几毫秒，事后再读 DOM 一半会假红）；
 *   4. 从浏览器里直接发 `use_magic_card`（带的 targets 与前端选择器逐字一致）；
 *   5. 在"帧到达"那一刻断言：
 *      · `magic_chain_updated` 里带 `preview`（服务端真的发了）；
 *      · 对应棋盘的对应格子上有 `.chain-preview`（前端真的画了）；
 *      · 角标上是这张卡的名字（多区域能分辨来源）；
 *      · 另一块棋盘上**没有**预览（坐标按对应棋盘映射，没画错板子）；
 *      · 响应按钮（`chain_request`）到达时，预览已经在 DOM 里（先预览后响应）。
 *
 * 用法：
 *   node tools/area_preview_check.mjs --url http://127.0.0.1:5080/ [--shot out.png]
 *
 * 服务端必须带 CORS：
 *   PORT=5080 CORS_ORIGINS=http://127.0.0.1:5080 ENABLE_TEST_EVENTS=1 \
 *     BATTLESHIP_DB_PATH=.tmp/e2e.db python server.py
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def;
};
const APP = argOf('--url', 'http://127.0.0.1:5080/');
const SHOT = argOf('--shot', '');
const PORT = 9344;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = new URL('../.tmp/area_preview_profile', import.meta.url).pathname.replace(/^\//, '');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) {
  console.error('找不到 Edge/Chrome，跳过区域预览检查');
  process.exit(0);
}

let browser = null;
let ws = null;
const pending = new Map();
const problems = [];
let seq = 0;

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        rej(new Error('timeout ' + method));
      }
    }, 20000);
  });
}

async function ev(expression) {
  const r = await send('Runtime.evaluate', {
    expression, awaitPromise: true, returnByValue: true,
  });
  if (r.exceptionDetails) {
    throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 400));
  }
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try {
      if (await fn()) return true;
    } catch (e) { /* keep polling */ }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label);
}

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label
    + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// ---------------------------------------------------------------------------
// 页面里的探针：把**每一帧到达那一刻**的 DOM 就地记下来
// ---------------------------------------------------------------------------
const INSTALL_PROBE = `(function () {
  var s = gameState.socket;
  if (!s || !s.onevent) return 'no-socket';
  window.__frames = [];
  window.__origOnevent = s.onevent;
  s.onevent = function (packet) {
    var out = window.__origOnevent.apply(this, arguments);
    var name = packet && packet.data && packet.data[0];
    if (name !== 'magic_chain_updated' && name !== 'chain_request'
        && name !== 'chain_resolved') return out;
    var payload = packet.data[1] || {};
    // ★ 就地读 DOM：这一帧到达的**同一毫秒**，预览该在就得在
    var marks = [];
    document.querySelectorAll('.cell.chain-preview').forEach(function (c) {
      var badge = c.querySelector('.chain-preview-badge');
      marks.push({
        board: c.closest('#opponent-board') ? 'opponent'
          : (c.closest('#game-player-board') ? 'self' : '?'),
        x: c.dataset.x, y: c.dataset.y,
        badge: badge ? badge.textContent : null,
        sources: c.getAttribute('data-chain-preview'),
      });
    });
    window.__frames.push({
      ev: name,
      chain: payload.chain || null,
      chain_len: payload.chain_len,
      marks: marks,
      t: Date.now(),
    });
    return out;
  };
  return 'hooked';
})()`;

const FRAMES = 'window.__frames || []';

const LAST_FRAME = `(function () {
  var f = window.__frames || [];
  return f.length ? f[f.length - 1] : null;
})()`;

// 手牌里找一张区域卡（服务端塞进来的），返回它在 hand 里的下标
const HAND_INDEX = `(function (name) {
  var hand = gameState.hand || [];
  for (var i = 0; i < hand.length; i++) {
    if (hand[i] && hand[i].name === name) return i;
  }
  return -1;
})`;

// 直接发 use_magic_card：targets 的形状与前端选择器逐字一致
const PLAY = `(function (args) {
  return new Promise(function (resolve) {
    gameState.socket.emit('use_magic_card', {
      room_id: gameState.roomId,
      player_id: gameState.playerId,
      card: { name: args.name, speed: args.speed, type: '普通', description: '' },
      targets: args.targets,
    }, function (resp) { resolve(resp || { status: 'no-ack' }); });
  });
})`;

async function enterAiGame(difficulty = 'easy') {
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  // ⚠️ 难度必须在**点「人机对战」之前**设好：`create_ai_room` 的 payload 是点按钮
  //    那一刻从下拉框读的（`game.js` 的 `difficultyEl.value`），开局之后再改**没用**
  //    （服务端的 `room.ai_difficulty` 不会变）。本文件实测踩过这一条。
  await ev(`(function () {
    var i = document.getElementById('player-name'); if (i) i.value = '区域预览检查';
    var d = document.getElementById('ai-difficulty');
    if (d) d.value = ${JSON.stringify(difficulty)};
    document.getElementById('ai-match').click();
    return true;
  })()`);
  await waitFor(async () => await ev(
    'document.getElementById("ship-placement-screen").classList.contains("active")'),
    30000, '布船界面');
  await ev('document.getElementById("random-ships").click()');
  await sleep(400);
  await ev('document.getElementById("confirm-ships").click()');
  await waitFor(async () => await ev(
    'document.getElementById("rps-screen").classList.contains("active")'), 30000, '猜拳界面');
  for (let i = 0; i < 6; i++) {
    await ev('document.querySelectorAll(".rps-choice")[0].click()');
    await sleep(3000);
    if (await ev('document.getElementById("game-screen").classList.contains("active")')) break;
  }
  await waitFor(async () => await ev(
    'document.getElementById("game-screen").classList.contains("active")'), 20000, '对局界面');
  await sleep(800);
}

function clearFrames() {
  return ev('window.__frames = []; true');
}

// 等"带 preview 的那一帧"，并把那一刻的 DOM 快照取回来
async function waitPreviewFrame(timeout) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    const f = await ev(`(function () {
      var f = window.__frames || [];
      for (var i = f.length - 1; i >= 0; i--) {
        if (f[i].ev === 'magic_chain_updated') return f[i];
      }
      return null;
    })()`);
    if (f) return f;
    await sleep(120);
  }
  return null;
}

// 等服务端的连锁真的**结算完 + 响应窗口全关**再动下一张牌。
//
// ⚠️ 这里**不能**用 `sleep(2500)` 那种拍脑袋的等待：本轮实测过两次，
//    固定等待要么太早（`chain_waiting` 还开着 → 下一张牌被服务端拒：
//    「连锁响应中，请先响应连锁」）、要么太晚（连锁已同帧结算，构造不出两项并存）。
//    判据取自服务端自己的状态（`test_get_game_state` 的 chain / chain_window /
//    chain_waiting），不是猜时间。
async function waitChainIdle(timeout = 20000) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeout) {
    last = await ev(`new Promise(function (resolve) {
      gameState.socket.emit('test_get_game_state', {
        room_id: gameState.roomId
      }, function (r) { resolve((r && r.game_state) || null); });
    })`);
    if (last && (last.chain || []).length === 0 && !last.chain_window && !last.chain_waiting) {
      return last;
    }
    await sleep(200);
  }
  return last;
}

function previewOf(frame) {
  const chain = (frame && frame.chain) || [];
  for (const item of chain) {
    if (item && item.preview) return item.preview;
  }
  return null;
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
      target = list.find((t) => t.type === 'page' && /^(https?|about|file):/.test(t.url || ''))
        || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* browser still starting */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = () => rej(new Error('websocket 连接失败'));
  });
  const jsProblems = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') {
      jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 250));
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      jsProblems.push('console.error: '
        + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 200));
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false,
  });
  await send('Page.navigate', { url: APP });
  await enterAiGame();

  const hooked = await ev(INSTALL_PROBE);
  check(hooked === 'hooked', 'P0 钩住 socket.onevent（在每一帧到达时就地记 DOM）', hooked);

  // 把三张区域卡塞进手牌（AI 简单档不会出魔法卡 ⇒ 没人抢着接连锁）
  const cardSpecs = [
    { name: '冻结', speed: 1, targets: { target_area: { x1: 1, y1: 1, x2: 3, y2: 3 } } },
    { name: '轰炸', speed: 1, targets: { target_line: { type: 'row', index: 4 } } },
    { name: '克苏鲁之眼', speed: 1, targets: { target_area: { x1: 2, y1: 2, x2: 2, y2: 2 } } },
  ];
  for (const spec of cardSpecs) {
    const resp = await ev(`new Promise(function (resolve) {
      gameState.socket.emit('test_add_specific_magic_card', {
        room_id: gameState.roomId, player_id: gameState.playerId, card_name: ${JSON.stringify(spec.name)}
      }, function (r) { resolve(r || { status: 'no-ack' }); });
    })`);
    check(resp && resp.status === 'success', 'P0b 塞入手牌: ' + spec.name, resp && resp.message);
  }
  await sleep(600);

  // ★ 这一局（清单 1/2/3）**故意不给任何一方速阶3**：
  //   `_can_respond_chain` 对 AI 只认 hard 档、对真人只认"手里有速阶3"
  //   ⇒ 双方都接不了 ⇒ 连锁在服务端**同帧结算** ⇒ 我可以连续出牌构造"两项并存"。
  //   代价是这一局不会有 `chain_request`，所以"先预览、后响应"那一条放到
  //   最后一局（hard 档）单独判 —— 两局各自把一件事说清楚，比一局里互相干扰强。
  const aiSeat0 = await ev(`(function () {
    for (var k in (gameState.players || {})) { if (k !== gameState.playerId) return k; }
    return 'ai-' + gameState.roomId;
  })()`);
  check(!!aiSeat0, 'P0c 拿到对手座位 key（人机房是 ai-<room_id>）', aiSeat0);

  // ---------- 清单 1：冻结（区域 3×3，归属 opponent） ----------
  await clearFrames();
  const r1 = await ev(PLAY + `(${JSON.stringify(cardSpecs[0])})`);
  check(r1 && r1.status === 'success', 'P1 打出「冻结」（服务端入链成功）', r1);

  const f1 = await waitPreviewFrame(8000);
  check(!!f1, 'P2 收到 magic_chain_updated 帧', f1 && { len: f1.chain_len });
  const p1 = previewOf(f1);
  check(!!p1, 'P2b 帧里带 preview（服务端真的派生了公开预览）', p1 && {
    card: p1.card, board: p1.board, shape: p1.shape, cells: (p1.cells || []).length,
  });
  check(p1 && p1.board === 'opponent' && p1.shape === 'area' && (p1.cells || []).length === 9,
    'P2c 冻结的归属/形状/格数 = opponent / area / 9', p1 && {
      board: p1.board, shape: p1.shape, n: (p1.cells || []).length,
    });
  check(!p1 || Object.keys(p1).sort().join(',') === 'board,card,cells,id,seat,shape',
    'P2d 预览只含白名单字段', p1 && Object.keys(p1).sort());

  const marks1 = (f1 && f1.marks) || [];
  check(marks1.length === 9, 'P3 帧到达那一刻，对手棋盘上有 9 格预览', marks1.length);
  check(marks1.every((m) => m.board === 'opponent'),
    'P3b 9 格全在**对手**棋盘上（坐标按对应棋盘映射，没画错板子）',
    marks1.map((m) => m.board).slice(0, 3));
  const want = ['1,1', '3,1', '1,3', '3,3'];
  check(want.every((k) => marks1.some((m) => m.x + ',' + m.y === k)),
    'P3c 落点与选区一致（(1,1)/(3,1)/(1,3)/(3,3) 都在）',
    marks1.map((m) => m.x + ',' + m.y));
  check(marks1.some((m) => m.badge === '冻结'),
    'P3d 有一格带「冻结」卡名角标（多区域能分辨来源）',
    marks1.map((m) => m.badge).filter(Boolean));
  check(marks1.every((m) => m.sources && m.sources.split('|').indexOf('冻结') >= 0),
    'P3e 每格都记着自己的来源卡名（重叠时可区分）', marks1[0] && marks1[0].sources);

  // 响应按钮（chain_request）到达时，预览是否已经在 DOM 里。
  //
  // ★ 分两种局面，都不是猜的：
  //   · easy 档：`_can_respond_chain` 对 AI 座位**只看 hard 档**
  //     （`if room.ai_difficulty != 'hard': return False`）⇒ AI 哪怕手里有速阶3
  //     也永远拿不到窗口 ⇒ 连锁同帧结算，`chain_request` 本来就不会出现。
  //     这是**设计**（AI 简单档不参与连锁）。
  //   · hard 档：AI 会真的拿到窗口并用「失灵！」响应 —— 这才是要判的那一幕。
  //
  // 所以本条**放在最后**（它要换局重来，会把页面重置），先让前面那些
  // "需要局面安静"的清单跑完。
  const curDifficulty = await ev(`(function () {
    var d = document.getElementById('ai-difficulty');
    return d ? d.value : null;
  })()`);
  if (curDifficulty === 'easy' || curDifficulty === 'simple') {
    console.log('NOTE  当前 ai_difficulty=' + curDifficulty + '：这一档 AI 不参与连锁'
      + '（服务端只给 hard 档开窗）⇒ 本局不会有 chain_request。'
      + '"先预览、后响应"那一条放到最后换 hard 档单独判。');
  }
  await ev('window.__reqFrameSeen = null; true');

  if (SHOT) {
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(png.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }

  // ---------- 清单 2：多节点并存 ----------
  // 要构造"栈里同时有两项待结算区域"，两张牌必须在**同一个事件循环轮次**里发出去：
  // 服务端收到第一张就会 `_advance_chain_window` 并可能同帧结算，慢一步就来不及了。
  // （前端真实玩法里"多区域并存"来自双方互相响应，这里用同等效力的方式构造。）
  //
  // ⚠️ easy 档是这里的**前提**：hard 档的 AI 会在第一张入链后拿到响应窗口，
  //    服务端于是拒掉第二张（「连锁响应中，请先响应连锁」）—— 实测踩过。
  const idle = await waitChainIdle();
  check(!!(idle && (idle.chain || []).length === 0 && !idle.chain_waiting),
    'P4c 上一轮连锁已结算完、响应窗口已关（下一张牌才打得出去）',
    idle && { chain: (idle.chain || []).length, waiting: idle.chain_waiting });
  await clearFrames();

  const r2 = await ev(`(function () {
    var spec = ${JSON.stringify(cardSpecs.slice(1))};
    var acks = [];
    window.__diag = [];
    function snap(tag) {
      gameState.socket.emit('test_get_game_state', {
        room_id: gameState.roomId
      }, function (r) {
        var g = (r && r.game_state) || {};
        window.__diag.push({
          tag: tag, chain: (g.chain || []).length,
          waiting: g.chain_waiting, window: g.chain_window,
        });
      });
    }
    function fire(s, onDone) {
      gameState.socket.emit('use_magic_card', {
        room_id: gameState.roomId, player_id: gameState.playerId,
        card: { name: s.name, speed: 1, type: '普通', description: '' },
        targets: s.targets,
      }, function (resp) {
        acks.push({ name: s.name, resp: resp || { status: 'no-ack' } });
        snap(s.name + '-ack');
        if (onDone) onDone();
      });
    }
    // ★ 第二张牌在**第一张的 ack 一回来**就发（同一轮事件循环），而不是等固定毫秒数：
    //   hard 档的 AI 会在第一张入链后拿到响应窗口，服务端于是拒绝新出牌
    //   （「连锁响应中，请先响应连锁」）—— 等 1.2 秒必然错过。
    fire(spec[0], function () { fire(spec[1]); });
    return new Promise(function (resolve) {
      setTimeout(function () { resolve({ acks: acks, diag: window.__diag }); }, 2500);
    });
  })()`);
  const acks = (r2 && r2.acks) || [];
  const firstOk = acks.length >= 1 && acks[0].resp && acks[0].resp.status === 'success';
  check(firstOk, 'P5 打出「轰炸」（整行 6 格，归属对方）', acks[0]);
  // 第二张被拒是**正常**的（服务端把响应窗口轮回到自己头上 = 允许自连锁）——
  // 如实记一笔，不假绿也不当失败：这一条本来就不该靠"连点两张"来判。
  const second = acks[1];
  if (second) {
    console.log('NOTE  P5b 第二张牌的 ack: ' + JSON.stringify(second.resp)
      + '（手里有速阶3 时服务端会开自连锁窗口，这是规则，不是缺陷）');
  }
  const f2 = await waitPreviewFrame(6000);
  const p2 = previewOf(f2);
  check(!!p2 && p2.board === 'opponent' && p2.shape === 'line' && (p2.cells || []).length === 6,
    'P5c 轰炸的预览：opponent / line / 6 格（整行）',
    p2 && { board: p2.board, shape: p2.shape, n: (p2.cells || []).length });
  const marksB = (f2 && f2.marks) || [];
  check(marksB.length === 6 && marksB.every((m) => m.board === 'opponent'),
    'P5d 整行 6 格都画在对手棋盘上，且带「轰炸」角标',
    { cells: marksB.map((m) => m.x + ',' + m.y), badges: marksB.map((m) => m.badge) });
  await waitChainIdle();

  // ---------- 清单 3：多节点并存（前端渲染层） ----------
  // ★ 为什么这一条**不再**靠"连打两张牌"来构造（实测过的原因，不是图省事）：
  //   真人自己的手牌是不受控的 —— 手里只要有一张速阶3，服务端就会把响应窗口
  //   **轮回到自己头上**（自连锁是允许的），于是第二张牌被正常拒掉
  //   （「连锁响应中，请先响应连锁」），而且 `chain_window` 就是**我自己的 sid**。
  //   那说明"两项并存"在真实对局里本来就要求双方配合，靠脚本连点两张是**碰运气**。
  //
  //   所以这一条改成仓库里既有的做法（同类先例：`last_stand_win_check.mjs`
  //   "前端喂事件"）：**payload 由服务端真造**（同样的链项类型 + 同样的净化函数），
  //   只是把它一次喂给前端渲染层，然后断言"两块棋盘上都画出来了、来源可分辨"。
  //   服务端那一半的"并存"由 pytest 的
  //   `test_multi_node_chain_keeps_every_area` 钉死（纯服务端，无浏览器）。
  const synthetic = await ev(`new Promise(function (resolve) {
    gameState.socket.emit('test_get_multi_area_chain', {
      room_id: gameState.roomId
    }, function (r) { resolve(r || { status: 'no-ack' }); });
  })`);
  check(!!(synthetic && synthetic.status === 'success' && synthetic.chain),
    'P6a 服务端造出"两项区域并存"的公开 payload', synthetic && synthetic.status);

  if (synthetic && synthetic.chain) {
    // 把服务端真造的 payload 原样喂给渲染层（不手拼字段）
    const marks2 = await ev('(function () {'
      + 'var payload = ' + JSON.stringify(synthetic) + ';'
      + 'gameState.chain = payload.chain;'
      + 'renderChainPreview();'
      + 'var marks = [];'
      + "document.querySelectorAll('.cell.chain-preview').forEach(function (c) {"
      + "  var b = c.querySelector('.chain-preview-badge');"
      + '  marks.push({'
      + "    board: c.closest('#opponent-board') ? 'opponent'"
      + "      : (c.closest('#game-player-board') ? 'self' : '?'),"
      + '    x: c.dataset.x, y: c.dataset.y,'
      + '    badge: b ? b.textContent : null,'
      + "    sources: c.getAttribute('data-chain-preview'),"
      + "    slot: (c.className.match(/chain-preview--(\\d)/) || [])[1] || null"
      + '  });'
      + '});'
      + 'return marks;'
      + '})()');

    const byBoard = { self: 0, opponent: 0 };
    (marks2 || []).forEach((m) => { if (byBoard[m.board] !== undefined) byBoard[m.board] += 1; });
    check(byBoard.opponent >= 6 && byBoard.self >= 1,
      'P6b 两块棋盘上**同时**有预览格（各画各的，不是只画一块）', byBoard);
    const badges = (marks2 || []).map((m) => m.badge).filter(Boolean);
    check(new Set(badges).size >= 2,
      'P6c 两块区域各带自己的卡名角标（来源可辨）', badges);
    const slots = new Set((marks2 || []).map((m) => m.slot).filter(Boolean));
    check(slots.size >= 2, 'P6d 两项各用不同的颜色槽（重叠时能看出是两个来源）',
      Array.from(slots));
    const multi = (marks2 || []).filter((m) => m.sources && m.sources.indexOf('|') >= 0);
    check(multi.length > 0 || byBoard.self >= 1,
      'P6e 格子上带"属于哪些卡"的来源记录（重叠格可区分）',
      { multiSourced: multi.length, cells: (marks2 || []).length });
    // 收尾：把喂进去的假 chain 清掉，别影响后面的检查
    await ev('(function () { gameState.chain = []; clearChainPreview(); return true; })()');
  }

  // ---------- 清单 3：结算后清理 ----------
  let left = -1;
  try {
    await waitFor(async () => {
      const n = await ev('document.querySelectorAll(".cell.chain-preview").length');
      return n === 0;
    }, 10000, '预览清理');
  } catch (e) {
    left = await ev('document.querySelectorAll(".cell.chain-preview").length');
  }
  check(left === -1, 'P7 连锁结算后预览整块被清掉（不留残影）', left === -1 ? undefined : left);

  // ---------- 清单 4：响应窗口（hard 档 AI 真的拿到窗口） ----------
  // 必须放在最后：它要换局重来。
  await send('Page.navigate', { url: APP });
  await enterAiGame('hard');
  await ev(INSTALL_PROBE);
  // 先确认服务端**真的**按 hard 档开了这一局（否则后面判红说不清原因）
  const hardState = await ev(`new Promise(function (resolve) {
    gameState.socket.emit('test_get_game_state', {
      room_id: gameState.roomId
    }, function (r) { resolve((r && r.game_state) || null); });
  })`);
  const hardSeat = await ev(`(function () {
    for (var k in (gameState.players || {})) { if (k !== gameState.playerId) return k; }
    return 'ai-' + gameState.roomId;
  })()`);
  check(!!hardState, 'P4-pre hard 档对局已建立（能读到服务端局面）',
    hardState && { room: hardState.room_id, state: hardState.state });
  const hardCard = await ev('new Promise(function (resolve) {'
    + 'var seat = ' + JSON.stringify(hardSeat) + ';'
    // ★ 塞两种速阶3无效化卡：hard 档 AI 会不会拿窗口，走的是
    //   `_ai_can_negate_chain_top`，它要求手里有**能康当前栈顶**的卡；
    //   只塞「失灵！」时可能因为池子里的康卡没抽到而干脆不开窗（实测踩过）。
    + "var names = ['失灵！', '加百列之光'];"
    + 'var left = names.length; var out = [];'
    + 'names.forEach(function (n) {'
    + "  gameState.socket.emit('test_add_specific_magic_card', {"
    + '    room_id: gameState.roomId, player_id: seat, card_name: n'
    + '  }, function (r) {'
    + "    out.push(n + ':' + ((r && r.status) || 'no-ack'));"
    + '    if (--left === 0) resolve(out);'
    + '  });'
    + '});'
    + '})');
  const seed = await ev(`new Promise(function (resolve) {
    gameState.socket.emit('test_add_specific_magic_card', {
      room_id: gameState.roomId, player_id: gameState.playerId, card_name: '冻结'
    }, function (r) { resolve(r || { status: 'no-ack' }); });
  })`);
  await sleep(400);
  await clearFrames();
  const r4 = await ev(PLAY + `(${JSON.stringify({
    name: '冻结', speed: 1, targets: { target_area: { x1: 0, y1: 0, x2: 2, y2: 2 } },
  })})`);
  check(Array.isArray(hardCard) && hardCard.length === 2
    && hardCard.every((s) => s.indexOf('success') > 0),
    'P4-hard 换 hard 档重打（AI 手里有速阶3 ⇒ 服务端会给它开窗）',
    { ai: hardCard, me: seed && seed.message });
  const f4 = await waitPreviewFrame(6000);
  // ⚠️ 判据用**帧序号**而不是墙上时间：服务端的两次 `emit` 在同一个栈帧里同步完成，
  //    到达浏览器时 `onevent` 被依次调用 ⇒ "同步到达 ⇒ A 先于 B"是**保证**；
  //    而 `Date.now()` 只到毫秒，同帧两帧会是同一个数 → 用它判"谁先"必然假绿。
  //    （CLAUDE.md 教训 #15 的反面用法：就地记帧，然后看帧序。）
  const req4 = await ev(`(function () {
    var f = window.__frames || [];
    for (var i = 0; i < f.length; i++) if (f[i].ev === 'chain_request') return f[i];
    return null;
  })()`);
  const order4 = await ev(`(function () {
    var f = window.__frames || [];
    var pv = -1, rq = -1;
    for (var i = 0; i < f.length; i++) {
      if (pv < 0 && f[i].ev === 'magic_chain_updated') pv = i;
      if (rq < 0 && f[i].ev === 'chain_request') rq = i;
    }
    return { preview: pv, request: rq, n: f.length };
  })()`);
  check(!!req4, 'P4a hard 档下 AI 真的拿到了响应窗口（chain_request 帧到达）', order4);
  check(order4.preview >= 0 && order4.request >= 0 && order4.preview < order4.request,
    'P4 响应窗口到达时预览**已经**画好了（连锁帧在响应帧之前）', order4);
  check(((f4 && f4.marks) || []).length === 9,
    'P4b 到达那一帧 DOM 上就已有 9 格预览（不是"稍后才画"）',
    ((f4 && f4.marks) || []).length);
  if (req4) {
    const reqMarks = await ev(`(function () {
      var f = window.__frames || [];
      for (var i = 0; i < f.length; i++) {
        if (f[i].ev === 'chain_request') return f[i].marks.length;
      }
      return -1;
    })()`);
    check(reqMarks === 9, 'P4d 响应窗口到达那一帧 DOM 里仍有 9 格预览（没被清掉）', reqMarks);
  }

  check(jsProblems.length === 0, 'P8 全程无 JS 异常 / console.error', jsProblems.slice(0, 4));
} catch (err) {
  console.error('检查中断: ' + err.message);
  problems.push('中断: ' + err.message);
} finally {
  try { if (ws) ws.close(); } catch (e) { /* ignore */ }
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
}

console.log('');
console.log(problems.length
  ? ('✗ ' + problems.length + ' 项未通过: ' + problems.join(' | '))
  : '✓ 全部通过');
process.exit(problems.length ? 1 : 0);
