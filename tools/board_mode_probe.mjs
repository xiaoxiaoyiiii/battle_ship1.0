#!/usr/bin/env node
/* 移动档棋盘模式探针：在五个紧凑视口下读 .boards-container[data-mode] 与
   #game-screen[data-boards]，以及实际格宽 —— 用来判断 Phase 5.2「改判据走 tabs」
   到底还需不需要改（先实测，再动手）。 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const PORT = 9468;
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome'); process.exit(0); }
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--remote-debugging-port=' + PORT, '--user-data-dir=C:/Windows/Temp/board_mode_profile', APP], { stdio: 'ignore' });
await sleep(3500);
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list[0];
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0; const pend = new Map();
ws.onmessage = (m) => { const x = JSON.parse(m.data); if (x.id && pend.has(x.id)) { const { res, rej } = pend.get(x.id); pend.delete(x.id); x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result); } };
const send = (m, p = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, { res, rej }); ws.send(JSON.stringify({ id, method: m, params: p })); setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout')); } }, 20000); });
const ev = async (e) => { const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 300) }; return r.result && r.result.value; };
await send('Runtime.enable');
for (let i = 0; i < 40; i++) { if (await ev('typeof window.gameState==="object"')) break; await sleep(250); }

const setup = `(function(){
  document.body.className = 'layout-ingame layout-compact';
  var gs = document.getElementById('game-screen');
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  gs.classList.add('active');
  gameState.ships = [{positions:[{x:0,y:0}],hits:[]}];
  gameState.opponentShips = []; gameState.opponentAttacks = []; gameState.revealedCells = [];
  if (typeof initGameBoards === 'function') initGameBoards();
  gameState.hand = [{name:'克苏鲁之眼',speed:2,type:'普通',description:'看牌'}];
  var ms = document.getElementById('magic-system'); if (ms) ms.classList.remove('hand-empty');
  if (typeof updateHandUI === 'function') updateHandUI();
  return 1;
})()`;

for (const [w, h, tag] of [[320, 568, '320x568'], [336, 664, '336x664'], [390, 844, '390x844'], [430, 932, '430x932'], [664, 336, '664x336 横屏']]) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: true });
  await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  await sleep(700);
  await ev(setup);
  await sleep(600);
  const r = await ev(`(function(){
    var stage = document.querySelector('.boards-container');
    var gs = document.getElementById('game-screen');
    var board = document.querySelector('#game-player-board');
    var cell = board ? board.querySelector('.cell') : null;
    var vis = [];
    document.querySelectorAll('.boards-container > .board-wrapper').forEach(function(x, i){
      var q = x.getBoundingClientRect();
      var cs = getComputedStyle(x);
      vis.push({ i: i, display: cs.display, h: Math.round(q.height), w: Math.round(q.width) });
    });
    return {
      stageW: stage ? Math.round(stage.clientWidth) : null,
      stageH: stage ? Math.round(stage.clientHeight) : null,
      stageMode: stage ? stage.dataset.mode : null,
      screenBoards: gs.dataset.boards || null,
      boardSize: Math.round((board||{getBoundingClientRect:function(){return {width:0}}}).getBoundingClientRect().width),
      cellW: cell ? +cell.getBoundingClientRect().width.toFixed(1) : null,
      wrappers: vis,
      usedH: Math.round((stage ? stage.getBoundingClientRect().height : 0)),
      viewportH: window.innerHeight,
      overflowY: document.documentElement.scrollHeight - window.innerHeight,
      bodyCls: document.body.className,
    };
  })()`);
  console.log(tag + ': ' + JSON.stringify(r));
}
browser.kill();
process.exit(0);
