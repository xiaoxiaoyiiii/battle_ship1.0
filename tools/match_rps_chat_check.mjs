#!/usr/bin/env node
/**
 * 「匹配成功等待页 + 猜拳选中/平局重试 + 快捷语进聊天窗」端到端回归（无头 Edge + CDP，真实双客户端）
 *
 * 这三块是同一次改动的三个接缝，共同点是**都要经过服务端真值**：
 *   - 匹配成功屏上的对手名 / 称号 / 段位 / 倒计时全部由服务端事件驱动；
 *   - 猜拳的「选中」必须是**服务端认过的那一次出拳**，平局要把三个选项还回来；
 *   - 快捷语的回显只能靠服务端广播，客户端**不许**再 emit 一次 `chat_message`。
 *
 * 所以本工具走**真实流程**（建房 → 入座 → 匹配成功 → 摆船 → 猜拳 → 对局），
 * 不用合成 DOM 去断言「元素在不在」。反过来，凡是能读到服务端真值的地方一律读真值，
 * 不听前端自己说的话。
 *
 * 为什么需要它（既有工具覆盖不到的洞）：
 *   - `tools/quick_chat_check.mjs` 验的是「快捷语发出去了、日志恰好一行」，但**没有**验
 *     聊天消息区的回显，也**没有**验「客户端有没有绕道再发一次 chat_message」；
 *     它那条「点浮层外面能关掉」的断言取候选点时会被超出视口的 host 矩形整体滤掉，
 *     实际从未点到过外面（见下面 §3 的修法）。
 *   - 猜拳的重复提交 / 迟到 ack / 平局重试，既有工具**一条都没有**。
 *   - 匹配成功屏只有 `level_check.mjs` / `ranked_check.mjs` 读过它的**文字**，
 *     没人量过它的**几何**（两档视口下核心信息在不在首屏、有没有横向溢出）。
 *     ⚠️ 2026-10-07 审查回单补的第三档手机视口 + ★13a/13b/13c 三条几何断言，
 *        就是被"文字/在首屏内都过了、实拍却是贴顶的一小块"这件事逼出来的。
 *
 * 用法：
 *   node tools/match_rps_chat_check.mjs --url http://127.0.0.1:5000/
 *   node tools/match_rps_chat_check.mjs --url http://127.0.0.1:5000/ --shots
 *
 * ⚠️ 需要服务端带 `ENABLE_TEST_EVENTS=1`（读服务端真值要用 `test_get_game_state`）。
 *    本地跑法（隔离库）：
 *      $env:PORT='5000'; $env:CORS_ORIGINS='http://127.0.0.1:5000'
 *      $env:BATTLESHIP_DB_PATH="$PWD\.tmp\match_rps_chat.db"; $env:ENABLE_TEST_EVENTS='1'
 *      python server.py
 * ⚠️ 只注册**游客**房间（create_room / join_room），不写任何账号数据。
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const flag = (n) => argv.indexOf(n) >= 0;
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOTS = flag('--shots');
const PORT = 9455;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(HERE, '..', '.tmp', 'match_rps_profile');
const SHOT_DIR = path.join(HERE, '..', '.tmp', 'match_rps_shots');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const VIEW_W = 1440;
const VIEW_H = 900;
// 三档视口：桌面 + 紧凑档（项目里 `layout-compact` 的判定线）+ 手机竖屏。
// ⚠️ 手机那档是 2026-10-07 审查回单补的：这块屏的验收里写着「手机首屏可见」，
//    而工具此前只量了 1280×720 / 1024×640 —— 手机档**从没被测过**。
//    390×844 是项目里既有的手机基准（changelog_check / friend_dm_check 都用它）。
const VIEWPORTS = [[1280, 720], [1024, 640], [390, 844], [320, 568]];

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过本检查'); process.exit(0); }

// 预清理：残留的无头 Edge 会占着调试端口 + 锁住 profile，新浏览器静默起不来。
try {
  execSync('powershell -NoProfile -Command "' +
    'Get-CimInstance Win32_Process -Filter \\"Name=\'msedge.exe\'\\" | ' +
    'Where-Object { $_.CommandLine -like \'*match_rps_profile*\' } | ' +
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
let shotSeq = 0;

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
  const tab = {
    ev, ws, send, tag: url,
    // 无头浏览器里只有前台页有正常布局；读几何 / 命中测试 / 派发鼠标事件之前必须先调它。
    front: async () => { try { await send('Page.bringToFront'); } catch (e) { /* 忽略 */ } await sleep(200); },
    ready: async () => {
      const t0 = Date.now();
      while (Date.now() - t0 < 20000) {
        if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true;
        await sleep(200);
      }
      return false;
    },
    waitFor: async (expr, ms = 8000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) { if (await ev(expr)) return true; await sleep(200); }
      return false;
    },
    realClick: async (sel) => {
      const box = await ev(`(function(){ var e=document.querySelector(${JSON.stringify(sel)}); if(!e) return null;
        var r=e.getBoundingClientRect(), cs=getComputedStyle(e);
        if (r.width<=0||r.height<=0||cs.display==='none'||cs.visibility==='hidden') return null;
        return {x:r.left+r.width/2, y:r.top+r.height/2, w:r.width, h:r.height}; })()`);
      if (!box || box.__exc) return { ok: false, reason: 'not-found-or-invisible', box: box };
      const x = Math.round(box.x), y = Math.round(box.y);
      const topDesc = await ev(`(function(){ var el=document.elementFromPoint(${x},${y}); return el? (el.tagName+(el.id?'#'+el.id:'')+(el.className&&typeof el.className==='string'?'.'+el.className.split(' ')[0]:'')) : 'null'; })()`);
      await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
      await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
      return { ok: true, x, y, w: box.w, h: box.h, topDesc };
    },
    clickAt: async (x, y) => {
      await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: Math.round(x), y: Math.round(y), button: 'left', clickCount: 1 });
      await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: Math.round(x), y: Math.round(y), button: 'left', clickCount: 1 });
    },
    setViewport: async (w, h) => {
      // 窄于 600 走真实手机档（项目里 cplus_* 系列同一判据）：`mobile:true` 会改
      // 布局视口/缩放的处理，只缩宽度不打开它，量到的就不是手机上的那块屏。
      await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
      await sleep(350);
    },
    clearViewport: async () => { await send('Emulation.clearDeviceMetricsOverride'); await sleep(250); },
    shot: async (name) => {
      if (!SHOTS) return null;
      fs.mkdirSync(SHOT_DIR, { recursive: true });
      const r = await send('Page.captureScreenshot', { format: 'png' });
      const f = path.join(SHOT_DIR, `${String(++shotSeq).padStart(2, '0')}-${name}.png`);
      fs.writeFileSync(f, Buffer.from(r.data, 'base64'));
      return f;
    },
  };
  return tab;
}

/** 页面侧钩子：数一数客户端**真的**往外发了哪些事件。
 *  ⚠️ 这是本工具最要紧的一件仪器：「不许客户端再补发一次 chat_message」不能靠读源码，
 *     只能靠数真实 emit。
 *  ⚠️ 必须包 `socket.emit`（**出站**），不能包 `socket.onevent` —— 后者是 socket.io 客户端
 *     处理**入站**包的入口。第一版包错了，于是计数恒为 0：★24/★33 全部假红（「只发了 1 次」
 *     写成 before=0 after=0 看不出来，因为 0 和 0 也满足某些比较），★50 则是**假绿**
 *     —— 它要证明「没有绕道补发」，而入站钩子本来就永远数不到出站事件，等于什么都没验。 */
const HOOK = `(function(){ if (window.__mrHook) return true;
  var s = (typeof ensureSocket === 'function') ? ensureSocket() : (window.gameState && window.gameState.socket);
  if (!s) return 'no-socket';
  window.__mrHook = { rps: 0, chat: 0, quick: 0 };
  s.emit = (function(orig){ return function(name){
    try {
      if (name === 'rps_choice') window.__mrHook.rps++;
      if (name === 'chat_message') window.__mrHook.chat++;
      if (name === 'quick_chat') window.__mrHook.quick++;
    } catch (e) { /* 计数失败不该影响被测流程 */ }
    return orig.apply(this, arguments); }; })(s.emit);
  return true; })()`;

/** 进房间：B 建房、A 入座，座位 key 用各自的账号 uid（游客房也走同一套）。 */
async function openRoom(A, B, label) {
  const nameA = 'Mr' + label + 'A';
  const nameB = 'Mr' + label + 'B';
  const created = await B.ev(`new Promise(function(res){ ensureSocket(); gameState.playerName = ${JSON.stringify(nameB)};
    gameState.socket.emit('create_room', { player_name: ${JSON.stringify(nameB)} }, function(r){ res(r); }); })`);
  const roomId = created && created.room_id;
  const joined = await A.ev(`new Promise(function(res){ ensureSocket(); gameState.playerName = ${JSON.stringify(nameA)};
    gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name: ${JSON.stringify(nameA)} }, function(r){ res(r); }); })`);
  const aSeat = joined && joined.player_id;
  const st = await A.ev(`new Promise(function(res){
    gameState.socket.emit('test_get_game_state', { room_id: ${JSON.stringify(roomId)} }, function(x){ res(x); }); })`);
  const players = (st && st.game_state && st.game_state.players) || {};
  // ⚠️ 这里**B 建房、A 入座**，所以 A 的座位 key 就是 join_room 回的 player_id；
  //    另一个才是 B 的。第一版按 quick_chat_check（A 建房、B 入座）的写法照抄成
  //    `aPid = keys.find(p => p !== aSeat)` —— 两边对调了，于是所有 place_ships /
  //    quick_chat 都带着**对手的身份**发出去，被服务端按身份校验一律拒掉。
  const aPid = aSeat;
  const bPid = Object.keys(players).find((p) => p !== aSeat) || null;
  await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; gameState.playerId = ${JSON.stringify(aPid)}; true`);
  await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; gameState.playerId = ${JSON.stringify(bPid)}; true`);
  return { roomId: roomId, aPid: aPid, bPid: bPid, nameA: nameA, nameB: nameB };
}

const SHIPS = (seed) => Array.from({ length: 6 }, (_, i) => ({ positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [] }));

async function placeShips(tab, room, pid, seed) {
  return tab.ev(`new Promise(function(res){ gameState.socket.emit('place_ships', { room_id: ${JSON.stringify(room.roomId)},
    player_id: ${JSON.stringify(pid)}, ships: ${JSON.stringify(SHIPS(seed))} }, function(r){ res(r); }); })`);
}

const RPS_STATE = `(function(){
  var out = { active: false, choices: [], waiting: false, result: null, resultText: '', resultTie: false, round: null };
  var s = document.getElementById('rps-screen');
  if (s) { var cs = getComputedStyle(s); out.active = s.classList.contains('active') && cs.display !== 'none'; }
  var list = [].slice.call(document.querySelectorAll('.rps-choice'));
  out.choices = list.map(function (e) {
    var cs = getComputedStyle(e);
    return { choice: e.dataset.choice, picked: e.classList.contains('picked'),
      aria: e.getAttribute('aria-pressed'), disabled: e.disabled === true,
      box: { w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height) },
      // ⚠️ 不能用 getComputedStyle(e).display 判可见：元素处在 display:none 的祖先下时，
      //    它自己的 computed display 仍返回 'block'/'inline-flex'，于是「猜拳屏根本没激活」
      //    也会显示成可见 —— 实测踩过这个假绿。getClientRects() 为空才是真的没渲染。
      visible: e.getClientRects().length > 0 && cs.visibility !== 'hidden' };
  });
  var w = document.getElementById('rps-waiting');
  if (w) { var cw = getComputedStyle(w); out.waiting = !w.classList.contains('hidden') && cw.display !== 'none' && cw.visibility !== 'hidden'; }
  var r = document.getElementById('rps-result');
  if (r) { var cr = getComputedStyle(r); out.result = !r.classList.contains('hidden') && cr.display !== 'none';
    out.resultText = (r.textContent || '').trim(); out.resultTie = r.classList.contains('is-tie'); }
  var rd = document.getElementById('rps-round');
  out.round = rd ? (rd.textContent || '').trim() : null;
  return out; })()`;

const pickedOf = (st) => (st.choices || []).filter((c) => c.picked).map((c) => c.choice);

async function openRps(A, B, label) {
  const room = await openRoom(A, B, label);
  await placeShips(A, room, room.aPid, 0);
  await placeShips(B, room, room.bPid, 1);
  const ok = await A.waitFor(`(function(){ var s=document.getElementById('rps-screen'); var cs=s&&getComputedStyle(s);
    return !!(s && s.classList.contains('active') && cs.display !== 'none' && document.querySelectorAll('.rps-choice').length === 3); })()`, 15000);
  return { room: room, rpsShown: ok };
}

/** 点一次猜拳选项（真实鼠标事件，走 .rps-choice 自己那条既有路径）。 */
async function clickChoice(tab, choice) {
  return tab.realClick(`.rps-choice[data-choice="${choice}"]`);
}

try {
  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=' + VIEW_W + ',' + VIEW_H, '--force-device-scale-factor=1',
    APP], { stdio: 'ignore' });
  await sleep(3500);

  const A = await openTab(APP);
  const B = await openTab(APP);
  check(await A.ready() && await B.ready(), '0 两个客户端都进到对局界面');

  await A.ev(HOOK); await B.ev(HOOK);
  const hooked = await A.ev('window.__mrHook || null');
  check(hooked && typeof hooked.rps === 'number', '0b 出站事件计数器已装上（数 rps_choice / chat_message / quick_chat）', hooked);

  // ================= §1 匹配成功等待页 =================
  const roomA = await openRoom(A, B, 'A');
  await A.ev(`gameState.opponentName = ${JSON.stringify(roomA.nameB)}; true`);
  const shown = await A.waitFor(`(function(){ var s=document.getElementById('match-success-screen');
    return !!(s && s.classList.contains('active')); })()`, 15000);
  check(shown === true, '★ 1 建房 + 入座后真的弹出了 #match-success-screen（真实流程，不是手动加 class）', shown);

  // 5 秒窗口内先抓「真实数据」，几何与 chips 留到后面单独测。
  // ⚠️ 下面这些是**活值**（覆盖后的 display、倒计时数字、进度条实测宽度），必须在 5 秒窗口内读完；
  //    第一版把「等 chips」插在这里，等于把读取推到倒计时结束之后，★2/★7/★8 全部假红。
  //    chips 是服务端异步填的，拆到 ★11 之后单独测（见下方 chip 段）。
  const info = await A.ev(`(function(){
    var s = document.getElementById('match-success-screen');
    var opp = document.getElementById('opponent-info');
    var box = document.getElementById('opponent-chips');
    var self = document.getElementById('match-self-rank');
    var cd = document.getElementById('countdown-timer');
    var bar = document.querySelector('#match-success-screen .countdown-bar');
    var fill = document.querySelector('#match-success-screen .countdown-fill');
    var now = document.getElementById('start-now');
    return {
      display: s ? getComputedStyle(s).display : 'no-el',
      oppText: opp ? (opp.textContent || '').trim() : 'no-el',
      lv: box ? !!box.querySelector('.match-chip.lv') : false,
      title: box ? !!box.querySelector('.match-chip.title') : false,
      tags: box ? box.querySelectorAll('.match-chip.tag').length : -1,
      chipsScroll: box ? box.scrollWidth - box.clientWidth : -1,
      selfRankPresent: !!self,
      countdown: cd ? (cd.textContent || '').trim() : 'no-el',
      barW: bar ? Math.round(bar.getBoundingClientRect().width) : -1,
      fillW: fill ? Math.round(fill.getBoundingClientRect().width) : -1,
      startNowPresent: !!now,
      vers: !!document.querySelector('#match-success-screen .match-versus'),
      foe: !!document.querySelector('#match-success-screen .match-fighter-foe'),
    }; })()`);
  check(info && info.display === 'flex',
    '★ 2 这块屏真的是 flex 布局（新样式生效；`.screen.active` 的 display:block 被压过去了）', info && info.display);
  check(info && info.oppText.length > 0 && info.oppText === roomA.nameB,
    '★ 3 #opponent-info 的文本**恰好等于**对手名（多塞一个字就会打断既有断言）', info && { got: info.oppText, want: roomA.nameB });
  check(info && info.selfRankPresent === true, '6 自身段位节点 #match-self-rank 仍在', info && info.selfRankPresent);
  check(info && /^[0-9]+$/.test(info.countdown), '★ 7 倒计时仍在逐秒走（#countdown-timer 是数字）', info && info.countdown);
  check(info && info.barW > 0 && info.fillW > 0, '★ 8 倒计时进度条有真实宽度（没被重排压成 0）', info && { bar: info.barW, fill: info.fillW });
  check(info && info.startNowPresent === true, '9 #start-now 仍在 DOM 里（保留既有元素，不新增行为）', info && info.startNowPresent);
  check(info && info.vers && info.foe, '★ 10 对阵结构真的渲染出来了（.match-versus / .match-fighter-foe 在）', info && { vers: info.vers, foe: info.foe });
  await A.shot('match-success');

  // 等它自己走完 5 秒 → 进摆船；顺便证明「倒计时真的会推进」，不是钉在原地的假屏。
  const advanced = await A.waitFor(`!document.getElementById('match-success-screen').classList.contains('active')`, 12000);
  check(advanced === true, '★ 11 5 秒后自动离开这一屏（倒计时逻辑没被我改坏）', advanced);

  // ---- 对手 chip 行 ----
  // ⚠️ 这里必须用**桩数据**驱动。真实链路是 `showOpponentChips()` → `GET /user_stats?username=…`，
  //    而本工具的库是隔离库（`.tmp/rpsqc.db`），里面没有任何战绩，对手又只是个游客名字，
  //    所以真实请求只会返回空 —— 靠轮询等真 chips 是等不到的（实测等 6.5 秒仍是 `tags:0`）。
  //    这一段要证明的是「层级重排之后 chips 仍然落进 #opponent-chips、四个都齐、且不横向溢出」，
  //    用桩数据走的是**同一条渲染路径**，比等一个永远不来的响应有意义。
  await A.ev(`(function(){
    window.__mrRealFetch = window.fetch;
    window.__mrMockStats = {
      level_info: { level: 42 }, title_id: 'sea_emperor', title_name: '海皇', rank_info: null, show_rank: 0,
      tag_names: ['快枪手', '老船长'] };
    window.fetch = function(u){
      if (String(u).indexOf('/user_stats') === 0) {
        return Promise.resolve({ ok: true, json: function(){ return Promise.resolve({ stats: window.__mrMockStats }); } });
      }
      return window.__mrRealFetch.apply(this, arguments);
    };
    return true; })()`);
  await A.ev(`(function(){ var s=document.getElementById('match-success-screen');
    document.querySelectorAll('.screen').forEach(function(e){ e.classList.remove('active'); });
    s.classList.add('active'); window.scrollTo(0,0); return true; })()`);
  await A.ev(`(function(){ showOpponentChips(${JSON.stringify(roomA.nameB)}); return true; })()`);
  await sleep(500);
  const chips = await A.ev(`(function(){
    var box = document.getElementById('opponent-chips');
    if (!box) return { none: true };
    var q = function (sel) { var e = box.querySelector(sel); return e ? (e.textContent || '').trim() : null; };
    return { hidden: box.classList.contains('hidden'), lv: q('.match-chip.lv'), title: q('.match-chip.title'),
      tags: [].map.call(box.querySelectorAll('.match-chip.tag'), function (e) { return (e.textContent || '').trim(); }),
      scroll: box.scrollWidth - box.clientWidth,
      inScreen: !!document.querySelector('#match-success-screen #opponent-chips'),
      text: (box.textContent || '').trim() }; })()`);
  check(chips && chips.hidden === false && chips.lv === 'Lv.42' && chips.title === '海皇' && chips.tags.length === 2,
    '★ 4 对手 chip 行完整：等级 / 称号 / 两个标签都还在（层级重排没吃掉任何 chip）',
    chips && { lv: chips.lv, title: chips.title, tags: chips.tags, inScreen: chips.inScreen });
  const aura = await A.ev(`(function(){
    var s = document.getElementById('match-success-screen');
    var f = s.querySelector('.match-fighter-foe');
    return { kind: s.dataset.foeAura, color: getComputedStyle(f).getPropertyValue('--match-side-glow').trim(),
      rootColor: getComputedStyle(s).getPropertyValue('--match-foe-glow').trim(),
      matched: s.matches('html[data-arena-screens="v2"][data-arena-screen-list~="placement"] #match-success-screen[data-foe-aura="royal"]') };
  })()`);
  check(aura && aura.kind === 'royal' && aura.color === '#ffdc81',
    '★ 4b 公开称号「海皇」触发专属对阵光效', aura);
  check(chips && chips.scroll <= 1,
    '★ 5 chip 行不横向溢出（scrollWidth - clientWidth <= 1）', chips && chips.scroll);
  await A.shot('match-chips');
  for (const sample of [
    { title: 'storm_helmsman', level: 42, aura: 'storm', glow: '#a789ff' },
    { title: '', level: 100, aura: 'level-100', glow: '#ffe5a6' },
  ]) {
    const effect = await A.ev(`(async function(){
      window.__mrMockStats.title_id = ${JSON.stringify(sample.title)};
      window.__mrMockStats.level_info.level = ${sample.level};
      showOpponentChips(${JSON.stringify(roomA.nameB)});
      await new Promise(function(r){ setTimeout(r, 60); });
      var s = document.getElementById('match-success-screen');
      return { aura: s.dataset.foeAura,
        glow: getComputedStyle(s.querySelector('.match-fighter-foe')).getPropertyValue('--match-side-glow').trim() };
    })()`);
    check(effect && effect.aura === sample.aura && effect.glow === sample.glow,
      `★ 4c ${sample.title || '满级'}切换到对应光效`, effect);
  }
  await A.ev(`(function(){ if (window.__mrRealFetch) { window.fetch = window.__mrRealFetch; delete window.__mrRealFetch; }
    return true; })()`);

  // 几何：把这块屏重新点亮再量两档视口。
  // ⚠️ 只是**重新显示**它 —— 屏幕上那几条真实数据是上面真实流程填的，没有被伪造。
  for (const [w, h] of VIEWPORTS) {
    await A.front();
    await A.setViewport(w, h);
    await A.ev(`(function(){ var s=document.getElementById('match-success-screen');
      document.querySelectorAll('.screen').forEach(function(e){ e.classList.remove('active'); });
      s.classList.add('active'); window.scrollTo(0,0); return true; })()`);
    await sleep(300);
    const geo = await A.ev(`(function(){
      var ids = ['#match-success-screen .match-entry-heading h2', '#match-success-screen .match-versus',
                 '#match-success-screen #opponent-chips', '#match-success-screen .countdown-bar'];
      var rows = ids.map(function (sel) {
        var e = document.querySelector(sel); if (!e) return { sel: sel, miss: true };
        var r = e.getBoundingClientRect();
        return { sel: sel, miss: false, l: Math.round(r.left), t: Math.round(r.top),
                 r: Math.round(r.right), b: Math.round(r.bottom) };
      });
      var de = document.documentElement;
      var box = function (sel) { var e = document.querySelector(sel); if (!e) return null;
        var r = e.getBoundingClientRect();
        return { t: Math.round(r.top), b: Math.round(r.bottom), h: Math.round(r.height),
                 cy: Math.round(r.top + r.height / 2) }; };
      var scr = box('#match-success-screen');
      var cont = box('.game-container');
      var info = box('.match-info');
      var h2 = box('#match-success-screen .match-entry-heading h2');
      return { rows: rows, vw: window.innerWidth, vh: window.innerHeight,
        docScrollW: de.scrollWidth, docClientW: de.clientWidth,
        screenBottom: scr.b, containerBottom: cont.b,
        cellTop: (h2.t < info.t ? h2.t : info.t), cellBottom: info.b,
        versusCy: box('.match-versus').cy }; })()`);
    const vp = w + 'x' + h;
    check(geo && geo.docScrollW === geo.docClientW, `★ 12 ${vp} 匹配成功屏没有横向溢出`, geo && { scroll: geo.docScrollW, client: geo.docClientW });
    const outside = (geo.rows || []).filter((r) => !r.miss && (r.l < -1 || r.t < -1 || r.r > geo.vw + 1 || r.b > geo.vh + 1));
    check(geo && outside.length === 0, `★ 13 ${vp} 核心信息（标题 / 对阵板 / chip 行 / 进度条）全在首屏内`,
      outside.map((r) => r.sel + ' ' + r.l + ',' + r.t + '-' + r.r + ',' + r.b));
    check(geo && geo.rows.every((r) => !r.miss), `14 ${vp} 四个关键节点都还在 DOM 里`, (geo.rows || []).filter((r) => r.miss).map((r) => r.sel));

    // ---- 几何验收（2026-10-07 审查回单新增：★ 13a / 13b / 13c）----------------
    // 历史缺陷：`#match-success-screen.screen.active` 写了 justify-content:center，
    // 但它的父链全是 auto 高 ⇒ 这一屏的高度就等于自己的内容高（1280×720 实测 388px），
    // center 在**没有富余空间**的盒子里等于没写 —— 实拍 `03-match-success-1280x720.png`
    // 里标题贴着导航，视口下方 273px 全是空的。
    // ⚠️ 上面 ★13 只要求"在首屏内"：一个贴在顶部的 388px 小盒子**照样满足它**，
    //    所以这三条几何断言必须单独写死，且要能判死在"贴顶"这个状态上。
    // ① 这一屏真的取得了视口高度：屏底贴到容器底（差 ≤ 容器的下 padding），容器底贴到视口底。
    check(geo && (geo.containerBottom - geo.screenBottom) <= 26 && (geo.vh - geo.containerBottom) <= 48,
      `★ 13a ${vp} 匹配成功屏取得视口高度（屏底 / 容器底都落到底，不留整屏空白）`,
      geo && { screenBottom: geo.screenBottom, containerBottom: geo.containerBottom, vh: geo.vh,
        screenGap: geo.containerBottom - geo.screenBottom, pageGap: geo.vh - geo.containerBottom });
    // ② 对阵板**不贴近顶部**：它的中心要落在视口中部带（30%~70% 视口高）里。
    //    修前实测：1280×720 上 versus 中心在 186px = 25.8% 视口高 —— 贴着导航。
    const vRatio = geo ? geo.versusCy / geo.vh : -1;
    check(geo && vRatio >= 0.3 && vRatio <= 0.7,
      `★ 13b ${vp} 对阵板中心落在视口中部带（30%~70% 视口高，不贴顶）`,
      geo && { versusCy: geo.versusCy, vh: geo.vh, ratio: +vRatio.toFixed(3) });
    // ③ 核心区域（标题顶 → 信息块底）有充分高度：≥ 40% 视口高。
    const coreH = geo ? geo.cellBottom - geo.cellTop : 0;
    check(geo && coreH >= 0.4 * geo.vh, `★ 13c ${vp} 核心区域（标题 + 对阵信息块）占视口高 ≥ 40%`,
      geo && { coreH: coreH, vh: geo.vh, ratio: +(coreH / geo.vh).toFixed(3) });

    await A.shot('match-success-' + vp);
  }
  await A.clearViewport();
  // 还原：让真实流程继续（摆船那一步）
  await A.ev(`(function(){ var ids=['match-success-screen','ship-placement-screen'];
    ids.forEach(function(id){ var e=document.getElementById(id); if(e) e.classList.remove('active'); });
    document.getElementById('ship-placement-screen').classList.add('active'); return true; })()`);

  // ================= §2 猜拳：选中 / 重复提交 / 平局重试 =================
  const r1 = await openRps(A, B, 'B');
  check(r1.rpsShown === true, '★ 15 摆完船后真的进到猜拳屏（真实事件驱动）', r1.rpsShown);

  const st0 = await A.ev(RPS_STATE);
  check(st0 && st0.choices.length === 3 && st0.choices.every((c) => c.visible),
    '16 三个选项都在且可见', st0 && st0.choices.map((c) => c.choice + (c.visible ? '' : '(隐藏)')));
  check(st0 && pickedOf(st0).length === 0 && st0.waiting === false,
    '★ 17 刚进屏时没有任何选中 / 没有"等待中"（干净的初始态）', st0 && { picked: pickedOf(st0), waiting: st0.waiting });
  check(st0 && st0.choices.every((c) => c.disabled === false),
    '★ 18 三个选项都**没有**被 disabled（置灰会让既有十几个工具的 .click() 静默变空操作）', st0 && st0.choices.map((c) => c.disabled));

  const before1 = await A.ev('window.__mrHook.rps');
  const c1 = await clickChoice(A, 'rock');
  await sleep(350);
  const st1 = await A.ev(RPS_STATE);
  check(c1.ok === true, '19 真实鼠标点中「石头」', c1);
  check(st1 && pickedOf(st1).join(',') === 'rock',
    '★ 20 点完立刻**只有石头**是选中态（.picked）', st1 && pickedOf(st1));
  check(st1 && st1.choices.find((c) => c.choice === 'rock').aria === 'true'
    && st1.choices.filter((c) => c.choice !== 'rock').every((c) => c.aria === 'false'),
    '★ 21 aria-pressed 与视觉一致（无障碍读到的和看到的是同一件事）', st1 && st1.choices.map((c) => c.choice + '=' + c.aria));
  check(st1 && st1.waiting === true, '★ 22 同时显示「已出拳，等待对手…」（#rps-waiting 可见）', st1 && st1.waiting);

  // 等待期间再点一次别的：既不许改选中，更不许再发一次 rps_choice。
  const c2 = await clickChoice(A, 'paper');
  await sleep(400);
  const st2 = await A.ev(RPS_STATE);
  const after2 = await A.ev('window.__mrHook.rps');
  check(st2 && pickedOf(st2).join(',') === 'rock',
    '★ 23 等待期间再点「布」不改选中态（仍是石头）', { clicked: c2.topDesc, picked: st2 && pickedOf(st2) });
  check(after2 === before1 + 1,
    '★ 24 等待期间重复点击**没有再发一次 rps_choice**（出站计数只 +1）', { before: before1, after: after2 });

  // 对手出「布」→ 非平局收场。结果文案里必须写「你选择了石头」：
  // 若重复提交没被挡住，服务端会把 A 的出拳覆写成「布」，那这一局就是**平局**——
  // 所以这一条同时证明了「服务端用的是第一次出拳」。
  await clickChoice(B, 'paper');
  const settled1 = await A.waitFor(`(function(){ var r=document.getElementById('rps-result');
    return !!(r && !r.classList.contains('hidden')); })()`, 10000);
  const st3 = await A.ev(RPS_STATE);
  check(settled1 === true && st3.result === true, '★ 25 对手出拳后收到 rps_result（结果区可见）', st3 && st3.resultText);
  check(st3 && st3.resultTie === false && st3.resultText.indexOf('你选择了石头') >= 0,
    '★ 26 结算用的是**第一次**出拳（石头 vs 布），不是等待期间那一次点击', st3 && { tie: st3.resultTie, text: st3.resultText });

  // ---- 平局重试：另开一局，连平两次再分出胜负 ----
  const r2 = await openRps(A, B, 'C');
  check(r2.rpsShown === true, '27 第二局也进到猜拳屏', r2.rpsShown);

  const pairs = [['rock', 'rock'], ['scissors', 'scissors'], ['scissors', 'paper']];
  for (let i = 0; i < pairs.length; i++) {
    const [ca, cb] = pairs[i];
    const n = i + 1;
    const beforeN = await A.ev('window.__mrHook.rps');
    await clickChoice(A, ca);
    await sleep(250);
    const midA = await A.ev(RPS_STATE);
    check(midA && pickedOf(midA).join(',') === ca,
      `★ 28.${n} 第 ${n} 轮：A 点「${ca}」立刻上是选中态`, midA && pickedOf(midA));
    await clickChoice(B, cb);
    const done = await A.waitFor(`(function(){ var r=document.getElementById('rps-result');
      return !!(r && !r.classList.contains('hidden')); })()`, 10000);
    const stN = await A.ev(RPS_STATE);
    const afterN = await A.ev('window.__mrHook.rps');
    // ⚠️ 结果区是上一轮留下的，可能**还没换文案**就被读到 —— 轮次令牌就是为这个加的。
    //    这里以「服务端确实收到了一次出拳」+「文案已经落地」两条一起判。
    const isTie = i < pairs.length - 1;
    if (isTie) {
      check(done === true && stN && stN.resultTie === true && stN.resultText.indexOf('平局') >= 0,
        `★ 29.${n} 第 ${n} 轮平局：结果区写明「平局」（并带 is-tie 样式）`, stN && { tie: stN.resultTie, text: stN.resultText });
      check(stN && pickedOf(stN).length === 0,
        `★ 30.${n} 平局后选中态被清干净（三个选项都回到未选中）`, stN && pickedOf(stN));
      check(stN && stN.choices.every((c) => c.aria === 'false' && c.disabled === false),
        `★ 31.${n} 平局后三个选项都能再点（aria-pressed 复位、没有 disabled）`, stN && stN.choices.map((c) => c.choice + ':' + c.aria + ':' + c.disabled));
      check(stN && stN.waiting === false,
        `★ 32.${n} 平局后「等待中」提示收起来了`, stN && stN.waiting);
    } else {
      check(done === true && stN && stN.resultTie === false && stN.resultText.indexOf('你选择了' + (ca === 'scissors' ? '剪刀' : ca === 'rock' ? '石头' : '布')) >= 0,
        `★ 29.${n} 平局两次之后照常出结果（非平局，文案对得上）`, stN && { tie: stN.resultTie, text: stN.resultText });
    }
    check(afterN === beforeN + 1,
      `★ 33.${n} 第 ${n} 轮 A 只发了 1 次 rps_choice（平局重试没有变成重复提交）`, { before: beforeN, after: afterN });
  }

  // 离开猜拳屏再回来：不许留孤儿锁定。
  await A.ev(`(function(){ var g=document.getElementById('game-screen'); var r=document.getElementById('rps-screen');
    r.classList.remove('active'); g.classList.add('active'); return true; })()`);
  await sleep(200);
  const leftSt = await A.ev(RPS_STATE);
  check(leftSt && pickedOf(leftSt).length === 0 && leftSt.waiting === false,
    '★ 34 离开猜拳屏后没有留下任何选中 / 等待状态', leftSt && { picked: pickedOf(leftSt), waiting: leftSt.waiting });
  await A.ev(`(function(){ var g=document.getElementById('game-screen'); var r=document.getElementById('rps-screen');
    g.classList.remove('active'); r.classList.add('active'); return true; })()`);
  await sleep(200);
  const backSt = await A.ev(RPS_STATE);
  check(backSt && pickedOf(backSt).length === 0 && backSt.waiting === false,
    '★ 35 再回到猜拳屏仍是干净的（没有被上一轮的死状态锁住）', backSt && { picked: pickedOf(backSt), waiting: backSt.waiting });

  // ================= §3 快捷语：入口进聊天窗 + 双向回显 =================
  await A.ev(`(function(){ document.getElementById('rps-screen').classList.remove('active');
    document.getElementById('game-screen').classList.add('active'); return true; })()`);
  await sleep(300);
  await A.front(); await B.front(); await A.front();

  const cat = await A.ev(`fetch('/api/quick_chat').then(r => r.json()).catch(e => ({ __err: String(e) }))`);
  const item = (cat && cat.items || []).find((x) => x.id === 'hurry_flowers') || (cat && cat.items || [])[0];
  check(!!item, '36 拿到一条快捷语真值（从 GET /api/quick_chat 取，不信前端写死）', item && item.id);

  const entry = await A.ev(`(function(){
    var btn = document.getElementById('quick-chat-btn');
    var row = document.querySelector('#in-game-chat-container .in-game-chat-input-row');
    var c = document.getElementById('in-game-chat-container');
    var panel = document.getElementById('quick-chat-panel');
    if (!btn || !row || !c) return { miss: true, btn: !!btn, row: !!row, c: !!c };
    var b = btn.getBoundingClientRect();
    var r = row.getBoundingClientRect();
    return { inRow: row.contains(btn), inChat: c.contains(btn),
      panelOutsideChat: panel ? !c.contains(panel) : null,
      sameRowAsInput: row.contains(document.getElementById('in-game-chat-input')),
      tap: Math.round(Math.min(b.width, b.height)),
      rowH: Math.round(r.height) }; })()`);
  check(entry && entry.inRow === true && entry.sameRowAsInput === true,
    '★ 37 入口按钮真的在聊天输入行里（和输入框同一行）', entry);
  check(entry && entry.tap >= 40, '★ 38 入口按钮的可点尺寸 >= 40px（紧凑档的触摸下限）', entry && { tap: entry.tap, rowH: entry.rowH });
  check(entry && entry.panelOutsideChat === true,
    '★ 39 浮层不在聊天窗**内部**（聊天窗是 overflow:hidden，放进去会被整块裁掉）', entry && entry.panelOutsideChat);

  // 拖动聊天窗 → 按钮与浮层都要跟着走。
  await A.ev(`(function(){ var c=document.getElementById('in-game-chat-container');
    c.style.left='160px'; c.style.top='200px'; c.style.right='auto'; c.style.bottom='auto'; return true; })()`);
  await sleep(250);
  const moved = await A.ev(`(function(){
    var c=document.getElementById('in-game-chat-container'), b=document.getElementById('quick-chat-btn');
    var rc=c.getBoundingClientRect(), rb=b.getBoundingClientRect();
    return { contains: c.contains(b), dx: Math.round(rb.left - rc.left), dy: Math.round(rb.bottom - rc.bottom),
      inside: rb.left >= 0 && rb.top >= 0 && rb.right <= window.innerWidth && rb.bottom <= window.innerHeight }; })()`);
  check(moved && moved.contains === true && Math.abs(moved.dy) < 90 && moved.inside === true,
    '★ 40 聊天窗拖走之后按钮仍贴在它输入行里（不是孤悬在屏幕角落）', moved);

  // ★40b 视口变矮时的回拉。历史缺陷：makeFloatingDraggable 的 resize 处理器把当次 rect
  // 钉成绝对 left/top，于是「在 1440x900 下钉住的浮窗」在 768 高的视口里仍停在原处，
  // 整块沉到屏外 —— 输入框和行内的入口按钮一起点不到（对局屏 body 是 overflow:hidden，滚不到）。
  // 这里不真的改视口（CDP 改视口会牵动别的断言），而是把浮窗放到当前视口下方，
  // 再派发一个 resize 事件，验证处理器会把它连按钮一起拉回屏内。
  const pulledBack = await A.ev(`(function(){
    var c = document.getElementById('in-game-chat-container');
    if (!c) return { miss: true };
    var h = c.offsetHeight || 0;
    c.style.right = 'auto'; c.style.bottom = 'auto';
    c.style.left = '40px';
    c.style.top = (window.innerHeight - Math.round(h / 3)) + 'px';
    var before = c.getBoundingClientRect();
    window.dispatchEvent(new Event('resize'));
    var after = c.getBoundingClientRect();
    var b = document.getElementById('quick-chat-btn');
    var rb = b ? b.getBoundingClientRect() : null;
    return {
      vh: window.innerHeight,
      beforeBottom: Math.round(before.bottom),
      afterTop: Math.round(after.top), afterBottom: Math.round(after.bottom),
      inside: after.top >= -1 && after.left >= -1 && after.right <= window.innerWidth + 1 && after.bottom <= window.innerHeight + 1,
      btnInside: !!rb && rb.top >= 0 && rb.bottom <= window.innerHeight && rb.left >= 0 && rb.right <= window.innerWidth
    }; })()`);
  check(pulledBack && pulledBack.beforeBottom > pulledBack.vh && pulledBack.inside === true && pulledBack.btnInside === true,
    '★ 40b 视口变矮把浮窗推出屏外时，resize 会把整块浮窗（含入口按钮）拉回屏内', pulledBack);
  // 复位成 CSS 的右下角锚定，免得影响后面的浮层断言
  await A.ev(`(function(){ var c=document.getElementById('in-game-chat-container');
    if (c) { c.style.left='auto'; c.style.top='auto'; c.style.right='12px'; c.style.bottom='24px'; } return true; })()`);
  await sleep(200);

  const openBtn = await A.realClick('#quick-chat-btn');
  await sleep(400);
  const panel = await A.ev(`(function(){ var p=document.getElementById('quick-chat-panel');
    if (!p) return 'no-el'; var r=p.getBoundingClientRect(); var cs=getComputedStyle(p);
    return { visible: !p.hidden && r.width>0 && r.height>0 && cs.display!=='none' && cs.visibility!=='hidden',
      l: Math.round(r.left), t: Math.round(r.top), rr: Math.round(r.right), b: Math.round(r.bottom),
      vw: window.innerWidth, vh: window.innerHeight,
      modal: p.classList.contains('modal-overlay') }; })()`);
  check(openBtn.ok === true && panel !== 'no-el' && panel.visible === true,
    '★ 41 点入口能打开浮层（真实鼠标事件）', { click: openBtn, panel: panel });
  check(panel !== 'no-el' && panel.l >= 0 && panel.t >= 0 && panel.rr <= panel.vw + 1 && panel.b <= panel.vh + 1,
    '★ 42 浮层整体落在视口内（拖动之后再打开也不越界）', panel);
  check(panel !== 'no-el' && panel.modal === false, '★ 43 浮层不是 .modal-overlay（全屏遮罩会挡住棋盘）', panel && panel.modal);

  // 点浮层外面应当收起。
  // ⚠️ 既有 quick_chat_check 的候选点会被「超出视口的 host 矩形」整体滤掉（实测 outside 恒为 null）；
  //    这一版**不再拿 `#game-screen` 当 host** —— 走到这一步时界面停在猜拳屏，`#game-screen` 是
  //    display:none，它的 rect 恒为 [0,0,0,0]，于是每个候选点都被「host 太小」滤掉（实测诊断
  //    `{"err":"host-too-small","box":{"host":[0,0,0,0]}}`）。要点的本来就是「界面别处」，
  //    视口本身就是正确的搜索范围。改成在视口里**网格扫描**，并且返回诊断而不是干巴巴 null。
  const outside = await A.ev(`(function(){
    var panel = document.getElementById('quick-chat-panel');
    if (!panel) return { err: 'no-panel' };
    var pr = panel.getBoundingClientRect();
    var chat = document.getElementById('in-game-chat-container');
    var cr = chat ? chat.getBoundingClientRect() : null;
    var vw = window.innerWidth, vh = window.innerHeight;
    var box = { panel: [Math.round(pr.left), Math.round(pr.top), Math.round(pr.right), Math.round(pr.bottom)],
                chat: cr ? [Math.round(cr.left), Math.round(cr.top), Math.round(cr.right), Math.round(cr.bottom)] : null,
                vp: [vw, vh] };
    var inRect = function (r, x, y) { return !!r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom; };
    var tried = 0, sample = null;
    for (var y = 4; y <= vh - 4; y += 20) {
      for (var x = 4; x <= vw - 4; x += 20) {
        tried++;
        if (inRect(pr, x, y)) continue;            // 浮层自己身上不算「别处」
        if (inRect(cr, x, y)) continue;            // 聊天窗那一块也不算
        var top = document.elementFromPoint(x, y);
        if (!top) { sample = sample || 'elementFromPoint=null@' + x + ',' + y; continue; }
        if (panel.contains(top)) { sample = sample || 'panel-child ' + top.className + '@' + x + ',' + y; continue; }
        return { x: Math.round(x), y: Math.round(y), tried: tried,
          topDesc: top.tagName + (top.id ? '#' + top.id : '') + (top.className ? '.' + String(top.className).split(' ')[0] : ''), box: box };
      }
    }
    return { err: 'no-outside-point', tried: tried, sample: sample, box: box }; })()`);
  const outsideOk = !!(outside && typeof outside.x === 'number');
  check(outsideOk, '★ 44 找得到一个"浮层外面的公平点"（点界面别处，而不是视口死角）', outside);
  if (outsideOk) {
    await A.clickAt(outside.x, outside.y);
    await sleep(400);
  }
  const closedByOutside = await A.ev(`(function(){ var p=document.getElementById('quick-chat-panel');
    return p ? (p.hidden === true || getComputedStyle(p).display === 'none') : 'no-el'; })()`);
  check(outsideOk && closedByOutside === true, '★ 45 点界面别处能把浮层收起来（不会被困在菜单里）', { outside: outsideOk ? outside : outside, closed: closedByOutside });

  await A.realClick('#quick-chat-btn');
  await sleep(300);
  await A.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await A.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(350);
  const closedByEsc = await A.ev(`(function(){ var p=document.getElementById('quick-chat-panel');
    return p ? (p.hidden === true || getComputedStyle(p).display === 'none') : 'no-el'; })()`);
  check(closedByEsc === true, '★ 46 按 Esc 也能收起来（既有行为保留）', closedByEsc);

  // ---- 真发一条，验双向回显 ----
  const chatCount = (tab) => tab.ev(`(function(){ var box=document.getElementById('in-game-chat-messages');
    return box ? box.querySelectorAll('.in-game-chat-message').length : -1; })()`);
  await A.realClick('#quick-chat-btn');
  await A.waitFor(`!!document.querySelector('.quick-chat-item[data-msg-id="${item.id}"]')`, 6000);
  await sleep(200);
  const beforeChat = { a: await chatCount(A), b: await chatCount(B) };
  const beforeEmit = { a: await A.ev('window.__mrHook.chat'), b: await B.ev('window.__mrHook.chat') };
  const picked = await A.realClick(`.quick-chat-item[data-msg-id="${item.id}"]`);
  check(picked.ok === true, '47 点中快捷语条目（真实鼠标事件）', picked);
  await sleep(900);
  const afterChat = { a: await chatCount(A), b: await chatCount(B) };
  const afterEmit = { a: await A.ev('window.__mrHook.chat'), b: await B.ev('window.__mrHook.chat') };
  check(afterChat.a === beforeChat.a + 1, '★ 48 发送方聊天区**恰好 +1 条**', { before: beforeChat.a, after: afterChat.a });
  check(afterChat.b === beforeChat.b + 1, '★ 49 对手聊天区也**恰好 +1 条**（不是 0 条，也不是 2 条）', { before: beforeChat.b, after: afterChat.b });
  check(afterEmit.a === beforeEmit.a && afterEmit.b === beforeEmit.b,
    '★ 50 客户端**没有**绕道再 emit 一次 chat_message（回显只能靠服务端广播，出站计数必须不动）',
    { a: [beforeEmit.a, afterEmit.a], b: [beforeEmit.b, afterEmit.b] });

  const sides = await Promise.all([A, B].map((tab) => tab.ev(`(function(){
    var box = document.getElementById('in-game-chat-messages');
    if (!box) return 'no-el';
    var all = [].slice.call(box.querySelectorAll('.in-game-chat-message'));
    var last = all[all.length - 1];
    if (!last) return { none: true };
    return { cls: last.className, text: (last.textContent || '').trim(),
      hasMe: last.classList.contains('me'), hasOpp: last.classList.contains('opponent') }; })()`)));
  // ⚠️ 别把发送者名字写死。第一版断言 `indexOf('MrCA') >= 0` 是照抄 §2 最后一个房间的名字，
  //    但快捷语实际落在 A 当时所处的房间里（名字不同），于是两条断言都红。
  //    真正要证明的是「两侧看到的是同一个发送者，且都带原文」——名字由服务端定，不写死更严。
  const senderOf = (s) => (s && typeof s.text === 'string' && s.text.indexOf('：') > 0 ? s.text.slice(0, s.text.indexOf('：')) : '');
  const nameA0 = senderOf(sides[0]);
  const nameB0 = senderOf(sides[1]);
  check(sides[0] && sides[0].hasMe === true && sides[0].text.indexOf(item.text) >= 0 && nameA0.length > 0,
    '★ 51 发送方那条显示成「我发的」（.me）且带发送者名字与原文', sides[0]);
  check(sides[1] && sides[1].hasOpp === true && sides[1].text.indexOf(item.text) >= 0 && nameB0.length > 0 && nameB0 === nameA0,
    '★ 52 对手那条显示成「对方发的」（.opponent）、发送者与发送方看到的是同一个名字且带原文',
    { b: sides[1], aName: nameA0, bName: nameB0 });
  await A.shot('chat-echo');

  const logCount = (tab) => tab.ev(`(function(){ var box=document.getElementById('game-logs');
    return box ? ((box.textContent||'').split(${JSON.stringify(item.text)}).length - 1) : -1; })()`);
  const logs = { a: await logCount(A), b: await logCount(B) };
  check(logs.a === 1 && logs.b === 1, '★ 53 对局日志仍是**各恰好 1 行**（加了聊天回显之后没变成两行）', logs);

  const overflow = await A.ev(`(function(){ var de=document.documentElement;
    return { h: de.scrollHeight, vh: window.innerHeight, w: de.scrollWidth, vw: de.clientWidth }; })()`);
  check(overflow.w === overflow.vw, '★ 54 加了聊天回显之后页面仍无横向滚动', overflow);

  check(jsProblems.length === 0, 'Z1 全程零 JS 异常 / 零 console.error', jsProblems.slice(0, 5));
} catch (e) {
  problems.push('EXCEPTION: ' + (e && e.message));
  console.error('EXCEPTION', e && e.stack);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* 忽略 */ }
}

console.log('');
if (problems.length) {
  console.log('MATCH / RPS / CHAT CHECK FAILED (' + problems.length + '): ' + problems.join(' | '));
  process.exit(1);
}
console.log('MATCH / RPS / CHAT CHECK 全部通过');
process.exit(0);
