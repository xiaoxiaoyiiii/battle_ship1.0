#!/usr/bin/env node
/* Phase 6 图鉴：条目从"一行文字"升成**真卡**后的门禁（原有 card_compendium_check.mjs 只管
   数据/筛选，不管长什么样 —— 这条补上"是不是真卡 + 说明能不能读 + 底图有没有接"）。
   用法：node tools/codex_realcard_check.mjs --url http://127.0.0.1:5055/ [--shot out.png] */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const SHOT = argOf('--shot', '');
const PORT = 9472;
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }
const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--window-size=1600,1000',
  '--remote-debugging-port=' + PORT, '--user-data-dir=C:/Windows/Temp/codex_card_profile', APP], { stdio: 'ignore' });
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
for (let i = 0; i < 40; i++) { if (await ev('typeof window.gameState==="object"')) break; await sleep(250); }

await ev('renderHomeHotCards({ usage: { "失灵！": 3, "轰炸": 2 } })');
await sleep(700);
const homeFaces = await ev(`(function(){
  var cards = [].slice.call(document.querySelectorAll('#home-hot-cards .hcard'));
  return { count: cards.length, ready: cards.filter(function(c){
    var image = c.querySelector('.ha .card-face-image');
    return image && image.naturalWidth > 0 && image.parentElement.classList.contains('has-card-face');
  }).length, names: cards.map(function(c){ return c.querySelector('.hn')?.textContent; }) };
})()`);
check(homeFaces.count === 5 && homeFaces.ready === 5, '★ 首页热门卡五张都显示完整卡面缩略图', homeFaces);

await ev(`(function(){
  var btn = document.getElementById('help-btn') || document.querySelector('[id$="help-btn"]');
  if (btn) btn.click();
  var modal = document.getElementById('help-modal');
  if (modal) modal.classList.remove('hidden');
  if (typeof renderCardCompendium === 'function') renderCardCompendium();
})()`);
await sleep(600);
const r = await ev(`(function(){
  var modal = document.getElementById('help-modal');
  var items = [].slice.call(document.querySelectorAll('#help-magic-cards .magic-card-help'));
  if (!items.length) return { none: true };
  var out = [];
  items.slice(0, 6).forEach(function(it){
    var c = it.querySelector('.magic-card');
    if (!c) { out.push({ noCard: true, name: it.getAttribute('data-card-name') }); return; }
    var q = c.getBoundingClientRect();
    var desc = c.querySelector('.card-desc');
    var image = c.querySelector('.card-face-image');
    out.push({
      name: it.getAttribute('data-card-name'),
      hasAttrs: !!(it.getAttribute('data-card-speed') && it.getAttribute('data-card-type') && it.hasAttribute('data-card-uses')),
      w: Math.round(q.width), h: Math.round(q.height),
      ratio: +(q.width / q.height).toFixed(3),
      zones: !!c.querySelector('.card-nameplate') && !!c.querySelector('.card-typebar') && !!desc,
      descClamp: desc ? getComputedStyle(desc).webkitLineClamp : null,
      faceReady: !!(image && image.naturalWidth > 0 && c.classList.contains('has-card-face')),
      faceSrc: image ? new URL(image.src).pathname : null,
    });
  });
  var usesBadge = document.querySelector('#help-magic-cards .compendium-uses');
  return { total: items.length, sample: out,
    usesBadge: usesBadge ? usesBadge.textContent.trim() : null,
    modalVisible: modal ? !modal.classList.contains('hidden') : null };
})()`);
console.log(JSON.stringify(r, null, 1));
// ⚠️ 2026-09-28 重定：原判据写死 `total === 41`（当时的真实卡数）。合并上游后卡表变成
//    50 张 / 去重 48 张（判定魔法卡 3 张 + 普通 4 张），死数字当场红 —— 但它要守的是
//    "图鉴把卡表里的牌一张不少地渲染出来"，所以改成从 static/magic_card.json 现算唯一
//    卡名数，而不是再换一个死数字（下次加卡还会红）。
const CARD_TABLE = JSON.parse(fs.readFileSync(new URL('../static/magic_card.json', import.meta.url), 'utf-8'));
const CARD_LIST = Array.isArray(CARD_TABLE) ? CARD_TABLE : (CARD_TABLE.cards || []);
const EXPECTED = new Set(CARD_LIST.map((c) => c && c.name).filter(Boolean)).size;
check(!r.none && r.total === EXPECTED, '（前提）图鉴渲染张数 = 卡表唯一卡数（' + EXPECTED + ' 张）', r.total);
const s0 = (r.sample || [])[0] || {};
check((r.sample || []).every((x) => x.zones === true), '★ 每个条目都是真卡（名牌/说明/类型条三区齐）',
  (r.sample || []).map((x) => x.zones));
check((r.sample || []).every((x) => x.hasAttrs === true), '★ data-* 四个属性没丢（原工具的取数口子不变）',
  (r.sample || []).map((x) => x.name));
check((r.sample || []).every((x) => Math.abs(x.ratio - 0.715) < 0.02), '★ 卡面比例 ≈ 0.715（实体 TCG 比例）',
  (r.sample || []).map((x) => x.ratio));
check((r.sample || []).every((x) => x.descClamp && x.descClamp !== 'none'), '★ 说明框按多行截断（图鉴要尽量读全 → 9 行）',
  (r.sample || []).map((x) => x.descClamp));
check((r.sample || []).every((x) => x.faceReady && x.faceSrc?.startsWith('/static/card_faces/')),
  '★ 图鉴显示已加载的完整卡面，旧 DOM 文字仍作后备', (r.sample || []).map((x) => x.faceSrc));
await ev(`(function(){
  document.querySelector('#help-magic-cards .magic-card-help[data-card-name="失灵！"]')?.click();
})()`);
await sleep(600);
const detail = await ev(`(function(){
  var card = document.querySelector('#codex-detail .ax-detail-card .magic-card');
  var image = card && card.querySelector('.card-face-image');
  return { ready: !!(card && card.classList.contains('has-card-face') && image && image.naturalWidth > 0),
    rules: !!document.querySelector('#codex-detail .ax-detail-text'),
    image: !!image, naturalWidth: image?.naturalWidth, active: card?.className };
})()`);
check(detail.ready && detail.rules, '★ 图鉴右侧详情显示完整卡面，规则原文仍可读', detail);

// 同一张牌在手牌和弃牌堆也要真正加载；其它界面仍沿用原卡面结构。
await ev(`(function(){
  var card = { name:'失灵！', speed:3, type:'普通', description:'无效化上一张魔法卡。' };
  document.getElementById('help-modal')?.classList.add('hidden');
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  document.getElementById('game-screen')?.classList.add('active');
  document.body.classList.add('layout-ingame');
  gameState.hand = [card];
  gameState.selectedCardIndex = -1;
  updateHandUI();
  document.getElementById('discard-pile-modal')?.classList.remove('hidden');
  displayDiscardPile([card]);
})()`);
await sleep(800);
const surfaces = await ev(`(function(){
  function ready(sel) {
    var el = document.querySelector(sel);
    var img = el && el.querySelector('.card-face-image');
    return !!(el && el.classList.contains('has-card-face') && img && img.naturalWidth > 0);
  }
  return {
    hand: ready('#magic-hand .magic-card'),
    discard: ready('#discard-pile-cards .discard-pile-card'),
    handText: !!document.querySelector('#magic-hand .card-desc'),
    discardText: !!document.querySelector('#discard-pile-cards .discard-pile-card-desc'),
  };
})()`);
check(surfaces.hand && surfaces.discard && surfaces.handText && surfaces.discardText,
  '★ 手牌与弃牌堆加载完整卡面，文字后备结构保留', surfaces);
await ev(`(function(){
  document.getElementById('discard-pile-modal')?.classList.add('hidden');
  updateCardPreview({ name:'失灵！', speed:3, type:'普通', description:'无效化上一张魔法卡。' }, 0);
})()`);
await sleep(400);
const preview = await ev(`(function(){
  var host = document.getElementById('magic-card-preview');
  var face = host.querySelector('.preview-face-card .card-face-image');
  var title = host.querySelector('.preview-header h3');
  var effect = host.querySelector('#preview-description');
  var imageRect = face?.getBoundingClientRect();
  var effectRect = effect?.getBoundingClientRect();
  return { title:title?.textContent, faceReady:!!(face && face.naturalWidth > 0),
    effect:effect?.textContent, imageBeforeEffect:!!(imageRect && effectRect && imageRect.bottom <= effectRect.top),
    titleVisible:getComputedStyle(title).display !== 'none' };
})()`);
check(preview.title === '失灵！' && preview.faceReady && preview.effect.includes('无效化')
  && preview.imageBeforeEffect && preview.titleVisible,
  '★ 待使用卡按卡名、完整卡面缩略图、可读效果三段显示', preview);
await ev(`(function(){
  var card = window.magicCards.find(function(c){ return c.name === '恶魔契约'; });
  updateCardPreview(card, 0);
})()`);
const longPreview = await ev(`(function(){
  var host = document.getElementById('magic-card-preview');
  var chat = document.getElementById('in-game-chat-container');
  return { scrollable:host.scrollHeight > host.clientHeight,
    panelBottom:host.getBoundingClientRect().bottom,
    chatTop:chat.getBoundingClientRect().top,
    effectLength:host.querySelector('#preview-description').textContent.length };
})()`);
check(longPreview.scrollable && longPreview.panelBottom + 4 <= longPreview.chatTop,
  '★ 长效果可滚动阅读，预览框不压住聊天窗', longPreview);
await ev(`(function(){
  document.getElementById('help-modal')?.classList.remove('hidden');
})()`);

// 48 张真卡比原来的一行文字高得多 → 必须确认容器**真的能滚**、且滚到底最后一张可见。
// （只断言"有 overflow:auto"是不够的：本项目踩过"看着有、其实永远不触发"的一类判据。）
const scrollState = await ev(`(function(){
  var grid = document.getElementById('help-magic-cards');
  var host = null, el = grid;
  while (el && el !== document.body) {
    var cs = getComputedStyle(el);
    if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 1) { host = el; break; }
    el = el.parentElement;
  }
  if (!host) return { scrollable: false };
  host.scrollTop = host.scrollHeight;
  var items = document.querySelectorAll('#help-magic-cards .magic-card-help');
  var last = items[items.length - 1].getBoundingClientRect();
  var hr = host.getBoundingClientRect();
  return { scrollable: true, hostId: host.id || host.className,
    lastVisible: last.bottom <= hr.bottom + 2, count: items.length };
})()`);
check(scrollState && scrollState.scrollable === true,
  '★ 真卡超出弹窗高度时容器可滚动（' + r.total + ' 张，不是被裁死）', scrollState);
check(scrollState && scrollState.lastVisible === true,
  '★ 滚到底后最后一张卡完整可见', scrollState);

if (SHOT) {
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
  console.log('SHOT ->', SHOT);
}
console.log('\n' + (problems.length ? '✗ ' + problems.length + ' 项未通过：\n   · ' + problems.join('\n   · ') : '✓ 全部通过'));
browser.kill();
process.exit(problems.length ? 1 : 0);
