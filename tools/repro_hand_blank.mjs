#!/usr/bin/env node
/**
 * 诊断脚本：手牌「莫名其妙消失」到底是谁清的。
 *
 * 症状（作者反馈，无法描述确切场景）：
 *   · 打完一张手牌之后，剩下的手牌从界面上消失
 *   · 刷新网页 / 下一个大回合开始 → 又回来了
 *   · 说明【服务端手牌是好的】，是前端把渲染搞没了
 *
 * 做法：两个真实浏览器页面打一局真服务端，全程给 gameState.hand 装陷阱：
 *   · 每一次 hand 被赋值 → 记长度 + 调用栈
 *   · updateHandUI 抛异常 → 记下来
 *   · 每一步都比对：DOM 上的卡数 / gameState.hand 长度 / 服务端 magic_hand_count
 * 一旦三者不一致，就把当时的调用栈打出来 —— 那就是根因。
 *
 * 用法：node tools/repro_hand_blank.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9417;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/repro_hand_profile', APP], { stdio: 'ignore' });

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
  const ready = async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 15000) {
      if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) return true;
      await sleep(200);
    }
    return false;
  };
  return { ev, send, ws, ready, id: t.id, name: '?' };
}

async function closeTab(tab) {
  try { tab.ws.close(); } catch (e) {}
  try { await fetch(`http://127.0.0.1:${PORT}/json/close/${tab.id}`); } catch (e) {}
}

// ─────────────────────────────────────────────── 装陷阱
const TRAP = `(function(){
  if (window.__trapped) return 'already';
  window.__handTrace = [];
  window.__handErrors = [];
  window.addEventListener('error', function(e){
    window.__handErrors.push({where:'window.onerror', msg:e.message, stack:String(e.error && e.error.stack || '')});
  });
  var gs = window.gameState;
  var _hand = gs.hand;
  Object.defineProperty(gs, 'hand', {
    configurable: true, enumerable: true,
    get: function(){ return _hand; },
    set: function(v){
      var st = '';
      try { throw new Error('trace'); } catch(e){ st = String(e.stack||'').split('\\n').slice(1,5).join(' <- '); }
      window.__handTrace.push({
        before: Array.isArray(_hand) ? _hand.length : String(_hand),
        after: Array.isArray(v) ? v.length : String(v),
        ev: window.__lastEvent || null,
        stack: st
      });
      _hand = v;
    }
  });
  var orig = window.updateHandUI;
  window.updateHandUI = function(){
    try { return orig.apply(this, arguments); }
    catch (e) {
      window.__handErrors.push({where:'updateHandUI', msg:e.message, stack:String(e.stack||''),
                                handIsArray: Array.isArray(window.gameState.hand)});
      throw e;
    }
  };
  window.__trapped = true;
  return 'ok';
})()`;

// 把界面提示也记下来：出牌被拒时界面会弹一句原因，那是定位的关键
const TRAP_MSGS = `(function(){
  if (window.__msgsTrapped) return 'already';
  window.__msgs = [];
  ['showAlert','showMessage'].forEach(function(fn){
    var o = window[fn];
    if (typeof o !== 'function') return;
    window[fn] = function(){
      try { window.__msgs.push(fn + ': ' + String(arguments[0])); } catch (e) {}
      return o.apply(this, arguments);
    };
  });
  window.__msgsTrapped = true;
  return 'ok';
})()`;

// socket 的每个入站事件名都记下来，这样 hand 被改时能知道"是谁改的"
const TRAP_SOCKET = `(function(){
  var s = window.gameState.socket;
  if (!s) return 'no-socket';
  if (s.__trappedOnevent) return 'already';
  var orig = s.onevent.bind(s);
  s.onevent = function(packet){
    try {
      if (packet && packet.data) {
        window.__lastEvent = packet.data[0];
        window.__lastPayload = packet.data[1];
      }
    } catch (e) {}
    return orig(packet);
  };
  s.__trappedOnevent = true;
  window.__events = [];
  s.on('hand_updated', function(d){
    window.__events.push({ev:'hand_updated', len: (d && Array.isArray(d.hand)) ? d.hand.length : 'NO-HAND',
                          names: (d && Array.isArray(d.hand)) ? d.hand.map(function(c){return c && c.name;}) : null});
  });
  return 'ok';
})()`;

async function installTraps(tab) {
  const r = await tab.ev(TRAP);
  return r;
}

// ─────────────────────────────────────────────── 快照
async function snapshot(tab, pid) {
  return await tab.ev(`(function(){
    var hand = window.gameState.hand;
    var dom = document.querySelectorAll('#magic-hand .magic-card');
    var names = Array.prototype.map.call(dom, function(el){
      var n = el.querySelector('.card-name');
      return n ? n.textContent : '?';
    });
    return {
      dom: dom.length,
      domNames: names,
      state: Array.isArray(hand) ? hand.length : String(hand),
      stateNames: Array.isArray(hand) ? hand.map(function(c){ return c && c.name; }) : null,
      handEl: !!document.getElementById('magic-hand'),
      systemHidden: (function(){
        var s = document.getElementById('magic-system');
        return s ? getComputedStyle(s).display === 'none' : null;
      })(),
      traces: (window.__handTrace || []).length,
      errors: (window.__handErrors || []).length
    };
  })()`);
}

async function serverHand(tab, pid) {
  const r = await tab.ev(`new Promise(function(res){
    gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
  })`);
  if (!r || r.status !== 'success') return null;
  const p = r.game_state.players[pid];
  return p ? p.magic_hand_count : null;
}

async function dumpTraces(tab, label) {
  const t = await tab.ev('(window.__handTrace || [])');
  const e = await tab.ev('(window.__handErrors || [])');
  console.log(`\n### ${label} · hand 赋值轨迹 (${t ? t.length : 0} 次)`);
  if (Array.isArray(t)) {
    t.forEach((x, i) => {
      console.log(`  [${i}] ${x.before} -> ${x.after}`);
      console.log(`      ${String(x.stack).split(' <- ').slice(0, 3).join('\n      ')}`);
    });
  }
  console.log(`### ${label} · JS 错误 (${e ? e.length : 0} 次)`);
  if (Array.isArray(e)) e.forEach((x) => console.log('  · ' + x.where + ': ' + x.msg + '\n    ' + x.stack));
  await tab.ev('window.__handTrace = []; window.__handErrors = []; true');
}

// ─────────────────────────────────────────────── 通用 UI 处理
// 优先权弹窗 / 连锁弹窗一律点「放弃/取消」，别让流程卡住
async function dismissOverlays(tab) {
  return await tab.ev(`(function(){
    var acted = [];
    var pc = document.querySelector('#priority-cancel');
    if (pc) { pc.click(); acted.push('priority-cancel'); }
    var cc = document.querySelector('.chain-pass-btn, .chain-cancel-btn, #chain-pass');
    if (cc) { cc.click(); acted.push('chain-pass'); }
    return acted;
  })()`);
}

// 点第 idx 张手牌：第一次选中，第二次出牌（真实点击）
async function clickHandCard(tab, idx) {
  return await tab.ev(`(function(){
    var cards = document.querySelectorAll('#magic-hand .magic-card');
    if (!cards[${idx}]) return 'no-card';
    cards[${idx}].click();
    var cards2 = document.querySelectorAll('#magic-hand .magic-card');
    if (!cards2[${idx}]) return 'gone-after-select';
    cards2[${idx}].click();
    return 'clicked';
  })()`);
}

// 出牌后可能出现的目标选择 / 桃园选择界面：尽力点完
async function finishPendingUI(tab) {
  const actions = [];
  for (let i = 0; i < 12; i++) {
    const a = await tab.ev(`(function(){
      var ty = document.querySelector('.taoyuan-choice-overlay');
      if (ty) {
        var items = ty.querySelectorAll('.taoyuan-card-item:not(.disabled)');
        if (items.length) { items[0].click(); return 'taoyuan-pick'; }
        return 'taoyuan-wait';
      }
      var conf = document.querySelector('.inline-confirm, #confirm-magic-target, .magic-target-confirm');
      if (conf) { conf.click(); return 'confirm-target'; }
      var cells = document.querySelectorAll('.cell.magic-selection-overlay, .cell.selection-highlight');
      if (cells.length) { cells[0].click(); return 'pick-cell'; }
      var pc = document.querySelector('#priority-cancel');
      if (pc) { pc.click(); return 'priority-cancel'; }
      var cc = document.querySelector('.chain-pass-btn, .chain-cancel-btn, #chain-pass');
      if (cc) { cc.click(); return 'chain-pass'; }
      return null;
    })()`);
    if (a === null) break;
    actions.push(a);
    await sleep(350);
  }
  return actions;
}

// ─────────────────────────────────────────────── 开打
const A = await openTab(APP);
const B = await openTab(APP);
A.name = 'A'; B.name = 'B';
await A.ready(); await B.ready();
await installTraps(A);
await installTraps(B);

const created = await A.ev(`new Promise(function(res){
  ensureSocket();
  gameState.playerName = 'ReproA';
  gameState.socket.emit('create_room', { player_name: 'ReproA' }, function(r){ res(r); });
})`);
console.log('建房:', JSON.stringify(created));
const roomId = created.room_id;

const joined = await B.ev(`new Promise(function(res){
  ensureSocket();
  gameState.playerName = 'ReproB';
  gameState.socket.emit('join_room', { room_id: ${JSON.stringify(roomId)}, player_name: 'ReproB' },
    function(r){ res(r); });
})`);
console.log('B 入座:', JSON.stringify(joined));

await A.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await B.ev(`gameState.roomId = ${JSON.stringify(roomId)}; true`);
await A.ev(`gameState.playerId = ${JSON.stringify(joined.player_id)}; true`);

const st0 = await A.ev(`new Promise(function(res){
  gameState.socket.emit('test_get_game_state', { room_id: gameState.roomId }, function(x){ res(x); });
})`);
const pids = Object.keys(st0.game_state.players);
const bPid = joined.player_id;
const aPid = pids.find((p) => p !== bPid);
await A.ev(`gameState.playerId = ${JSON.stringify(aPid)}; true`);
await B.ev(`gameState.playerId = ${JSON.stringify(bPid)}; true`);
// 陷阱装完后再装一次：gameState 对象没换，所以不用；但要确认 gameState.hand 陷阱还在
console.log('A 陷阱:', await A.ev('window.__trapped === true'), ' B 陷阱:', await B.ev('window.__trapped === true'));
// socket 事件名陷阱必须等 ensureSocket() 之后才装得上
console.log('A socket 陷阱:', await A.ev(TRAP_SOCKET), ' B socket 陷阱:', await B.ev(TRAP_SOCKET));
console.log('A 提示陷阱:', await A.ev(TRAP_MSGS), ' B 提示陷阱:', await B.ev(TRAP_MSGS));

// 摆船 + 猜拳
const ships = (seed) => Array.from({ length: 6 }, (_, i) => ({
  positions: [{ x: i, y: seed === 0 ? i : 5 - i }], hits: [],
}));
await A.ev(`new Promise(function(res){
  gameState.socket.emit('place_ships', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(aPid)}, ships: ${JSON.stringify(ships(0))} }, function(r){ res(r); });
})`);
await B.ev(`new Promise(function(res){
  gameState.socket.emit('place_ships', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(bPid)}, ships: ${JSON.stringify(ships(1))} }, function(r){ res(r); });
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
console.log('先手:', attacker, '(A=' + aPid + ', B=' + bPid + ')');
if (!attacker) { console.log('猜拳没分出先手，退出'); process.exit(1); }

const atkTab = attacker === aPid ? A : B;
const dfnTab = attacker === aPid ? B : A;
const atkPid = attacker;
const dfnPid = attacker === aPid ? bPid : aPid;
await atkTab.ev(`gameState.playerId = ${JSON.stringify(atkPid)}; true`);
await dfnTab.ev(`gameState.playerId = ${JSON.stringify(dfnPid)}; true`);
console.log('攻击方 =', atkTab.name, ' 防守方 =', dfnTab.name);

// ⚠️ test_clear_all_effects 会清【房间里所有人】的手牌（不是只有 player_id 那个）。
// 所以必须先清一次，再依次给双方发牌；先给 B 发再给 A 清的话，B 会被清空。
async function clearHands(tab) {
  await tab.ev(`new Promise(function(res){
    gameState.socket.emit('test_clear_all_effects', { room_id: gameState.roomId,
      player_id: gameState.playerId }, function(r){ res(r); });
  })`);
  await sleep(300);
}

async function addCards(tab, pid, names) {
  for (const n of names) {
    await tab.ev(`new Promise(function(res){
      gameState.socket.emit('test_add_specific_magic_card', { room_id: gameState.roomId,
        player_id: ${JSON.stringify(pid)}, card_name: ${JSON.stringify(n)} }, function(r){ res(r); });
    })`);
  }
  await sleep(400);
}

await clearHands(atkTab);
await addCards(atkTab, atkPid, ['桃园结义', '无中生有', '增援']);
await addCards(dfnTab, dfnPid, ['无中生有', '桃园结义', '失灵！']);
await sleep(600);

async function report(label) {
  const sa = await snapshot(A, aPid);
  const sb = await snapshot(B, bPid);
  const ha = await serverHand(A, aPid);
  const hb = await serverHand(A, bPid);
  const bad = (sa.state !== ha) || (sa.dom !== ha) || (sb.state !== hb) || (sb.dom !== hb);
  console.log(`\n[${label}]`);
  console.log(`  A  DOM=${sa.dom} ${JSON.stringify(sa.domNames)}  state=${sa.state} ${JSON.stringify(sa.stateNames)}  server=${ha}  systemHidden=${sa.systemHidden}`);
  console.log(`  B  DOM=${sb.dom} ${JSON.stringify(sb.domNames)}  state=${sb.state} ${JSON.stringify(sb.stateNames)}  server=${hb}  systemHidden=${sb.systemHidden}`);
  if (sa.errors || sb.errors) console.log(`  ⚠️  JS 错误  A=${sa.errors} B=${sb.errors}`);
  if (bad) console.log('  ❌❌ 不一致！');
  // 增量打印：这一步里 hand 被谁改了
  for (const [tab, tag] of [[A, 'A'], [B, 'B']]) {
    const t = await tab.ev('(function(){ var t = window.__handTrace || []; window.__handTrace = []; return t; })()');
    const e = await tab.ev('(function(){ var e = window.__handErrors || []; window.__handErrors = []; return e; })()');
    const m = await tab.ev('(function(){ var m = window.__msgs || []; window.__msgs = []; return m; })()');
    if (Array.isArray(t) && t.length) {
      console.log(`  ── ${tag} hand 赋值 ${t.length} 次:`);
      t.forEach((x) => {
        const top = String(x.stack).split(' <- ');
        console.log(`     ${x.before} -> ${x.after}   ev=${x.ev}   @ ${top[1] || top[0]}`);
      });
    }
    if (Array.isArray(e) && e.length) {
      e.forEach((x) => console.log(`  ‼️ ${tag} ${x.where}: ${x.msg}\n     ${x.stack}`));
    }
    if (Array.isArray(m) && m.length) {
      m.forEach((x) => console.log(`  💬 ${tag} ${x}`));
    }
  }
  return { sa, sb, ha, hb, bad };
}

await report('发牌后');

// 通用的「找牌 + 真实点击出牌」步骤
async function playByName(tab, tag, name) {
  const idx = await tab.ev(`(function(){
    var cards = document.querySelectorAll('#magic-hand .magic-card');
    for (var i = 0; i < cards.length; i++) {
      var n = cards[i].querySelector('.card-name');
      if (n && n.textContent === ${JSON.stringify(name)}) return i;
    }
    return -1;
  })()`);
  console.log(`\n>>> ${tag} 点「${name}」 idx=${idx}`);
  if (idx < 0) return false;
  const r = await clickHandCard(tab, idx);
  console.log('    点击结果:', r);
  await sleep(600);
  console.log('    UI 动作:', JSON.stringify(await finishPendingUI(tab)));
  await sleep(2000);
  return true;
}

async function endTurn(tab, pid) {
  await tab.ev(`new Promise(function(res){
    gameState.socket.emit('test_end_turn', { room_id: gameState.roomId,
      player_id: ${JSON.stringify(pid)} }, function(r){ res(r); });
  })`);
  await sleep(1500);
  await dismissOverlays(tab);
  await sleep(800);
}

// ─────────── 准备阶段：攻击方打「无中生有」（速阶1，只能准备阶段打）
await playByName(atkTab, atkTab.name, '无中生有');
await report('攻击方准备阶段打出无中生有后');

// ─────────── 准备阶段：攻击方打「桃园结义」（速阶1，会同时改双方手牌）
await playByName(atkTab, atkTab.name, '桃园结义');
await report('攻击方打出桃园结义后');

// ─────────── 进战斗阶段
await dismissOverlays(dfnTab);
await atkTab.ev(`new Promise(function(res){
  gameState.socket.emit('enter_battle_phase', { room_id: gameState.roomId,
    player_id: ${JSON.stringify(atkPid)} }, function(r){ res(r); });
})`);
await sleep(900);
await dismissOverlays(dfnTab);
await sleep(1500);
await report('攻击方进入战斗阶段后');

// ─────────── 交回合 → 防守方准备阶段打牌
await endTurn(atkTab, atkPid);
await report('攻击方交回合后');

await playByName(dfnTab, dfnTab.name, '无中生有');
await report('防守方准备阶段打出无中生有后');

await playByName(dfnTab, dfnTab.name, '桃园结义');
await report('防守方打出桃园结义后');

// ─────────── 防守方交回合 → 攻击方再打一次（跨大回合）
await endTurn(dfnTab, dfnPid);
await report('防守方交回合后');

await dumpTraces(A, 'A 全量');
await dumpTraces(B, 'B 全量');

await closeTab(A);
await closeTab(B);
browser.kill();
process.exit(0);
