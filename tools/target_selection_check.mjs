#!/usr/bin/env node
/**
 * 范围选择（区域 / 整行整列 / 连续格）的可视化检查 + 截图。
 *
 * 覆盖三张卡的三种选择模式：
 *   · 冻结（3×3 区域）、探测雷达（2×2）
 *   · 轰炸（整行 / 整列）
 *   · 硫磺火焰（自由连选 6 格）
 *
 * 每个模式都会：真实调 showMagicTargetSelection → 点选若干格 → 截图，
 * 并断言「选中态在视觉上足够明显」：
 *   · 至少有一个明显不同于未选中格的计算样式（背景/描边/阴影/动画）
 *   · 页面上有文字告诉玩家选了哪里
 *
 * 用法：node tools/target_selection_check.mjs --url http://127.0.0.1:5000/ [--shots 目录]
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOTS = argOf('--shots', '');
const PORT = 9407;
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
  '--user-data-dir=C:/Windows/Temp/target_sel', '--window-size=1400,1000', APP], { stdio: 'ignore' });
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
await send('Page.enable');
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

async function shot(name) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  const r = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(SHOTS, name + '.png'), Buffer.from(r.data, 'base64'));
}

// 造一个真实棋盘：对手 5 艘船 + 己方 3 艘
const SETUP = `(function(){
  if (typeof switchScreen === 'function') { try { switchScreen('gameScreen'); } catch(e){} }
  gameState.roomId = 'r1';
  gameState.playerId = 'me';
  gameState.currentPhase = 'battle';
  gameState.currentAttacker = 'me';
  gameState.opponentAttacks = [];
  gameState.revealedCells = [];
  gameState.ships = [ {positions:[{x:0,y:0}],hits:[],frozen:false},
                      {positions:[{x:2,y:3}],hits:[],frozen:false},
                      {positions:[{x:5,y:1}],hits:[],frozen:false} ];
  gameState.opponentShips = [ {positions:[{x:1,y:1}],hits:[],frozen:false},
                              {positions:[{x:3,y:2}],hits:[],frozen:false},
                              {positions:[{x:4,y:4}],hits:[],frozen:false},
                              {positions:[{x:0,y:5}],hits:[],frozen:false},
                              {positions:[{x:5,y:0}],hits:[],frozen:false} ];
  initGameBoards();
  window.__alerts = [];
  window.showAlert = function(m){ window.__alerts.push(String(m)); };
  return document.querySelectorAll('#opponent-board .cell').length;
})()`;
const cellCount = await ev(SETUP);
check(cellCount === 36, '对手棋盘渲染出 36 格', cellCount);

/** 读某格的视觉特征（用于判断"看得见"）。 */
const CELL_STYLE = `(function(sel){
  var el = document.querySelector(sel);
  if (!el) return null;
  var cs = getComputedStyle(el);
  var before = getComputedStyle(el, '::before');
  return {
    bg: cs.backgroundColor,
    bgImage: cs.backgroundImage,
    outline: cs.outlineWidth + ' ' + cs.outlineStyle + ' ' + cs.outlineColor,
    boxShadow: cs.boxShadow,
    border: cs.borderTopWidth + ' ' + cs.borderTopColor,
    animation: cs.animationName,
    opacity: cs.opacity,
    beforeBg: before.backgroundColor,
    beforeContent: before.content,
  };
})`;

function signature(s) {
  return s ? [s.bg, s.outline, s.boxShadow, s.border, s.animation, s.beforeBg].join('|') : 'null';
}

// ---------------------------------------------------------------- 场景 1：冻结 3×3
console.log('--- 场景 1：冻结（3×3 区域点选）---');
await ev(`(function(){ showMagicTargetSelection({name:'冻结', speed:1, type:'普通'}, 0); return true; })()`);
await sleep(450);
const areaIdle = await ev(`${CELL_STYLE}('#opponent-board .cell[data-x="0"][data-y="0"]')`);
// 点选 3×3 区域（起点 1,1）
await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="1"][data-y="1"]');
  if (c) c.click();
  return true;
})()`);
await sleep(450);
const areaSel = await ev(`${CELL_STYLE}('#opponent-board .cell[data-x="1"][data-y="1"]')`);
const areaCount = await ev(`document.querySelectorAll('#opponent-board .cell.selection-highlight').length`);
check(areaCount === 9, '点选后高亮 9 格（3×3）', areaCount);
check(signature(areaIdle) !== signature(areaSel),
  '选中格与未选中格有可见差异', { idle: signature(areaIdle), sel: signature(areaSel) });
// 可见性判定：背景填充足够不透明，或有描边/阴影/动画
function visible(s) {
  if (!s) return false;
  const alpha = (bg) => {
    const m = /rgba?\(([^)]+)\)/.exec(bg || '');
    if (!m) return 0;
    const p = m[1].split(',').map((v) => parseFloat(v));
    return p.length >= 4 ? p[3] : 1;
  };
  const strongBg = alpha(s.bg) >= 0.3;
  const hasOutline = parseFloat(s.outline) >= 2 && !/none/.test(s.outline);
  const hasShadow = s.boxShadow && s.boxShadow !== 'none';
  const hasAnim = s.animation && s.animation !== 'none';
  return strongBg || hasOutline || hasShadow || hasAnim;
}
check(visible(areaSel), '★ 选中格视觉强度足够（不透明度≥0.3 / 描边 / 阴影 / 动画）', areaSel);
check(areaSel && /^\s*("")?\s*$/.test(String(areaSel.beforeContent || '')) === false || !!areaSel.beforeContent,
  '（参考）选中格 ::before 内容', areaSel && areaSel.beforeContent);
const areaLabel = await ev(`(function(){
  var bar = document.querySelector('.area-picker-bar');
  if (!bar) return null;
  return { text: bar.textContent.trim(), html: bar.innerHTML.length };
})()`);
check(!!areaLabel && /\d/.test(areaLabel.text), '★ 确认条上写出了「选中的是哪一块」', areaLabel);
await shot('1-area-selected');

// 换一个位置，确认标签跟着变
await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="3"][data-y="3"]');
  if (c) c.click();
  return true;
})()`);
await sleep(350);
const areaLabel2 = await ev(`(function(){
  var bar = document.querySelector('.area-picker-bar');
  return bar ? bar.textContent.trim() : null;
})()`);
check(areaLabel && areaLabel2 && areaLabel2 !== areaLabel.text,
  '换位置后标签随之更新', { before: areaLabel && areaLabel.text, after: areaLabel2 });
await shot('2-area-moved');
await ev(`(function(){ var b=document.querySelector('#area-cancel'); if(b) b.click(); return true; })()`);
await sleep(300);

// ---------------------------------------------------------------- 场景 2：轰炸（整行）
console.log('--- 场景 2：轰炸（整行/整列）---');
await ev(`(function(){ showMagicTargetSelection({name:'轰炸', speed:2, type:'普通'}, 0); return true; })()`);
await sleep(450);
await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="0"][data-y="2"]');
  if (c) c.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
  return true;
})()`);
await sleep(400);
const lineSel = await ev(`${CELL_STYLE}('#opponent-board .cell[data-x="3"][data-y="2"]')`);
const lineCount = await ev(`document.querySelectorAll('#opponent-board .cell.magic-selection-overlay').length`);
check(lineCount === 6, '整行高亮 6 格', lineCount);
check(visible(lineSel), '★ 整行高亮的视觉强度足够', lineSel);
const lineLabel = await ev(`(function(){
  var p = document.querySelector('.magic-target-prompt');
  return p ? p.textContent.trim() : null;
})()`);
check(!!lineLabel && /\d/.test(lineLabel),
  '★ 提示文字里写出了「第几行/列」', lineLabel);
await shot('3-line-selected');
await ev(`(function(){ var b=document.querySelector('#cancel-target'); if(b) b.click(); return true; })()`);
await sleep(300);

// ---------------------------------------------------------------- 场景 3：硫磺火焰（连续 6 格）
console.log('--- 场景 3：硫磺火焰（连选 6 格）---');
await ev(`(function(){ showMagicTargetSelection({name:'硫磺火焰', speed:2, type:'普通'}, 0); return true; })()`);
await sleep(450);
for (const [x, y] of [[0, 3], [1, 3], [2, 3]]) {
  await ev(`(function(){
    var c = document.querySelector('#opponent-board .cell[data-x="${x}"][data-y="${y}"]');
    if (c) c.click();
    return true;
  })()`);
  await sleep(180);
}
await sleep(300);
const contSel = await ev(`${CELL_STYLE}('#opponent-board .cell[data-x="1"][data-y="3"]')`);
const contCount = await ev(`document.querySelectorAll('#opponent-board .cell.magic-selection-overlay').length`);
check(contCount === 3, '已选 3 格', contCount);
check(visible(contSel), '★ 连选高亮的视觉强度足够', contSel);
const contLabel = await ev(`(function(){
  var p = document.querySelector('.magic-target-prompt');
  return p ? p.textContent.trim() : null;
})()`);
check(!!contLabel && /3/.test(contLabel),
  '★ 提示文字里写出了「已选几格 / 还需几格」', contLabel);
await shot('4-continuous-selected');
await ev(`(function(){ var b=document.querySelector('#cancel-target'); if(b) b.click(); return true; })()`);
await sleep(300);

// ---------------------------------------------------------------- 场景 4：两种模式的颜色互不干扰
console.log('--- 场景 4：先后打开两种选择模式，样式不互相污染 ---');
// 先开轰炸（行），读样式；关掉；再开硫磺火焰，读样式
await ev(`(function(){ showMagicTargetSelection({name:'轰炸', speed:2, type:'普通'}, 0); return true; })()`);
await sleep(400);
await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="0"][data-y="0"]');
  if (c) c.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
  return true;
})()`);
await sleep(300);
const firstModeBg = await ev(`${CELL_STYLE}('#opponent-board .cell[data-x="2"][data-y="0"]')`);
await ev(`(function(){ var b=document.querySelector('#cancel-target'); if(b) b.click(); return true; })()`);
await sleep(300);
await ev(`(function(){ showMagicTargetSelection({name:'硫磺火焰', speed:2, type:'普通'}, 0); return true; })()`);
await sleep(400);
await ev(`(function(){
  var c = document.querySelector('#opponent-board .cell[data-x="0"][data-y="0"]');
  if (c) c.click();
  return true;
})()`);
await sleep(300);
const secondModeBg = await ev(`${CELL_STYLE}('#opponent-board .cell[data-x="0"][data-y="0"]')`);
check(visible(firstModeBg) && visible(secondModeBg),
  '★ 两种模式先后使用都保持可见（旧实现抢同一个 <style> 标签，后一种会失效）',
  { line: firstModeBg && firstModeBg.bg, continuous: secondModeBg && secondModeBg.bg });
await ev(`(function(){ var b=document.querySelector('#cancel-target'); if(b) b.click(); return true; })()`);

// ---------------------------------------------------------------- 场景 5：压着船的格子也要能盖上去
console.log('--- 场景 5：选区压着「自己的船」时高亮仍可见 ---');
// 注意：对手棋盘的格子永远不会带 .ship（对手的船本来是隐藏的），
// 所以这里必须走「神威！→ 己方棋盘」这条路 —— 那才是
// .cell.ship { background: var(--ship-metal) !important } 生效的地方。
// 对局中己方棋盘的 id 是 #game-player-board（#player-board 是布船界面的那个）。
const SELF_BOARD = '#game-player-board';
await ev(`(function(){
  gameState.ships = [ {positions:[{x:2,y:2}],hits:[],frozen:false} ];
  gameState.opponentShips = [];
  gameState.opponentAttacks = [];
  gameState.revealedCells = [];
  initGameBoards();
  return true;
})()`);
await sleep(350);
const shipCellSel = SELF_BOARD + ' .cell[data-x="2"][data-y="2"]';
const shipClass = await ev(`(function(){
  var c = document.querySelector(${JSON.stringify(shipCellSel)});
  return c ? c.className : 'no-cell';
})()`);
check(/ship/.test(String(shipClass)), '（前提）该格确实带 ship 类', shipClass);
const shipIdle = await ev(`${CELL_STYLE}(${JSON.stringify(shipCellSel)})`);
check(!!shipIdle && shipIdle.bgImage && shipIdle.bgImage !== 'none',
  '（前提）船的底色是不透明渐变（金属色）', shipIdle && shipIdle.bgImage);

// 神威！ → 选己方棋盘 → 点选覆盖 (2,2) 的 3×3
await ev(`(function(){ showMagicTargetSelection({name:'神威！', speed:3, type:'普通'}, 0); return true; })()`);
await sleep(450);
const pickedSelf = await ev(`(function(){ var b=document.getElementById('shenwei-pick-self'); if(b) b.click(); return !!b; })()`);
check(pickedSelf === true, '（前提）能切到「己方棋盘」', pickedSelf);
await sleep(550);
const clicked = await ev(`(function(){
  var cells = document.querySelectorAll(${JSON.stringify(SELF_BOARD + ' .cell')});
  // 点 (0,0) → 3×3 覆盖 (0..2, 0..2)，包含 (2,2) 这艘船
  var target = null;
  for (var i = 0; i < cells.length; i++) {
    if (cells[i].dataset.x === '0' && cells[i].dataset.y === '0') { target = cells[i]; break; }
  }
  if (target) target.click();
  return { total: cells.length, clicked: !!target };
})()`);
check(clicked && clicked.total === 36 && clicked.clicked, '（前提）己方棋盘 36 格且已点选', clicked);
await sleep(500);
const shipSel = await ev(`${CELL_STYLE}(${JSON.stringify(shipCellSel)})`);
check(shipSel && shipSel.bgImage === 'none',
  '★ 选中后船的金属渐变被压掉（background 简写 + !important 生效）',
  shipSel && { bg: shipSel.bg, bgImage: shipSel.bgImage });
check(visible(shipSel), '★ 压着船的选中格视觉强度足够', shipSel);
await ev(`(function(){
  document.querySelectorAll('.magic-target-prompt, .area-picker-bar').forEach(function(e){ e.remove(); });
  if (typeof gameState.selectionCleanup === 'function') { try { gameState.selectionCleanup(); } catch(e){} gameState.selectionCleanup = null; }
  gameState.selectingOnBoard = false;
  return true;
})()`);
await sleep(300);

// ---------------------------------------------------------------- 场景 6：连选未选满时确认按钮禁用
console.log('--- 场景 6：连选未满格时确认按钮禁用 ---');
await ev(`(function(){ showMagicTargetSelection({name:'硫磺火焰', speed:2, type:'普通'}, 0); return true; })()`);
await sleep(400);
const btnInitial = await ev(`(function(){ var b=document.getElementById('confirm-continuous'); return b ? b.disabled : 'no-btn'; })()`);
check(btnInitial === true, '刚打开时确认按钮是禁用的', btnInitial);
for (const [x, y] of [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0]]) {
  await ev(`(function(){
    var c = document.querySelector('#opponent-board .cell[data-x="${x}"][data-y="${y}"]');
    if (c) c.click();
    return true;
  })()`);
  await sleep(120);
}
await sleep(300);
const btnFull = await ev(`(function(){ var b=document.getElementById('confirm-continuous'); return b ? b.disabled : 'no-btn'; })()`);
const fullInfo = await ev(`(function(){ var i=document.getElementById('cont-picker-info'); return i ? i.textContent : null; })()`);
check(btnFull === false, '选满 6 格后确认按钮可用', { disabled: btnFull, info: fullInfo });
check(!!fullInfo && /6\s*\/\s*6/.test(fullInfo), '提示文字显示 6 / 6', fullInfo);
await ev(`(function(){ var b=document.querySelector('#cancel-target'); if(b) b.click(); return true; })()`);
await sleep(300);

console.log('');
if (problems.length) {
  console.log(`✗ ${problems.length} 项未通过：`);
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}
if (SHOTS) console.log('截图目录: ' + SHOTS);

try { ws.close(); } catch (e) {}
browser.kill();
process.exit(problems.length ? 1 : 0);
