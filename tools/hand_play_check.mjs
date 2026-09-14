#!/usr/bin/env node
/**
 * 「出完一张牌，剩下的手牌消失」定点复现 + 回归。
 *
 * 根因（读代码得出的时序）：
 *   handle_use_magic_card 里，扣牌之后会走到 `_advance_chain_window`。
 *   对方手上一张速阶3都没有时，这个函数会【在同一个请求里同步调用 resolve_chain】，
 *   而 resolve_chain 收尾会向双方各推一次 hand_updated（手牌里已经没有刚打出的那张）。
 *   也就是说：**客户端先收到"新手牌"，随后才收到 use_magic_card 的 ack。**
 *
 *   前端 sendMagicCard 的 ack 回调要"本地把这张牌从手牌里删掉"，逻辑是：
 *     · 按身份找 → 找不到（服务端已经推过新手牌，牌早就不在了）
 *     · 兜底分支：`hand.length === sentIndex + 1` 时按下标删一张
 *   而"打出倒数第二张"恰好满足这个条件：
 *     手牌 ["A","B"]（sentIndex=0）→ 服务端推来 ["B"]（长度 1）→ 1 == 0+1 成立
 *     → 把剩下的那张 "B" 也删掉 → 手牌变成空 → 整块手牌区域空掉。
 *   刷新页面走重连快照，手牌就"回来"了 —— 与服务端手牌一直是好的完全吻合。
 *
 * 本工具就在真实浏览器 + 真服务端上走这条路径：
 *   给自己发 2 张牌、给对方发 0 张（保证连锁在同一请求内结算），
 *   真实点击打出第 1 张，然后断言剩下那张还在。
 *
 * 用法：node tools/hand_play_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9421;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/hand_play_profile', APP], { stdio: 'ignore' });

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

await sleep(3000);

async function openTab(url) {
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`,
    { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let seq = 0; const pend = new Map();
  ws.onmessage = (m) => {
    const x = JSON.parse(m.data);
    if (x.id && pend.has(x.id)) {
      const { res, rej } = pend.get(x.id); pend.delete(x.id);
      x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result);
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
  return { ev, ws, id: t.id,
    ready: async () => {
      const t0 = Date.now();
      while (Date.now() - t0 < 15000) {
        if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true;
        await sleep(200);
      }
      return false;
    } };
}

const A = await openTab(APP);
const B = await openTab(APP);
await A.ready(); await B.ready();

// 记下"服务端推手牌" 与 "出牌 ack" 谁先到 —— 这是本 bug 的关键时序
const TRAP = `(function(){
  window.__order = [];
  var s = gameState.socket;
  // 页面真实注册的监听器（socket.io 存在 _callbacks 里，事件名带 $ 前缀）。
  // 下面要"喂坏 payload"就得直接调它 —— 与真的收到事件等价。
  window.__realCallbacks = s._callbacks || {};
  var origOnevent = s.onevent.bind(s);
  s.onevent = function(packet){
    try {
      var name = packet && packet.data && packet.data[0];
      if (name === 'hand_updated') {
        var d = packet.data[1] || {};
        window.__order.push('hand_updated:' + ((d.hand || []).length)
          + (d.resync ? '(resync)' : ''));
      }
    } catch (e) {}
    return origOnevent(packet);
  };
  var origEmit = s.emit.bind(s);
  s.emit = function(event, payload, cb){
    if (event === 'use_magic_card' && typeof cb === 'function') {
      window.__order.push('emit:use_magic_card');
      return origEmit(event, payload, function(resp){
        window.__order.push('ack:use_magic_card');
        return cb(resp);
      });
    }
    return origEmit(event, payload, cb);
  };
  return 'ok';
})()`;

const created = await A.ev(`new Promise(function(res){
  ensureSocket();
  gameState.playerName = 'HandA';
  gameState.socket.emit('create_room', { player_name: 'HandA' }, function(r){ res(r); });
})`);
const roomId = created.room_id;
const joined = await B.ev(`new Promise(function(res){
  ensureSocket();
  gameState.playerName = 'HandB';
  gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name: 'HandB' },
    function(r){ res(r); });
})`);
await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await A.ev(`gameState.playerId = ${JSON.stringify(joined.player_id)}; true`);
const st0 = await A.ev(`new Promise(function(res){
  gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
})`);
const bPid = joined.player_id;
const aPid = Object.keys(st0.game_state.players).find((p) => p !== bPid);
await A.ev(`gameState.playerId = ${JSON.stringify(aPid)}; true`);
await B.ev(`gameState.playerId = ${JSON.stringify(bPid)}; true`);

const ships = (seed) => Array.from({ length: 6 }, (_, i) => ({
  positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [],
}));
await A.ev(`new Promise(function(res){
  gameState.socket.emit('place_ships', { room_id: gameState.roomId, player_id: ${JSON.stringify(aPid)},
    ships: ${JSON.stringify(ships(0))} }, function(r){ res(r); });
})`);
await B.ev(`new Promise(function(res){
  gameState.socket.emit('place_ships', { room_id: gameState.roomId, player_id: ${JSON.stringify(bPid)},
    ships: ${JSON.stringify(ships(1))} }, function(r){ res(r); });
})`);
let attacker = null;
for (let i = 0; i < 12 && !attacker; i++) {
  await A.ev(`new Promise(function(res){
    gameState.socket.emit('rps_choice', { room_id: gameState.roomId, player_id: ${JSON.stringify(aPid)},
      choice: 'rock' }, function(r){ res(r); });
  })`);
  await B.ev(`new Promise(function(res){
    gameState.socket.emit('rps_choice', { room_id: gameState.roomId, player_id: ${JSON.stringify(bPid)},
      choice: 'paper' }, function(r){ res(r); });
  })`);
  await sleep(400);
  const s = await A.ev(`new Promise(function(res){
    gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
  })`);
  attacker = s.game_state.current_attacker;
}
check(!!attacker, '猜拳分出先手', attacker);
const atkTab = attacker === aPid ? A : B;
const dfnTab = attacker === aPid ? B : A;
const atkPid = attacker;
const dfnPid = attacker === aPid ? bPid : aPid;
await atkTab.ev(`gameState.playerId = ${JSON.stringify(atkPid)}; true`);
await dfnTab.ev(`gameState.playerId = ${JSON.stringify(dfnPid)}; true`);
check(await atkTab.ev(TRAP) === 'ok', '时序探针已装上');

async function serverHand(tab, pid) {
  const r = await tab.ev(`new Promise(function(res){
    gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
  })`);
  return r && r.status === 'success' ? r.game_state.players[pid].magic_hand : null;
}

// 准备阶段：给攻击方 2 张【自己不摸牌】的速阶2（准备阶段可用），
// 防守方 0 张（保证连锁在同一请求内结算）。
// ⚠️ 不能用会摸牌的卡（无中生有/桃园结义）：它们会把手牌变成 3 张，
// 反而让下面那个错误兜底分支的条件不成立，掩盖掉 bug。
await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('test_clear_all_effects', { room_id: gameState.roomId,
    player_id: gameState.playerId }, function(r){ res(r); });
})`);
await sleep(300);
for (const n of ['五险一金', '看破！']) {
  await atkTab.ev(`new Promise(function(res){
    gameState.socket.emit('test_add_specific_magic_card', { room_id: gameState.roomId,
      player_id: ${JSON.stringify(atkPid)}, card_name: ${JSON.stringify(n)} }, function(r){ res(r); });
  })`);
}
await sleep(700);

const before = await atkTab.ev(`(function(){
  var el = document.querySelectorAll('#magic-hand .magic-card');
  return { dom: el.length,
           names: Array.prototype.map.call(el, function(e){
             var n = e.querySelector('.card-name'); return n ? n.textContent : '?'; }),
           state: (gameState.hand || []).map(function(c){ return c && c.name; }) };
})()`);
const srvBefore = await serverHand(atkTab, atkPid);
console.log('出牌前:', JSON.stringify(before), '服务端:', JSON.stringify(srvBefore));
check(before.dom === 2 && before.state.length === 2,
  '★ 前置条件：自己手上有 2 张牌（打第 1 张 = 打"倒数第二张"）', before);
check(srvBefore && srvBefore.length === 2, '前置条件：服务端手牌也是 2 张', srvBefore);
const dfnHand = await serverHand(atkTab, dfnPid);
check(Array.isArray(dfnHand) && dfnHand.length === 0,
  '前置条件：对方手上 0 张牌（连锁会在同一请求内结算）', dfnHand);

// 真实两步点击：选中第 0 张 → 再点一次出牌
const clicked = await atkTab.ev(`(function(){
  var cards = document.querySelectorAll('#magic-hand .magic-card');
  if (cards.length < 2) return 'only-' + cards.length;
  var name = cards[0].querySelector('.card-name').textContent;
  cards[0].click();
  var again = document.querySelectorAll('#magic-hand .magic-card');
  if (again[0]) again[0].click();
  return name;
})()`);
console.log('点击打出的牌:', clicked);
await sleep(2500);

const order = await atkTab.ev('window.__order || []');
console.log('事件时序:', JSON.stringify(order));
// 时序本身就是本 bug 的成立条件：服务端先推新手牌，ack 后到
const pushedFirst = order.indexOf('ack:use_magic_card') > order.findIndex((x) => String(x).startsWith('hand_updated:'));
check(pushedFirst, '★ 时序确认：服务端先推新手牌，出牌 ack 后到（bug 成立条件）', order);

const after = await atkTab.ev(`(function(){
  var el = document.querySelectorAll('#magic-hand .magic-card');
  return { dom: el.length,
           names: Array.prototype.map.call(el, function(e){
             var n = e.querySelector('.card-name'); return n ? n.textContent : '?'; }),
           state: (gameState.hand || []).map(function(c){ return c && c.name; }) };
})()`);
const srvAfter = await serverHand(atkTab, atkPid);
console.log('出牌后:', JSON.stringify(after), '服务端:', JSON.stringify(srvAfter));

check(srvAfter && srvAfter.length === 1, '服务端出牌后剩 1 张（权威结果）', srvAfter);
check(after.state.length === 1,
  '★ 打完一张后本地手牌还剩 1 张（不是被连带删空）', after.state);
check(after.dom === 1, '★ 界面上仍显示剩下的那 1 张牌', after);
check(JSON.stringify(after.state) === JSON.stringify(srvAfter),
  '★ 本地手牌与服务端手牌一致', { client: after.state, server: srvAfter });

// ────────────────────────────────────────────────────────────────
// 第二节：坏 payload 不能把手牌打成空白（"刷新才好"的另一个成因）
//
// 历史实现里 hand_updated 直接 `gameState.hand = data.hand`，而 updateHandUI
// 是【先清空容器再遍历 hand】。只要有一次 payload 不带 hand，hand 就变成
// undefined → 清空后遍历抛异常 → 整块手牌空白，且此后每次刷新手牌都抛异常，
// 只能靠刷新页面恢复。下面用真实页面喂坏数据，断言它不再被清空。
// ────────────────────────────────────────────────────────────────
console.log('\n--- 坏 payload 防御 ---');
await atkTab.ev(`(function(){
  window.__resync = 0;
  var s = gameState.socket;
  var orig = s.emit.bind(s);
  s.emit = function(ev, payload, cb){
    if (ev === 'request_hand_sync') { window.__resync += 1; }
    return orig(ev, payload, cb);
  };
  return true;
})()`);

const baseline = await atkTab.ev(`(gameState.hand || []).map(function(c){ return c.name; })`);
console.log('当前手牌:', JSON.stringify(baseline));

// ① payload 完全没有 hand 字段
const fired = await atkTab.ev(`(function(){
  // 直接调用页面真实注册的 hand_updated 监听器（与收到事件等价）
  if (!window.__realCallbacks) return 'no-callbacks';
  var list = window.__realCallbacks['$hand_updated'];
  if (!list || !list.length) return 'no-listener';
  list.forEach(function(cb){ cb({ room_id: gameState.roomId }); });   // 没有 hand
  return 'ok';
})()`);
check(fired === 'ok', '能喂到页面的 hand_updated 监听器（前置条件）', fired);
await sleep(400);
const afterBad = await atkTab.ev(`(function(){
  var el = document.querySelectorAll('#magic-hand .magic-card');
  return { dom: el.length, state: Array.isArray(gameState.hand) ? gameState.hand.length : String(gameState.hand),
           names: (gameState.hand || []).map(function(c){ return c && c.name; }) };
})()`);
check(afterBad.dom === baseline.length && afterBad.state === baseline.length,
  '★ 不带 hand 的 payload 不会把手牌清空', { before: baseline, after: afterBad });

// ② payload 里混入 null / 缺 name 的坏条目
await atkTab.ev(`(function(){
  var list = (window.__realCallbacks || {})['$hand_updated'] || [];
  list.forEach(function(cb){ cb({ hand: [null, {speed: 1}, 'junk'].concat(
    gameState.hand.map(function(c){ return c; })) }); });
  return true;
})()`);
await sleep(400);
const afterJunk = await atkTab.ev(`(function(){
  var el = document.querySelectorAll('#magic-hand .magic-card');
  return { dom: el.length, state: Array.isArray(gameState.hand) ? gameState.hand.length : String(gameState.hand),
           bad: (gameState.hand || []).filter(function(c){ return !c || !c.name; }).length };
})()`);
check(afterJunk.dom === baseline.length && afterJunk.bad === 0,
  '★ 坏条目被剔除，手牌不会变空白、也不会渲染出空洞', { after: afterJunk });

// ③ 检测到不对时应该主动要一份权威手牌（免刷新自愈）
const resyncCount = await atkTab.ev('window.__resync || 0');
check(resyncCount > 0, '★ 检测到 payload 不对时会请求服务端重发手牌（不必刷新页面）', resyncCount);
await sleep(900);
const healed = await atkTab.ev(`(function(){
  var el = document.querySelectorAll('#magic-hand .magic-card');
  return { dom: el.length, state: (gameState.hand || []).map(function(c){ return c && c.name; }) };
})()`);
console.log('重同步后:', JSON.stringify(healed), ' 服务端:', JSON.stringify(srvAfter));
check(healed.dom === srvAfter.length && JSON.stringify(healed.state) === JSON.stringify(srvAfter),
  '★ 重同步后本地手牌恢复成服务端权威值', { client: healed.state, server: srvAfter });

console.log('');
if (problems.length) {
  console.log(`✗ ${problems.length} 项未通过：`);
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}

try { A.ws.close(); await fetch(`http://127.0.0.1:${PORT}/json/close/${A.id}`); } catch (e) {}
try { B.ws.close(); await fetch(`http://127.0.0.1:${PORT}/json/close/${B.id}`); } catch (e) {}
browser.kill();
process.exit(problems.length ? 1 : 0);
