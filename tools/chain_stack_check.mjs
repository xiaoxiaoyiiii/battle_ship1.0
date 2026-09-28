#!/usr/bin/env node
/* Phase 3 连锁叠牌验证：往 gameState.chain 注入 3 条连锁，调 updateChainUI，
   断言「叠起来的一摞真卡」真的渲染出来（卡数 / 结构 / 谁出的角标 / 叠放错位），并出图。 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const OUT = argOf('--out', '.tmp/chain_stack.png');
const PORT = 9467;
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--window-size=1600,1000',
  '--remote-debugging-port=' + PORT, '--user-data-dir=C:/Windows/Temp/chain_stack_profile', APP], { stdio: 'ignore' });
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

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

const ME = 'me-pid';
const r = await ev(`(function(){
  document.body.className = 'layout-ingame';
  var gs = document.getElementById('game-screen');
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  gs.classList.add('active');
  gameState.playerId = ${JSON.stringify(ME)};
  gameState.hand = [{name:'克苏鲁之眼',speed:2,type:'普通',description:'看牌'}];
  var ms = document.getElementById('magic-system'); if (ms) ms.classList.remove('hand-empty');
  if (typeof updateHandUI === 'function') updateHandUI();
  // 三条连锁：1=对手、2=你、3=对手（结算顺序 LIFO）
  gameState.chain = [
    { card: { name:'百亿补贴', speed:2, type:'普通', description:'每有一艘船死亡就加3攻击次数' }, playerId: 'other-pid', negated:false },
    { card: { name:'冻结', speed:3, type:'普通', description:'冻结一个 3×3 区域' }, playerId: ${JSON.stringify(ME)}, negated:false },
    { card: { name:'失灵！', speed:3, type:'普通', description:'无效化上一张魔法卡' }, playerId: 'other-pid', negated:false },
  ];
  if (typeof updateChainUI === 'function') updateChainUI();
  var stack = document.querySelector('#chain-display .chain-stack');
  var cards = document.querySelectorAll('#chain-display .chain-stack-card');
  var listCards = document.querySelectorAll('#chain-cards-list .chain-stack-card');
  var first = cards[0], second = cards[1];
  return {
    hasStack: !!stack,
    count: cards.length,
    listCount: listCards.length,
    headText: (document.querySelector('#chain-display h3')||{}).textContent,
    names: Array.prototype.map.call(cards, function(c){ return c.querySelector('.card-name').textContent; }),
    hasArt: Array.prototype.every.call(cards, function(c){ return !!c.querySelector('.card-art'); }),
    whoBadges: Array.prototype.map.call(cards, function(c){ var w=c.querySelector('.chain-card-who'); return w ? w.textContent : null; }),
    mineClasses: Array.prototype.map.call(cards, function(c){ return c.classList.contains('chain-mine') ? 'mine' : (c.classList.contains('chain-theirs') ? 'theirs' : '?'); }),
    // 叠放错位：第 2 张的 x 应比第 1 张大、y 比第 1 张小（往右上错开）
    rects: Array.prototype.map.call(cards, function(c){ var q=c.getBoundingClientRect(); return {x:Math.round(q.x),y:Math.round(q.y),w:Math.round(q.width),h:Math.round(q.height)}; }),
    listFlex: listCards.length ? getComputedStyle(document.getElementById('chain-cards-list')).flexDirection : null,
  };
})()`);
console.log(JSON.stringify(r, null, 1));

check(!!r.hasStack, '★ 连锁渲染成「一摞」容器（.chain-stack）', r.hasStack);
check(r.count === 3, '★ 三张连锁都渲染成真卡', r.count);
check(r.hasArt === true, '★ 每张连锁卡都有插画层（与手牌共用真卡组件）', r.hasArt);
check(JSON.stringify(r.names) === JSON.stringify(['百亿补贴', '冻结', '失灵！']), '★ 卡名按结算顺序排列', r.names);
check(JSON.stringify(r.whoBadges) === JSON.stringify(['对手', '你', '对手']), '★ 每张卡标出「谁出的」', r.whoBadges);
check(JSON.stringify(r.mineClasses) === JSON.stringify(['theirs', 'mine', 'theirs']), '★ 我方/对手用不同类名（配色分开）', r.mineClasses);
if (r.rects && r.rects.length >= 2) {
  const overlapping = r.rects[1].x < r.rects[0].x + r.rects[0].w;   // 第 2 张压住第 1 张
  check(overlapping, '★ 卡片互相压住（真的是"叠"而不是并排）', r.rects);
}
check(r.listCount === 3, '★ 10 秒响应窗的卡列表也用同一套真卡', r.listCount);

// 常驻叠牌必须落在手牌条**之内**（条 overflow:hidden，超出去就被裁掉 = 看不见）
const fit = await ev(`(function(){
  var strip = document.getElementById('magic-system');
  var cards = document.querySelectorAll('#chain-display .chain-stack-card');
  if (!strip || !cards.length) return null;
  var sr = strip.getBoundingClientRect();
  var out = 0, rects = [];
  cards.forEach(function(c){
    var q = c.getBoundingClientRect();
    rects.push({x:Math.round(q.x),y:Math.round(q.y),b:Math.round(q.bottom),r:Math.round(q.right)});
    if (q.bottom > sr.bottom + 1 || q.right > sr.right + 1 || q.y < sr.y - 1) out++;
  });
  return { strip: {x:Math.round(sr.x),y:Math.round(sr.y),b:Math.round(sr.bottom),r:Math.round(sr.right)},
           cards: rects, outside: out };
})()`);
check(fit && fit.outside === 0, '★ 常驻叠牌全部落在手牌条内（不被 overflow 裁掉）', fit);

// 常驻叠牌不许被浮窗盖住 —— 尤其右下角的聊天窗。出图时实测过：两者同处右下角，
// 叠牌只露出半张卡，而"看不见谁响应了谁"正是这一期要修的问题本身。
const overlap = await ev(`(function(){
  var cards = document.querySelectorAll('#chain-display .chain-stack-card');
  if (!cards.length) return null;
  var others = ['in-game-chat-container', 'magic-card-preview', 'game-logs']
    .map(function(id){ return document.getElementById(id); }).filter(Boolean);
  function inter(a, b){
    var x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
    var y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
    // 真重叠要求**两个轴都有交集**：只有一轴相交时矩形并不相交
    // （实测链在聊天窗左侧：x 相交 0、y 相交 45 —— 那是"上下相邻"，不是叠住）
    return (x > 0 && y > 0) ? Math.round(x) + 'x' + Math.round(y) : '0x0';
  }
  var c = cards[cards.length-1].getBoundingClientRect();
  var bad = [];
  others.forEach(function(o){
    var cs = getComputedStyle(o);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    var r = o.getBoundingClientRect();
    if (!r.width || !r.height) return;
    var ov = inter(c, r);
    if (ov !== '0x0') bad.push((o.id || o.className) + '=' + ov);
  });
  return { overlaps: bad, cardRight: Math.round(c.right), cardBottom: Math.round(c.bottom) };
})()`);
check(overlap && overlap.overlaps.length === 0,
  '★ 常驻叠牌不被浮窗盖住（聊天窗 / 预览框 / 日志）', overlap);



const shot = await send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync(OUT, Buffer.from(shot.data, 'base64'));
console.log('SHOT ->', OUT);
console.log('\n' + (problems.length ? '✗ ' + problems.length + ' 项未通过：\n   · ' + problems.join('\n   · ') : '✓ 全部通过'));
browser.kill();
process.exit(problems.length ? 1 : 0);
