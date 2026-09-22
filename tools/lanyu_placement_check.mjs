#!/usr/bin/env node
/**
 * 滥竽充数「只摆了一艘就当成摆完」的前端回归（无头 Edge + CDP，**不需要服务端**）。
 *
 * 根因（时序，读代码 + 真机复现）：
 *   服务端 `handle_confirm_reinforcement` 每次落子后按顺序做两件事：
 *     ① `_emit_placement_request(...)` —— 若 `remaining > 0`，重发 `placement_request`
 *     ② `return {...}` —— 这个返回值被 flask-socketio 编成**本次 emit 的 ack**
 *   两者走同一条连接，**事件包先入队、ack 后入队** → 客户端先收到新的
 *   `placement_request`，再收到上一次落子的 ack。
 *
 *   而 `static/game.js` 的 `showPlacementPrompt`：
 *     · `socket.on('placement_request')` → `showPlacementPrompt(data)` 建**新的**面板
 *     · 确认按钮的 ack 回调成功分支 → `document.getElementById('placement-prompt').remove()`
 *   新面板刚建好，就被**上一次落子的 ack** 无条件删掉 → 第 2 艘开始再也没有窗口，
 *   玩家侧就是「只摆了一次就当摆完了 / 没摆满目标船数」。
 *
 *   ⚠️ 只有"一次放置流程要放 ≥2 艘"的卡才暴露：增援 / 死者苏生 / 绝处逢生都是 1 艘，
 *   第一艘落完 `remaining` 就归零、直接走 `placement_done`，ack 删掉的面板本来也该消失
 *   —— 所以这个 bug 被它们掩盖了很久。目前会 ≥2 艘的只有 `滥竽充数` 与
 *   `神机妙算`（重新部署多艘时）。
 *
 * 本工具用**真模板渲染的真页面 + 真 game.js**，只把 socket.io 打桩，
 * 从而精确控制「事件包」与「ack」的先后，把上面那个时序钉死。
 *   · 场景 A：新的 placement_request 先到、上一次的 ack 后到（服务端的真实顺序）
 *   · 场景 B：ack 先到、新的 placement_request 后到（顺序反过来也必须对）
 *
 * 用法：
 *   python tools/render_index_snapshot.py           # 先生成 .tmp/index_snapshot.html
 *   node tools/lanyu_placement_check.mjs
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const SNAPSHOT = path.join(ROOT, '.tmp', 'index_snapshot.html');
const PORT = 9471;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

if (!fs.existsSync(SNAPSHOT)) {
  console.error('缺少 ' + SNAPSHOT + '\n请先跑：python tools/render_index_snapshot.py');
  process.exit(2);
}

let failed = 0;
const check = (ok, label, detail) => {
  if (!ok) failed++;
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
};

// ---------------------------------------------------------------------------
// ① 只读本地文件的静态服务（没有服务端，没有真的 socket.io 连接）
// ---------------------------------------------------------------------------
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml' };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  const rel = decodeURIComponent(url.pathname);
  if (rel === '/' || rel === '/index.html') {
    res.writeHead(200, { 'Content-Type': MIME['.html'] });
    return res.end(fs.readFileSync(SNAPSHOT));
  }
  if (rel.startsWith('/static/')) {
    const file = path.join(ROOT, rel);
    if (fs.existsSync(file) && fs.statSync(file).isFile()) {
      res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
      return res.end(fs.readFileSync(file));
    }
  }
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('not found');
});
await new Promise((r) => server.listen(PORT, '127.0.0.1', r));
const APP = `http://127.0.0.1:${PORT}/`;

// ---------------------------------------------------------------------------
// ② 无头浏览器 + CDP
// ---------------------------------------------------------------------------
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + (PORT + 1),
  '--user-data-dir=' + path.join(ROOT, '.tmp', 'lanyu_placement_profile'),
  '--window-size=1600,1000', 'about:blank'], { stdio: 'ignore' });
await sleep(3000);

const list = await (await fetch(`http://127.0.0.1:${PORT + 1}/json/list`)).json();
const page = list.find((t) => t.type === 'page') || list[0];
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0; const pend = new Map();
ws.onmessage = (m) => {
  const x = JSON.parse(m.data);
  if (x.id && pend.has(x.id)) {
    const p = pend.get(x.id); pend.delete(x.id);
    x.error ? p.j(new Error(JSON.stringify(x.error))) : p.r(x.result);
  }
};
const send = (method, params = {}) => new Promise((r, j) => { const id = ++seq; pend.set(id, { r, j }); ws.send(JSON.stringify({ id, method, params })); });
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return 'EXC: ' + (r.exceptionDetails.exception?.description || '').slice(0, 300);
  return r.result && r.result.value;
};

// 页面里的每一处脚本之前先打桩：socket.io 的 **连接** 用一个 stub，
// 这样页面不会真的去连服务端；但事件处理器仍旧注册在真实的 socket.io 实例上
// （socket.io.js 会覆盖 window.io，我们不跟它抢）。
// 事件包由测试主动喂给 `socket.listeners(name)`、ack 由测试决定什么时候回
// —— 只有这样才能精确控制「事件包」与「ack」的先后，把时序钉死。
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
(function () {
  var SINK = [];
  window.__sink = SINK;
  // 只挡住"建连"这一件事：把 io 换成一个返回假连接对象的工厂。
  // 假连接对象上挂 __h/__emits/__acks，真正的 handler 由页面自己 on() 进来。
  var nativeIo = null;
  function makeStub() {
    function StubSocket() {
      this.connected = true;
      this.id = 'stub-sid';
      this.__h = {};
      this.__emits = [];
      this.__acks = [];
    }
    StubSocket.prototype.on = function (n, f) { (this.__h[n] = this.__h[n] || []).push(f); return this; };
    StubSocket.prototype.once = function (n, f) {
      var self = this;
      var wrap = function () { f.apply(null, arguments); self.off(n, wrap); };
      return self.on(n, wrap);
    };
    StubSocket.prototype.off = function (n, f) {
      if (!f) { delete this.__h[n]; return this; }
      this.__h[n] = (this.__h[n] || []).filter(function (x) { return x !== f; });
      return this;
    };
    StubSocket.prototype.emit = function (name) {
      var args = Array.prototype.slice.call(arguments, 1);
      var ack = (typeof args[args.length - 1] === 'function') ? args.pop() : null;
      this.__emits.push({ name: name, args: args });
      this.__acks.push(ack);
      SINK.push({ kind: 'client_emit', name: name, args: args });
      return this;
    };
    StubSocket.prototype.disconnect = function () { this.connected = false; return this; };
    StubSocket.prototype.listeners = function (n) { return (this.__h[n] || []).slice(); };
    StubSocket.prototype.__recv = function (name, data) {   // 等价于真的收到一个事件包
      SINK.push({ kind: 'server_event', name: name });
      var hs = (this.__h[name] || []).slice();
      for (var i = 0; i < hs.length; i++) hs[i](data);
      return hs.length;
    };
    var sock = new StubSocket();
    function io() { return sock; }
    io.connect = function () { return sock; };
    io.Socket = StubSocket;
    return { io: io, sock: sock };
  }
  var s = makeStub();
  window.__sock = s.sock;
  // socket.io.js 可能在 window.io 上装 getter/setter，用 defineProperty 强占
  Object.defineProperty(window, 'io', {
    configurable: true, get: function () { return s.io; },
    set: function (v) { nativeIo = v; },
  });
})();
`,
});

await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: APP });

let ready = false;
for (let i = 0; i < 60 && !ready; i++) {
  await sleep(250);
  ready = await ev(`!!(window.gameState && window.gameState.socket
    && window.gameState.socket.__h && window.gameState.socket.__h['placement_request']
    && window.gameState.socket.__h['placement_request'].length > 0)`);
}
if (ready !== true) {
  console.error('页面没就绪（placement_request 处理器没注册上），无法判定：', ready);
  browser.kill(); server.close();
  process.exit(2);
}
console.log('页面就绪：真模板 + 真 game.js + 打桩 socket。');
await ev(`(function(){ window.gameState.playerId='p1'; window.gameState.roomId='r1';
  window.gameState.maxShips=6; return true; })()`);

const BLOCKED = [];
for (let x = 0; x < 6; x++) { BLOCKED.push({ x: x, y: 0 }); BLOCKED.push({ x: x, y: 5 }); }

// 说明：页面里 #placement-prompt 里只有一个 <p class="placement-hint">，
// 「（第 N/M 艘）」这一步提示写在 hint 里（标题只有卡名），所以从 hint 取步数。
const panelState = `(function(){
  var p = document.getElementById('placement-prompt');
  if (!p) return null;
  var title = p.querySelector('h3');
  var hint = p.querySelector('.placement-hint');
  var cells = p.querySelectorAll('.placement-cell');
  var free = 0, blockedN = 0, selectedN = 0;
  cells.forEach(function(c){
    if (c.classList.contains('blocked')) blockedN++;
    else free++;
    if (c.classList.contains('selected')) selectedN++;
  });
  var btn = document.getElementById('placement-confirm');
  return { title: title ? title.textContent : '', hint: hint ? hint.textContent : '',
           total: cells.length, freeCells: free, blockedCells: blockedN, selected: selectedN,
           confirmDisabled: btn ? !!btn.disabled : null };
})()`;

const stepOf = (st) => {
  if (!st) return null;
  const m = /第\s*(\d+)\s*\/\s*(\d+)\s*艘/.exec(String(st.hint));
  return m ? m[1] + '/' + m[2] : null;
};

const recv = async (name, data, label) => {
  const n = await ev(`(function(){ return window.__sock.__recv(${JSON.stringify(name)}, ${JSON.stringify(data)}); })()`);
  check(typeof n === 'number' && n > 0, label, { handlers: n });
};

const clickFreeCell = async (label) => {
  const r = await ev(`(function(){
    var p = document.getElementById('placement-prompt');
    if (!p) return 'no-panel';
    var cell = null;
    p.querySelectorAll('.placement-cell').forEach(function(c){ if(!cell && !c.classList.contains('blocked')) cell = c; });
    if (!cell) return 'no-free-cell';
    cell.click();
    return cell.dataset.x + ',' + cell.dataset.y;
  })()`);
  check(typeof r === 'string' && r.includes(','), label, r);
  return r;
};

const titleIs = (st, want) => stepOf(st) === want;

// ---------------------------------------------------------------------------
console.log('\n=== 场景 A：新的 placement_request 先到、上一次落子的 ack 后到（服务端真实顺序）===');

await recv('placement_request', { kind: 'lanyu', remaining: 3, total: 3, placed: 0, blocked: BLOCKED },
  '① 收到第 1 次 placement_request');
let st = await ev(panelState);
check(titleIs(st, '1/3') && st.freeCells === 24 && st.blockedCells === 12 && st.selected === 0,
  '面板出现：第 1/3 艘、24 个可点格子（12 格被 blocked 灰掉）', st);

await clickFreeCell('点选第 1 艘的位置');
st = await ev(panelState);
check(!!st && st.selected === 1 && st.confirmDisabled === false, '点选后「确认」可用', st);

await ev(`document.getElementById('placement-confirm').click()`);
let acks = await ev(`window.__sock.__acks.filter(function(f){return !!f;}).length`);
check(acks === 1, '点「确认」发出了 confirm_reinforcement_position（带 ack）', { acks });
st = await ev(panelState);
check(titleIs(st, '1/3'), '面板先留着等 ack / 等新请求（本地不提前关）', st);

// 服务端：落子成功 → remaining 2 → 重发 placement_request
await recv('placement_request', { kind: 'lanyu', remaining: 2, total: 3, placed: 1, blocked: BLOCKED },
  '② 收到第 2 次 placement_request（服务端 remaining=2）');
st = await ev(panelState);
check(titleIs(st, '2/3') && st.selected === 0, '第 2 艘的面板出现在 DOM 里', st);

// ack 此刻才到 —— 这正是服务端的真实顺序（事件包先入队、ack 后入队）
await ev(`window.__sock.__acks[0]({ status: 'success', message: 'ok' })`);
st = await ev(panelState);
check(titleIs(st, '2/3'),
  '★ 上一次落子的 ack 不得删掉第 2 艘的面板（本 bug 的正面判据）', st);

await clickFreeCell('第 2 艘照样能点选');
await ev(`document.getElementById('placement-confirm').click()`);
await recv('placement_request', { kind: 'lanyu', remaining: 1, total: 3, placed: 2, blocked: BLOCKED },
  '③ 收到第 3 次 placement_request（服务端 remaining=1）');
st = await ev(panelState);
check(titleIs(st, '3/3'), '第 3 艘的面板出现在 DOM 里', st);
await ev(`window.__sock.__acks[1]({ status: 'success', message: 'ok' })`);
st = await ev(panelState);
check(titleIs(st, '3/3'), '★ 第 2 艘的 ack 也不得删掉第 3 艘的面板', st);

await clickFreeCell('第 3 艘也点得动');
await ev(`document.getElementById('placement-confirm').click()`);
// 三艘都落完：remaining 归零 → 服务端只发 placement_done
await recv('placement_done', { kind: 'lanyu' }, '④ 收到 placement_done（三艘已满）');
await ev(`window.__sock.__acks[2]({ status: 'success', message: 'ok' })`);
st = await ev(panelState);
check(st === null, '三艘都落完后面板才消失', st);
const leftover = await ev(`document.querySelectorAll('.placement-cell.selected').length`);
check(leftover === 0, '面板收干净（没有残留选中态）', { selected: leftover });
const confirmCount = await ev(`window.__sock.__emits.filter(function(e){
  return e.name === 'confirm_reinforcement_position'; }).length`);
check(confirmCount === 3, '★ 三艘各自确认了一次（落子 N 次 = 补满 N 艘）', { confirmCount });

// ---------------------------------------------------------------------------
console.log('\n=== 场景 B：ack 先到、新的 placement_request 后到（顺序反过来也必须对）===');
await ev(`window.__sock.__acks.length = 0`);
await recv('placement_request', { kind: 'lanyu', remaining: 2, total: 2, placed: 0, blocked: BLOCKED },
  '收到一次 placement_request（2 艘的流程）');
await clickFreeCell('点选第 1 艘');
await ev(`document.getElementById('placement-confirm').click()`);
await ev(`window.__sock.__acks[0]({ status: 'success', message: 'ok' })`);
st = await ev(panelState);
check(st === null, 'ack 先到时面板正常收掉（没有新请求在等）', st);
await recv('placement_request', { kind: 'lanyu', remaining: 1, total: 2, placed: 1, blocked: BLOCKED },
  '随后收到第 2 艘的 placement_request');
st = await ev(panelState);
check(titleIs(st, '2/2'), '面板重新出现（第 2/2 艘）', st);
await clickFreeCell('第 2 艘照样能点选');

// ---------------------------------------------------------------------------
console.log('\n' + (failed ? 'FAILED: ' + failed + ' 项断言失败' : 'ALL PASS（全部断言通过）'));

try { ws.close(); } catch (e) { /* ignore */ }
browser.kill();
server.close();
process.exit(failed ? 1 : 0);
