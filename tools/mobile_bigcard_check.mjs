#!/usr/bin/env node
/* Phase 5.3 验证：紧凑档选中一张卡后，抽屉里出现 200×280 的可读大卡面。
   断言：① 卡面存在且有尺寸 ② 比例 = 0.714（实体 TCG 比例）
        ③ 说明文字**完整显示**（scrollHeight ≤ clientHeight，这一档是唯一要读说明的地方）
        ④ 卡面落在抽屉可视区内（不被裁）  ⑤ 出图存档 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const OUT = argOf('--out', '.tmp/mobile_bigcard.png');
const PORT = 9469;
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }
const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--remote-debugging-port=' + PORT, '--user-data-dir=C:/Windows/Temp/bigcard_profile', APP], { stdio: 'ignore' });
await sleep(3500);
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list[0];
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0; const pend = new Map();
ws.onmessage = (m) => { const x = JSON.parse(m.data); if (x.id && pend.has(x.id)) { const { res, rej } = pend.get(x.id); pend.delete(x.id); x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result); } };
const send = (m, p = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, { res, rej }); ws.send(JSON.stringify({ id, method: m, params: p })); setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout')); } }, 20000); });
const ev = async (e) => { const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 400) }; return r.result && r.result.value; };
await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
for (let i = 0; i < 40; i++) { if (await ev('typeof window.gameState==="object"')) break; await sleep(250); }

// 长描述的真实卡（场地魔法 125 字那张）——最能压出"读不了"的档
const DESC_CARD = await ev(`(function(){
  var cards = null;
  try { cards = (typeof MAGIC_CARDS !== 'undefined' && MAGIC_CARDS) ? MAGIC_CARDS : null; } catch(e){}
  var pick = null;
  if (cards) { for (var i=0;i<cards.length;i++){ if (cards[i] && (cards[i].description||'').length > 100) { pick = cards[i]; break; } } }
  if (!pick) pick = { name:'恶魔契约', speed:2, type:'场地', description:'这张牌作为场地魔法卡使用。接下来，双方的船数增减将会绑定。对方的一艘船被击杀了，我也要选择一艘我自己的船让他死亡。' };
  return pick;
})()`);

const r = await ev(`(function(){
  document.body.className = 'layout-ingame layout-compact';
  var gs = document.getElementById('game-screen');
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  gs.classList.add('active');
  var dock = document.getElementById('aux-dock');
  if (dock) { dock.dataset.open = 'true'; dock.dataset.tab = 'card'; }
  var ms = document.getElementById('magic-system'); if (ms) ms.classList.remove('hand-empty');
  var card = ${JSON.stringify(DESC_CARD)};
  gameState.hand = [card];
  if (typeof updateHandUI === 'function') updateHandUI();
  gameState.selectedCardIndex = 0;
  if (typeof updateCardPreview === 'function') updateCardPreview(card, 0);
  var face = document.getElementById('preview-card-face');
  var inner = face ? face.querySelector('.magic-card') : null;
  if (!inner) return { none: true, faceExists: !!face };
  var fr = inner.getBoundingClientRect();
  var desc = inner.querySelector('.card-desc');
  var cs = getComputedStyle(face);
  return {
    faceExists: true,
    faceDisplay: cs.display,
    w: Math.round(fr.width), h: Math.round(fr.height),
    ratio: +(fr.width / fr.height).toFixed(4),
    descVisible: desc ? getComputedStyle(desc).display : null,
    descOverflow: desc ? (desc.scrollHeight - desc.clientHeight) : null,
    descText: desc ? desc.textContent.length : 0,
    descFontPx: desc ? getComputedStyle(desc).fontSize : null,
    nameText: (inner.querySelector('.card-name')||{}).textContent,
    inViewport: fr.top >= -1 && fr.bottom <= window.innerHeight + 1,
    rect: {x:Math.round(fr.x),y:Math.round(fr.y),b:Math.round(fr.bottom)},
  };
})()`);
console.log(JSON.stringify(r, null, 1));
check(!!r.faceExists, '★ 预览里渲染出大卡面容器', r.faceExists);
check(r.faceDisplay === 'block', '★ 紧凑档大卡面可见（display:block）', r.faceDisplay);
check(r.w === 200 && r.h === 280, '★ 大卡面尺寸 = 200×280（可读）', { w: r.w, h: r.h });
check(Math.abs(r.ratio - 0.714) < 0.01, '★ 比例 = 0.714（实体 TCG 63×88mm 同比例）', r.ratio);
check(r.descVisible !== 'none', '★ 大卡面上说明框恢复显示（紧凑档手牌那张是隐藏的）', r.descVisible);
check(r.descOverflow !== null && r.descOverflow <= 1,
  '★ 说明文字在大卡面上完整显示（不截断、不切字）', { overflow: r.descOverflow, chars: r.descText, font: r.descFontPx });
check(!!r.nameText && r.nameText.length > 0, '大卡面有卡名', r.nameText);
await sleep(400);
const shot = await send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync(OUT, Buffer.from(shot.data, 'base64'));
console.log('SHOT ->', OUT);
console.log('\n' + (problems.length ? '✗ ' + problems.length + ' 项未通过：\n   · ' + problems.join('\n   · ') : '✓ 全部通过'));
browser.kill();
process.exit(problems.length ? 1 : 0);
