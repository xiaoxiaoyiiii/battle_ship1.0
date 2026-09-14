#!/usr/bin/env node
/**
 * 教皇旨意（改版后）的前端交互检查。
 *
 * 作者裁定：弃置魔法卡 → 攻击次数 +2 → 之后和正常攻击逻辑一样。
 *
 * 关键断言：
 *   · 教皇旨意生效 + 战斗阶段 + 我的回合 → 出现「弃卡换攻击 +2」按钮
 *   · 次数为 0 时点对手棋盘 → 弹弃卡窗（不直接攻击）
 *   · 选一张卡 → 发出 papal_discard（带 discard_card_index），不再带 x/y
 *   · ★ 次数 > 0 时点对手棋盘 → 发的是【普通 attack】，不能再弹弃卡窗
 *
 * 用法：node tools/papal_discard_check.mjs --url http://127.0.0.1:5000/
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
if (!EDGE) { console.error('找不到 Edge/Chrome'); process.exit(0); }

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/papal_check', '--window-size=1280,900', APP], { stdio: 'ignore' });
await sleep(3200);

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || ''))
  || list.find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
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
  setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout')); } }, 20000);
});
await send('Runtime.enable');
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return 'EXC: ' + JSON.stringify(r.exceptionDetails).slice(0, 250);
  return r.result && r.result.value;
};
const t0 = Date.now();
while (Date.now() - t0 < 15000) {
  if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break;
  await sleep(200);
}

// 进入对局界面 + 装一个只记录的假 socket
// ⚠️ 必须用真实的 updateTurnIndicator 设置回合状态：handleAttack 开头就判
// gameState.isMyTurn，直接点棋盘会因为它是 undefined 而静默 return
// （表现就是"点了没反应"，很容易误判成功能坏了）。
async function refreshTurn(attacker, attacks) {
  await ev(`(function(){
    if (typeof updateTurnIndicator === 'function') {
      updateTurnIndicator(${JSON.stringify(attacker)}, ${JSON.stringify(String(attacks))});
    }
    return true;
  })()`);
  await sleep(150);
}

await ev(`(function(){
  if (typeof switchScreen === 'function' && typeof gameScreen !== 'undefined' && gameScreen) {
    switchScreen(gameScreen);
  } else {
    document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
    var el = document.getElementById('game-screen');
    if (el) el.classList.add('active');
  }
  window.__sent = [];
  gameState.socket = {
    emit: function(name, payload, cb){
      window.__sent.push({ name: name, payload: payload });
      // 按真实服务端的响应形状回调，这样"本地删手牌 + 成功提示"那段才会执行
      if (typeof cb === 'function') {
        if (name === 'papal_discard') {
          cb({ status: 'success', discarded: '冻结', attacks_remaining: 2,
               message: '已弃置「冻结」，攻击次数 +2' });
        } else {
          cb({ status: 'success' });
        }
      }
    },
    on: function(){ return this; }
  };
  gameState.roomId = 'r1';
  gameState.playerId = 'me';
  gameState.currentAttacker = 'me';
  gameState.currentPhase = 'battle';
  gameState.fieldMagic = '教皇旨意';
  gameState.hand = [
    { name: '冻结', speed: 2, type: '普通' },
    { name: '轰炸', speed: 2, type: '普通' },
  ];
  window.__alerts = [];
  window.showAlert = function(m){ window.__alerts.push(String(m)); };
  window.showMessage = function(m){ window.__alerts.push('MSG:' + String(m)); };
  if (typeof updatePapalDiscardButton === 'function') updatePapalDiscardButton();
  return true;
})()`);
await sleep(300);
await refreshTurn('me', 0);

// ---- 1. 按钮出现 ----
const btnState = await ev(`(function(){
  var b = document.getElementById('papal-discard-btn');
  if (!b) return 'missing';
  var cs = getComputedStyle(b);
  return { exists: true, display: cs.display, text: b.textContent.trim() };
})()`);
check(btnState !== 'missing' && btnState.display !== 'none',
  '★ 教皇旨意 + 战斗阶段 + 我的回合 → 出现「弃卡换攻击 +2」按钮', btnState);
check(btnState !== 'missing' && /\+2/.test(btnState.text || ''), '按钮文案写明了 +2', btnState && btnState.text);

// 不是我的回合时应隐藏
await ev(`(function(){ gameState.currentAttacker='opp'; updatePapalDiscardButton(); return true; })()`);
await sleep(200);
const hiddenWhenNotMine = await ev(`getComputedStyle(document.getElementById('papal-discard-btn')).display`);
check(hiddenWhenNotMine === 'none', '不是我的回合时按钮隐藏', hiddenWhenNotMine);
await ev(`(function(){ gameState.currentAttacker='me'; updatePapalDiscardButton(); return true; })()`);
await sleep(200);

// ---- 2. 次数为 0 时点对手棋盘 → 弹弃卡窗 ----
await ev(`(function(){ window.__sent = []; window.__alerts = []; return true; })()`);
await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="1"][data-y="1"]');
  if (c) c.click();
  return true;
})()`);
await sleep(350);
const dlg = await ev(`(function(){
  var box = document.querySelector('.papal-discard-box');
  if (!box) return null;
  return {
    text: box.textContent.replace(/\\s+/g, ' ').trim().slice(0, 120),
    cards: Array.prototype.map.call(box.querySelectorAll('.papal-discard-card'), function(b){ return b.textContent; }),
  };
})()`);
const sentAfterBoardClick = await ev('window.__sent || []');
check(!!dlg, '★ 次数为 0 时点对手棋盘会弹弃卡窗', dlg);
check(!sentAfterBoardClick.some((s) => s.name === 'attack'),
  '★ 次数为 0 时不能直接发出普通 attack', sentAfterBoardClick.map((s) => s.name));
check(!!dlg && /\+2/.test(dlg.text), '弹窗写明了弃卡的作用是 +2（不是"打两次"）', dlg && dlg.text);
check(!!dlg && dlg.cards.length === 2, '弹窗列出了手牌', dlg && dlg.cards);

// ---- 3. 选一张 → 发 papal_discard，不带 x/y ----
await ev(`(function(){
  var b = document.querySelector('.papal-discard-box .papal-discard-card');
  if (b) b.click();
  return true;
})()`);
await sleep(350);
const sent = await ev('window.__sent || []');
const disc = sent.filter((s) => s.name === 'papal_discard');
check(disc.length === 1, '★ 选一张卡后发出 papal_discard', sent.map((s) => s.name));
check(disc.length === 1 && disc[0].payload.discard_card_index === 0,
  '带了要弃的卡下标', disc[0] && disc[0].payload);
check(disc.length === 1 && disc[0].payload.x === undefined && disc[0].payload.y === undefined,
  '★ 不再带 x/y（旧实现是用坐标一次性打两发）', disc[0] && disc[0].payload);
check(await ev(`document.querySelectorAll('.papal-discard-box').length`) === 0, '选完弹窗关闭');
check(await ev(`(gameState.hand || []).length`) === 1, '本地手牌也少了一张',
  await ev(`(gameState.hand || []).map(function(c){return c.name;})`));
const discMsgs = await ev('window.__alerts || []');
check(discMsgs.some((m) => /\+2/.test(m)), '弃卡后给出「攻击次数 +2」的提示', discMsgs);

// ---- 4. 次数 > 0 时点棋盘 → 走普通 attack ----
await ev(`(function(){ window.__sent = []; return true; })()`);
await refreshTurn('me', 2);   // 换到 2 次（走真实的回合指示器更新）
await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="2"][data-y="3"]');
  if (c) c.click();
  return true;
})()`);
await sleep(350);
const sent2 = await ev('window.__sent || []');
const atk = sent2.filter((s) => s.name === 'attack');
check(atk.length === 1, '★ 有次数时点棋盘走【普通 attack】', sent2.map((s) => s.name));
check(atk.length === 1 && atk[0].payload.x === 2 && atk[0].payload.y === 3,
  '攻击坐标正确（玩家自己选格子）', atk[0] && atk[0].payload);
check(await ev(`document.querySelectorAll('.papal-discard-box').length`) === 0,
  '★ 有次数时不再弹弃卡窗', await ev(`document.querySelectorAll('.papal-discard-box').length`));

// ---- 5. 场地被拆掉后按钮消失 ----
await ev(`(function(){ updateFieldMagicUI('opp', null); return true; })()`);
await sleep(250);
const afterFieldGone = await ev(`getComputedStyle(document.getElementById('papal-discard-btn')).display`);
check(afterFieldGone === 'none', '场地被拆除后按钮消失', afterFieldGone);

// ---- 6. 没有手牌时点棋盘给出明确提示 ----
await ev(`(function(){
  gameState.fieldMagic = '教皇旨意';
  gameState.hand = [];
  window.__alerts = [];
  updatePapalDiscardButton();
  return true;
})()`);
await refreshTurn('me', 0);
await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="0"][data-y="0"]');
  if (c) c.click();
  return true;
})()`);
await sleep(300);
const noHandAlerts = await ev('window.__alerts || []');
check(noHandAlerts.some((m) => /没有手牌/.test(m)),
  '没手牌时给出明确提示（不是静默什么都不做）', noHandAlerts);

console.log('');
if (problems.length) {
  console.log(`✗ ${problems.length} 项未通过：`);
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}
try { ws.close(); } catch (e) {}
browser.kill();
process.exit(problems.length ? 1 : 0);
