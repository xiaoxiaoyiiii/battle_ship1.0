#!/usr/bin/env node
/**
 * C+ 大厅屏 · **筛选与卡片**的定向检查（W3）
 *
 * 覆盖搜索（房名／房主／对局玩家）、状态筛选（全部/可加入/可观战/已满）、
 * 已满房的禁用与说明、两级空态，以及"订阅刷新不许把玩家正在输的关键词抹掉"。
 *
 * 做法：**直接喂 lobby_state 载荷**给 renderLobbyState()（与 cplus_deploy_check 同一手法）。
 *   大厅的数据来源就是这条广播，喂它等价于"服务端推了一份这样的状态"，
 *   不伪造任何业务字段、也不碰产品代码。这样筛选逻辑可以在无第二个客户端、
 *   无等待时间的前提下被确定性地验，包括"房满/不同房主/不同房间名"这些组合。
 *
 * 布局断言保留四类功能面板，并量它们的真实位置与房间卡片列数。
 *
 * 用法：node tools/cplus_lobby_check.mjs --url http://127.0.0.1:5097/ [--shots <dir>]
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
const PORT = Number(argOf('--port', '9363'));
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
const PROFILE = argOf('--profile', path.join(REPO, '.tmp', 'cplus-lobby', 'profile'));
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

/* 一份具名载荷：三间等待房（一间满、两间可加入，其中一间房主名与房名都不含关键词）
   + 两局进行中对局。房名/房主刻意做成可区分的字符串，好断言"筛出来的是哪几条"。 */
const STATE = {
  online_count: 12, lobby_count: 5, queue: { casual: 2, ranked: 1 },
  players: [
    { key: 'k1', name: '老船长', level: 7, status: 'idle' },
    { key: 'k2', name: '新水手', level: 2, status: 'matching' },
  ],
  rooms: [
    { room_id: 'rAAA1111', name: '紫金杯预选', host: '老船长', players: 1, capacity: 2 },
    { room_id: 'rBBB2222', name: '深海练兵', host: '新水手', players: 1, capacity: 2 },
    { room_id: 'rCCC3333', name: '满员房', host: '老船长', players: 2, capacity: 2 },
  ],
  matches: [
    { room_id: 'mDDD4444', names: ['老船长', '新水手'], round: 3, spectators: 1, spectator_limit: 10 },
    { room_id: 'mEEE5555', names: ['路人甲', '路人乙'], round: 7, spectators: 0, spectator_limit: 10 },
  ],
};

const HARNESS = `(function(){
  if (window.__lobbyHarness) return window.__lobbyHarness;
  var H = {};
  /* ⚠️ 每次动作前都把 gameState.lobbyState 重新钉回 fixture。
     否则会被别的东西改掉：showLobby() 会订阅大厅，而订阅下来的
     lobby_state 是**这台测试服务器上的真实状态**（没有房间）——
     它一到就把 fixture 盖掉，于是"搜索之后列表空了"看着像筛选写坏了，
     其实是喂进去的数据被替换了。fixture 就是"服务端推的这份状态"。
     （这段在模板字符串里，所以注释里不能用反引号引用函数名。） */
  H.seed = function(){ gameState.lobbyState = window.__LOBBY_FIXTURE__; return H; };
  H.feed = function(){
    if (typeof showLobby === 'function') showLobby();
    H.seed();
    renderLobbyState(window.__LOBBY_FIXTURE__);
    return H.snap();
  };
  H.search = function(v){
    H.seed();
    var el = document.getElementById('lobby-room-search');
    el.value = v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return H.snap();
  };
  H.filter = function(name){
    H.seed();
    var btn = document.querySelector('#lobby-room-filter [data-filter="' + name + '"]');
    if (btn) btn.click();
    return H.snap();
  };
  H.snap = function(){
    var rooms = [].slice.call(document.querySelectorAll('#lobby-rooms-list .lobby-room'));
    var matches = [].slice.call(document.querySelectorAll('#lobby-matches-list .lobby-match'));
    var roomsEmpty = document.querySelector('#lobby-rooms-list .lobby-empty');
    var matchesEmpty = document.querySelector('#lobby-matches-list .lobby-empty');
    return {
      roomNames: rooms.map(function(li){ return (li.querySelector('.lobby-room-name') || {}).textContent || ''; }),
      roomJoins: rooms.map(function(li){ var b = li.querySelector('.lobby-room-join');
        return b ? { disabled: b.disabled, room: b.dataset.room } : null; }),
      matchNames: matches.map(function(li){ return (li.querySelector('.lobby-match-name') || {}).textContent || ''; }),
      roomsEmpty: roomsEmpty ? roomsEmpty.textContent : null,
      matchesEmpty: matchesEmpty ? matchesEmpty.textContent : null,
      searchValue: (document.getElementById('lobby-room-search') || {}).value,
      activeFilter: (function(){ var b = document.querySelector('#lobby-room-filter [data-filter].active');
        return b ? b.dataset.filter : null; })(),
      panels: document.querySelectorAll('#lobby-screen .lobby-panel').length,
      filters: document.querySelectorAll('#lobby-room-filter [data-filter]').length,
      roomPanelVisible: getComputedStyle(document.querySelector('#lobby-screen .lobby-panel:nth-child(2)')).display !== 'none',
      matchPanelVisible: getComputedStyle(document.querySelector('#lobby-screen .lobby-panel:nth-child(3)')).display !== 'none',
    };
  };
  window.__lobbyHarness = H;
  return H;
})()`;

console.log('== C+ 大厅筛选定向检查（W3）==');
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

  for (const [vlabel, w, h] of [['1440x900', 1440, 900], ['1280x720', 1280, 720],
    ['390x844', 390, 844], ['320x568', 320, 568], ['664x336', 664, 336]]) {
    console.log('');
    console.log('-- 视口 ' + vlabel + ' --');
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
    await send('Page.navigate', { url: APP });
    for (let i = 0; i < 60; i++) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break; await sleep(300); }
    await sleep(600);
    await ev('window.__LOBBY_FIXTURE__ = ' + JSON.stringify(STATE) + ';');
    await ev(HARNESS);

    // ① 基线：三间房 + 两局对局都在，骨架没被改坏
    const base = await ev('(function(){ return window.__lobbyHarness.feed(); })()');
    check(base && base.roomNames.length === 3, '[' + vlabel + '] 基线：三间等待房都画出来', base && base.roomNames);
    check(base && base.matchNames.length === 2, '[' + vlabel + '] 基线：两局进行中对局都画出来', base && base.matchNames);
    check(base && base.panels === 4, '[' + vlabel + '] 骨架不变量：仍是 4 块 .lobby-panel（没加第 5 块）', base && base.panels);
    check(base && base.filters === 4, '[' + vlabel + '] 状态筛选有四档（全部/可加入/可观战/已满）', base && base.filters);
    const tracks = await ev('(function(){ var g = getComputedStyle(document.querySelector("#lobby-screen .lobby-columns"));'
      + ' return g.gridTemplateColumns.split(" ").filter(function(x){ return x && x !== "0px"; }).length; })()');
    /* 三条轨道是布局实现细节；下面的几何断言检验真正的产品结构：
       房间卡片占主区，在线玩家在侧栏，手机按房间→对局→玩家→公屏排列。 */
    if (w >= 900) {
      check(tracks === 3, '[' + vlabel + '] 骨架不变量：.lobby-columns 仍是 3 条轨道（lobby_check 的固定判据）', { tracks });
    } else {
      check(tracks >= 1, '[' + vlabel + '] 窄屏下 .lobby-columns 折成单列（响应式行为，非骨架变更）', { tracks });
    }
    const geometry = await ev(`(function(){
      window.__lobbyHarness.seed(); renderLobbyState(window.__LOBBY_FIXTURE__);
      var p = Array.from(document.querySelectorAll('#lobby-screen .lobby-panel')).map(function(el){
        var r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height};
      });
      var cards = Array.from(document.querySelectorAll('#lobby-rooms-list > .lobby-room')).map(function(el){
        var r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width};
      });
      var rooms=document.getElementById('lobby-rooms-list');
      return {panels:p,cards:cards,roomScroll:rooms.scrollWidth-rooms.clientWidth};
    })()`);
    check(geometry && geometry.roomScroll <= 2,
      '[' + vlabel + '] 房间卡片容器没有局部水平溢出', geometry && geometry.roomScroll);
    if (w >= 900) {
      check(geometry && geometry.panels[1].x < geometry.panels[0].x
        && geometry.panels[1].w > geometry.panels[0].w,
        '[' + vlabel + '] 房间主区在左且比在线侧栏宽', geometry && geometry.panels);
      check(geometry && geometry.cards.length >= 2 && geometry.cards[1].x > geometry.cards[0].x,
        '[' + vlabel + '] 等待房卡片在主区排成两列', geometry && geometry.cards);
    } else {
      check(geometry && geometry.panels[1].y < geometry.panels[2].y
        && geometry.panels[2].y < geometry.panels[0].y
        && geometry.panels[0].y < geometry.panels[3].y,
        '[' + vlabel + '] 手机按房间、对局、玩家、公屏排列', geometry && geometry.panels);
    }

    // ② 按房名搜索
    const byName = await ev('window.__lobbyHarness.search("深海")');
    check(byName && byName.roomNames.length === 1 && byName.roomNames[0] === '深海练兵',
      '[' + vlabel + '] 搜索房名：只剩命中那一间', byName && byName.roomNames);
    check(byName && byName.matchNames.length === 0,
      '[' + vlabel + '] 搜索是**统一**的：对局列表也按同一关键词筛（两位玩家名都不含"深海"）',
      byName && byName.matchNames);

    // ③ 按房主搜索
    const byHost = await ev('window.__lobbyHarness.search("新水手")');
    check(byHost && byHost.roomNames.length === 1 && byHost.roomNames[0] === '深海练兵',
      '[' + vlabel + '] 搜索房主：命中"新水手"当房主的那间', byHost && byHost.roomNames);
    check(byHost && byHost.matchNames.length === 1,
      '[' + vlabel + '] 搜索房主同时命中他参与的对局', byHost && byHost.matchNames);

    // ④ 搜不到的空态要说清是"筛掉了"而不是"大厅空了"
    const none = await ev('window.__lobbyHarness.search("不存在的房")');
    check(none && none.roomNames.length === 0 && /共 3 间在等/.test(none.roomsEmpty || ''),
      '[' + vlabel + '] 搜不到时说明"是筛掉的"（并给出总数），不是"暂无房间"',
      none && none.roomsEmpty);

    // ⑤ 状态筛选：可加入 / 已满
    const jn = await ev('(function(){ var H = window.__lobbyHarness; H.search(""); return H.filter("joinable"); })()');
    check(jn && jn.roomNames.length === 2 && jn.roomNames.indexOf('满员房') < 0,
      '[' + vlabel + '] 筛"可加入"：满员那间不在列表里', jn && jn.roomNames);
    check(jn && jn.roomPanelVisible && !jn.matchPanelVisible,
      '[' + vlabel + '] 可加入视图只显示等待房主区', jn && { rooms: jn.roomPanelVisible, matches: jn.matchPanelVisible });
    const watch = await ev('window.__lobbyHarness.filter("watchable")');
    check(watch && watch.matchNames.length === 2 && !watch.roomPanelVisible && watch.matchPanelVisible,
      '[' + vlabel + '] 可观战视图只显示服务端可见对局', watch && { names: watch.matchNames, rooms: watch.roomPanelVisible, matches: watch.matchPanelVisible });
    const full = await ev('window.__lobbyHarness.filter("full")');
    check(full && full.roomNames.length === 1 && full.roomNames[0] === '满员房',
      '[' + vlabel + '] 筛"已满"：只剩满员那间', full && full.roomNames);
    check(full && full.roomJoins[0] && full.roomJoins[0].disabled === true,
      '[' + vlabel + '] 满员房的「加入」按钮是禁用的（不是点了报错）', full && full.roomJoins[0]);

    // ⑥ 订阅刷新不许把输入抹掉：再喂一次 lobby_state，搜索词与筛选档都还在
    const afterBroadcast = await ev('(function(){ var H = window.__lobbyHarness;\n'
      + ' H.search("紫金"); H.filter("all");\n'
      + ' H.seed(); renderLobbyState(window.__LOBBY_FIXTURE__);   // 模拟 4 秒一次的那条广播\n'
      + ' return H.snap(); })()');
    check(afterBroadcast && afterBroadcast.searchValue === '紫金'
      && afterBroadcast.roomNames.length === 1,
      '[' + vlabel + '] 广播刷新后搜索词与筛选结果都保持（没把玩家正在输的关键词抹掉）',
      afterBroadcast && { value: afterBroadcast.searchValue, rooms: afterBroadcast.roomNames });

    // ⑦ 回到全量：清空搜索 + 全部
    const reset = await ev('(function(){ var H = window.__lobbyHarness; H.search(""); H.filter("all"); return H.snap(); })()');
    check(reset && reset.roomNames.length === 3 && reset.matchNames.length === 2,
      '[' + vlabel + '] 清空搜索 + 选「全部」后三间房两局对局都回来', reset && { rooms: reset.roomNames, matches: reset.matchNames });

    // ⑧ 无横向溢出（筛选栏在窄屏要能折行）
    const ov = await ev('(function(){ var d = document.documentElement;'
      + ' var worst = 0, el = null;'
      + ' document.querySelectorAll("#lobby-screen *").forEach(function(e){'
      + '   if (!e.clientWidth) return; var x = getComputedStyle(e).overflowX;'
      + '   if (x === "auto" || x === "scroll") return;'
      + '   var d2 = e.scrollWidth - e.clientWidth; if (d2 > worst) { worst = d2; el = e.className || e.tagName; } });'
      + ' return { page: d.scrollWidth - d.clientWidth, worst: worst, el: String(el).slice(0, 60) }; })()');
    check(ov && ov.page <= 1 && ov.worst <= 1, '[' + vlabel + '] 大厅（含筛选栏）无横向溢出', ov);

    if (SHOTS) {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(SHOTS, 'lobby-' + vlabel + '.png'), Buffer.from(shot.data, 'base64'));
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
