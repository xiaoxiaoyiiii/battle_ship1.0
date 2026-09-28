#!/usr/bin/env node
/**
 * Phase 7 门禁：卡面美术的**接线**（出图前也必须绿）。
 *
 * 计划里 Phase 7 依赖出图，但「接线」本身可以先用占位验证：
 *   ① window.CARD_ART_MAP 覆盖卡表里**每一张**唯一卡（漏一张就是漏一张底图）
 *   ② 每条路径形如 cards/<slug>.webp（与提示词文件 spec.outputDir 的约定一致）
 *   ③ 手牌 / 连锁 / 大卡面三处渲染出来的卡，都真的把 --card-art-image 写上了
 *   ④ **出图前不破图**：文件不存在时计算样式里仍是「url + 两层渐变占位」，
 *      即真图只是最上面一层、拿不到就落回占位（不需要存在性探测）
 *   ⑤ 美术层不许承担文字与交互：.card-art 必须 aria-hidden + pointer-events:none
 *      （卡名/速阶/类型/描述仍由 DOM 叠 —— 与提示词文件「美术不生成文字与卡框」一致）
 *
 * 用法：node tools/card_art_wiring_check.mjs --url http://127.0.0.1:5055/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const PORT = 9470;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }

// ---------- 静态检查（不需要浏览器）----------
const rawDeck = JSON.parse(fs.readFileSync(path.join(ROOT, 'static', 'magic_card.json'), 'utf-8'));
const deck = Array.isArray(rawDeck) ? rawDeck : (rawDeck.cards || []);
const uniqueNames = [...new Set(deck.map((c) => c.name))].filter(Boolean);
const mapSrc = fs.readFileSync(path.join(ROOT, 'static', 'card_art_map.js'), 'utf-8');
const mapMatch = mapSrc.match(/window\.CARD_ART_MAP\s*=\s*(\{[\s\S]*\});/);
check(!!mapMatch, '（前提）static/card_art_map.js 里有 CARD_ART_MAP');
const artMap = mapMatch ? JSON.parse(mapMatch[1]) : {};
const missing = uniqueNames.filter((n) => !artMap[n]);
check(missing.length === 0, '① 映射覆盖卡表里每一张唯一卡（' + uniqueNames.length + ' 张）', { missing });
const badPath = Object.entries(artMap).filter(([, p]) => !/^cards\/[a-z0-9-]+\.webp$/.test(p));
check(badPath.length === 0, '② 每条路径形如 cards/<slug>.webp（与提示词 spec 的约定一致）', badPath.slice(0, 5));
const slugs = Object.values(artMap);
check(new Set(slugs).size === slugs.length, '②b slug 两两不同（不会两张卡共用一张图）',
  slugs.length - new Set(slugs).size);

// ---------- 浏览器检查 ----------
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--remote-debugging-port=' + PORT, '--user-data-dir=C:/Windows/Temp/card_art_profile', APP], { stdio: 'ignore' });
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

const r = await ev(`(function(){
  var hasMap = !!(window.CARD_ART_MAP && Object.keys(window.CARD_ART_MAP).length);
  document.body.className = 'layout-ingame layout-compact';
  var gs = document.getElementById('game-screen');
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  gs.classList.add('active');
  var dock = document.getElementById('aux-dock');
  if (dock) { dock.dataset.open = 'true'; dock.dataset.tab = 'card'; }
  var card = { name:'仁王之盾', speed:1, type:'普通', description:'选择自己的至多3艘船并使他们进入盾牌状态。' };
  gameState.playerId = 'me';
  gameState.hand = [card];
  var ms = document.getElementById('magic-system'); if (ms) ms.classList.remove('hand-empty');
  if (typeof updateHandUI === 'function') updateHandUI();
  gameState.chain = [{ card: card, playerId: 'other' }];
  if (typeof updateChainUI === 'function') updateChainUI();
  if (typeof updateCardPreview === 'function') updateCardPreview(card, 0);

  function probe(sel){
    var el = document.querySelector(sel);
    if (!el) return null;
    var art = el.querySelector('.card-art') || el;
    var cs = getComputedStyle(art);
    return {
      varSet: art.style.getPropertyValue('--card-art-image').trim(),
      bgImage: cs.backgroundImage,
      layers: (cs.backgroundImage.match(/url\\(|gradient\\(/g) || []).length,
      hasUrl: /url\\(/.test(cs.backgroundImage),
      hasGradient: /gradient\\(/.test(cs.backgroundImage),
      ariaHidden: art.getAttribute('aria-hidden'),
      pointerEvents: cs.pointerEvents,
      bgSize: cs.backgroundSize,
    };
  }
  return {
    hasMap: hasMap, mapCount: hasMap ? Object.keys(window.CARD_ART_MAP).length : 0,
    hand: probe('#magic-hand .magic-card'),
    chain: probe('#chain-display .chain-stack-card'),
    face: probe('#preview-card-face .magic-card'),
    faceExists: !!document.querySelector('#preview-card-face .magic-card'),
  };
})()`);
console.log(JSON.stringify(r, null, 1));

check(r.hasMap === true, '（前提）页面加载了 window.CARD_ART_MAP', { count: r.mapCount });
check(r.mapCount === uniqueNames.length,
  '①b 页面里的映射条目数与卡表唯一卡一致（脚本与页面同步）',
  { page: r.mapCount, deck: uniqueNames.length });

for (const [key, label] of [['hand', '③ 手牌'], ['chain', '③ 连锁叠牌'], ['face', '③ 大卡面']]) {
  const p = r[key];
  if (key === 'face' && !r.faceExists) { check(false, label + '：卡面元素存在', p); continue; }
  check(!!p && /url\("\/static\/cards\//.test(p.varSet), label + '：写上了 --card-art-image（指向 static/cards/）', p && p.varSet);
  check(!!p && p.hasUrl === true, label + '：真图层已进入 background-image', p && p.layers);
  check(!!p && p.hasGradient === true,
    '④ 出图前不破图：渐变占位仍在（真图只是最上面一层）', p && p.bgImage);
  check(!!p && p.ariaHidden === 'true' && p.pointerEvents === 'none',
    '⑤ 美术层不承担文字与交互（aria-hidden + pointer-events:none）',
    p && { ariaHidden: p.ariaHidden, pointerEvents: p.pointerEvents });
  check(!!p && /cover/.test(p.bgSize), label + '：真图按 cover 铺满卡面', p && p.bgSize);
}

console.log('\n' + (problems.length ? '✗ ' + problems.length + ' 项未通过：\n   · ' + problems.join('\n   · ') : '✓ 全部通过'));
browser.kill();
process.exit(problems.length ? 1 : 0);
