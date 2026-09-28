#!/usr/bin/env node
/* 宽屏对局屏几何探针：量 HUD / 棋盘区 / 两块棋盘 / 手牌条的矩形，
   用来定位 §10.3「第二块棋盘被贴底手牌压住」的精确预算。 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const PORT = 9466;
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--window-size=1600,1000',
  '--remote-debugging-port=' + PORT, '--user-data-dir=C:/Windows/Temp/wide_geom_profile', APP], { stdio: 'ignore' });
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

// 强制进入宽屏对局布局 + 摆两块棋盘 + 非空手牌（都不依赖 AI 房）
const setup = `(function(){
  document.body.className = 'layout-ingame';
  var gs = document.getElementById('game-screen');
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  gs.classList.add('active');
  gameState.ships = [{positions:[{x:0,y:0}],hits:[]}];
  gameState.opponentShips = [];
  gameState.opponentAttacks = [];
  gameState.revealedCells = [];
  if (typeof initGameBoards === 'function') initGameBoards();
  gameState.hand = [{name:'克苏鲁之眼',speed:2,type:'普通',description:'看牌'},{name:'八方来财',speed:2,type:'普通',description:'抽两张'}];
  var ms = document.getElementById('magic-system'); if (ms) ms.classList.remove('hand-empty');
  if (typeof updateHandUI === 'function') updateHandUI();
  return document.body.className;
})()`;
await ev(setup);
await sleep(500);

for (const [w, h] of [[1600, 1000], [1440, 900], [1366, 768], [1280, 800], [1280, 720]]) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await sleep(500);
  await ev(setup);
  await sleep(350);
  const g = await ev(`(function(){
    function R(el){ if(!el) return null; var r=el.getBoundingClientRect(); return {y:Math.round(r.y), bottom:Math.round(r.bottom), h:Math.round(r.height), x:Math.round(r.x), w:Math.round(r.width)}; }
    var bs = Array.prototype.map.call(document.querySelectorAll('.boards-container > .board-wrapper'), function(w){ return R(w); });
    var boards = Array.prototype.map.call(document.querySelectorAll('.boards-container .board'), function(b){ return R(b); });
    var hand = R(document.getElementById('magic-system'));
    // 手牌里第一张卡：中心点到底命中了谁（点不到时看是哪个元素盖住了）
    var cardInfo = null;
    var c0 = document.querySelector('#magic-hand .magic-card');
    if (c0) {
      var cr = c0.getBoundingClientRect();
      var cx = Math.round(cr.x + cr.width/2), cy = Math.round(cr.y + cr.height/2);
      var hit = (cx>=0&&cy>=0&&cx<window.innerWidth&&cy<window.innerHeight) ? document.elementFromPoint(cx,cy) : null;
      cardInfo = { rect: R(c0), cx: cx, cy: cy,
        hit: hit ? (hit.id || hit.className || hit.tagName) : null,
        clickable: !!(hit && (hit===c0 || c0.contains(hit))) };
    }
    var brands = Array.prototype.map.call(document.querySelectorAll('.boards-container .board'), function(b){
      var r = b.getBoundingClientRect();
      // 逐格遮挡：格中心点 elementFromPoint 是否落在手牌条内
      var occ = 0, total = 0;
      b.querySelectorAll('.cell').forEach(function(c){
        var cr = c.getBoundingClientRect(); total++;
        var cx = Math.round(cr.x + cr.width/2), cy = Math.round(cr.y + cr.height/2);
        if (cy < 0 || cy > window.innerHeight || cx < 0 || cx > window.innerWidth) { occ++; return; }
        var hit = document.elementFromPoint(cx, cy);
        if (!hit || !(hit === c || c.contains(hit))) occ++;
      });
      return { id: b.id, occluded: occ, cells: total };
    });
    return {
      vh: window.innerHeight,
      content: R(document.querySelector('.game-content')),
      hud: R(document.querySelector('.game-info')),
      boardsContainer: R(document.querySelector('.boards-container')),
      wrappers: bs, boards: boards, hand: hand, card0: cardInfo, occlusion: brands,
      log: R(document.querySelector('.log-container')),
      preview: R(document.getElementById('magic-card-preview')),
      boardVar: getComputedStyle(document.documentElement).getPropertyValue('--board-size'),
    };
  })()`);
  console.log(`--- ${w}x${h} ---`);
  console.log(JSON.stringify(g));
}
browser.kill();
process.exit(0);
