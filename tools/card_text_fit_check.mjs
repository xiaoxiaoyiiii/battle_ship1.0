#!/usr/bin/env node
/* Phase 2 卡内文字盒度量：照 IMPLEMENTATION_PLAN §4 风险表 —— 卡组件定尺寸后
   必须用脚本量一遍「说明框是否切字 / 名牌是否溢出 / 三区总和是否超过卡高」，不能靠眼看。
   ⚠️ 这里在 §4 的原始口径上做了一处**有意的重定**（照 §4 风险表第二行「每改一条断言，
      在 docs/ 写下为什么旧口径不再适用」）：
        旧口径：说明框 scrollHeight ≤ clientHeight（一律不许截断）
        新口径：卡名**不许截断**（真缺陷）；说明框**允许按设计的行截断**
                （-webkit-line-clamp + overflow:hidden + 省略号）——
                理由：卡面 86×118 物理上放不下完整中文描述（实测最长描述溢出 173px），
                完整文本由二级预览的右侧说明窗与移动端大卡面抽屉承载（MTG Arena 同做法）。
                若说明框既没截断也没容纳（overflow 可见 → 被卡框切一半），仍判 FAIL。
        → 见 docs/CARD_TEXT_FIT_2026_09_24.md */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5055/');
const PORT = 9462;
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过'); process.exit(0); }
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--window-size=1600,1000', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/card_text_fit_profile', APP], { stdio: 'ignore' });
await sleep(3500);
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list[0];
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0; const pend = new Map();
ws.onmessage = (m) => { const x = JSON.parse(m.data); if (x.id && pend.has(x.id)) { const { res, rej } = pend.get(x.id); pend.delete(x.id); x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result); } };
const send = (m, p = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, { res, rej }); ws.send(JSON.stringify({ id, method: m, params: p })); setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout')); } }, 20000); });
const ev = async (e) => { const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300)); return r.result && r.result.value; };
await send('Runtime.enable');
for (let i = 0; i < 40; i++) { if (await ev('typeof window.gameState==="object" && !!gameState.socket')) break; await sleep(250); }

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// ⚠️ 用**真实卡数据**（static/magic_card.json 的全部唯一卡名），不用编造的长名字。
//    理由：卡名长度是数据事实 —— 编一个数据里不存在的 7 字名去断言，等于测一个
//    到不了的状态（本项目「实测复现」原则）。同时把「最长的真实描述」一并放进手牌，
//    因为说明框的截断行为只有最坏输入才能压出来。
const here = path.dirname(fileURLToPath(import.meta.url));
const raw = JSON.parse(fs.readFileSync(path.join(here, '..', 'static', 'magic_card.json'), 'utf-8'));
const all = Array.isArray(raw) ? raw : (raw.cards || []);
const byName = new Map();
for (const c of all) if (c && c.name && !byName.has(c.name)) byName.set(c.name, c);
const unique = [...byName.values()];
const sortedNames = [...unique].sort((a, b) => b.name.length - a.name.length);
// 手牌上限 8：取「最长的 4 个卡名」+「描述最长的 4 张」做最坏情况
const longestNames = sortedNames.slice(0, 4);
const longestDescs = [...unique].sort((a, b) => (b.description || '').length - (a.description || '').length).slice(0, 4);
const CARDS = [...longestNames, ...longestDescs]
  .filter((c, i, arr) => arr.findIndex((x) => x.name === c.name) === i)
  .slice(0, 8);
console.log('  真实卡数据: ' + unique.length + ' 张唯一卡；'
  + '本档测试 ' + CARDS.length + ' 张（最长卡名 ' + longestNames[0].name
  + ' / 最长描述 ' + (longestDescs[0].description || '').length + ' 字）');

// 在真实对局屏上渲染（要在 layout-ingame 下量，而不是首页）。
// 直接强制屏幕/布局类：不依赖 AI 房能不能开起来（本工具只量卡内文字盒，不测流程）。
async function setupGame() {
  return await ev(`(function(){
    var gs = document.getElementById('game-screen');
    if (gs) { document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); }); gs.classList.add('active'); }
    document.body.classList.add('layout-ingame');
    var ms = document.getElementById('magic-system');
    if (ms) ms.classList.remove('hand-empty');
    return { game: !!gs, cls: document.body.className };
  })()`);
}
const setupInfo = await setupGame();
console.log('  强制对局屏: ' + JSON.stringify(setupInfo));

const measure = async (tag) => {
  const r = await ev(`(function(){
    var cards = ${JSON.stringify(CARDS)};
    gameState.hand = cards;
    if (typeof updateHandUI === 'function') updateHandUI();
    var out = [];
    document.querySelectorAll('#magic-hand .magic-card').forEach(function(c, i){
      var namepl = c.querySelector('.card-nameplate');
      var name = c.querySelector('.card-name');
      var desc = c.querySelector('.card-desc');
      var typebar = c.querySelector('.card-typebar');
      var sp = c.querySelector('.card-speed');
      var ty = c.querySelector('.card-type');
      var ch = c.clientHeight;
      var sum = (namepl?namepl.offsetHeight:0) + (desc?desc.offsetHeight:0) + (typebar?typebar.offsetHeight:0);
      out.push({
        i: i, cardH: ch, zones: sum, fits: sum <= ch + 1,
        descOverflow: desc ? (desc.scrollHeight - desc.clientHeight) : null,
        descDisplayed: desc ? getComputedStyle(desc).display : null,
        descClamp: desc ? getComputedStyle(desc).webkitLineClamp : null,
        descOverflowStyle: desc ? getComputedStyle(desc).overflow : null,
        nameOverflow: name ? (name.scrollHeight - name.clientHeight) : null,
        nameText: name ? name.textContent : null,
        speedText: sp ? sp.textContent : null, typeText: ty ? ty.textContent : null,
        cardW: c.clientWidth,
        // ① 说明框的高度必须是**整行高**的整数倍（否则文字被拦腰切断，不是干净的截断）
        //    ⚠️ 要用**内容盒**（clientHeight − 上下内边距）：clientHeight 含 padding，
        //       直接去除会把 padding 也算成"半行"（上一版就这么误报过 3 行 = 余 7.8px）
        descLinePx: desc ? parseFloat(getComputedStyle(desc).lineHeight) : null,
        descBoxH: desc ? desc.clientHeight : null,
        descPadY: desc ? (parseFloat(getComputedStyle(desc).paddingTop) + parseFloat(getComputedStyle(desc).paddingBottom)) : null,
        // ② 卡面各处文字都不许被切：既查文字块自身的 scrollWidth，也查**容器**（类型条/名牌）
        //    —— 文字块自己"够宽"但容器装不下时，会被卡片的 overflow:hidden 从右边切掉，
        //    这种切法只有查容器才看得见（实测宽屏的「普通魔法」就是这么被切的）。
        typeClip: [name, sp, ty, namepl, typebar].filter(Boolean).map(function(el){
          return { cls: el.className, over: el.scrollWidth - el.clientWidth, text: (el.textContent||'').slice(0,12) };
        }),
      });
    });
    return out;
  })()`);
  console.log('\n  [' + tag + '] 卡数=' + r.length);
  r.forEach((x, i) => {
    console.log('    #' + i + ' 卡=' + x.cardW + 'x' + x.cardH +
      ' 三区总高=' + x.zones + (x.fits ? ' ✓' : ' ✗超') +
      ' 说明溢出=' + x.descOverflow + ' 名字溢出=' + x.nameOverflow +
      (x.descDisplayed === 'none' ? ' [说明框此档隐藏]' : ' clamp=' + x.descClamp + '/' + x.descOverflowStyle));
  });
  check(r.length === CARDS.length, tag + '：最坏情况测试卡都渲染出来了', { n: r.length });
  check(r.every((x) => x.fits), tag + '：名牌+说明+类型条三区总高不撑破卡框', r.map((x) => x.zones + '/' + x.cardH));
  // 说明框可见的档位：要么完整放下，要么按设计的行截断（clamp + overflow:hidden）；
  // 「既放不下、又没截断」= 被卡框切一半 → FAIL（详见文件头那段重定理由）
  const withDesc = r.filter((x) => x.descDisplayed !== 'none' && x.descOverflow !== null);
  check(withDesc.every((x) => x.descOverflow <= 1
      || (x.descClamp !== 'none' && x.descOverflowStyle === 'hidden')),
    tag + '：说明框放得下 或 按设计截断（clamp+hidden，不是被卡框切一半）',
    withDesc.map((x) => x.descOverflow + '/clamp=' + x.descClamp + '/' + x.descOverflowStyle));
  check(r.every((x) => x.nameOverflow <= 1), tag + '：卡名不裁字', r.map((x) => x.nameOverflow));

  // ③ 说明框按**整行**裁：内容盒高度必须是 line-height 的整数倍。
  //    为什么单看 line-clamp 不够：那条只说明"设了截断"，而盒高由 flex 撑出来时，
  //    浏览器会在盒底**拦腰切断**半行字（实测宽屏就是这样，肉眼才看得出来）。
  //    容差 1px 给亚像素舍入。
  const withBox = r.filter((x) => x.descDisplayed !== 'none' && x.descLinePx && x.descPadY !== null);
  check(withBox.every((x) => {
    const contentH = x.descBoxH - x.descPadY;
    const rem = contentH % x.descLinePx;
    return Math.min(rem, x.descLinePx - rem) <= 1;
  }), tag + '：说明框内容盒高度是整行高的整数倍（文字不被拦腰切断）',
    withBox.map((x) => (x.descBoxH - x.descPadY) + '/' + x.descLinePx + ' 余' + ((x.descBoxH - x.descPadY) % x.descLinePx).toFixed(1)));

  // ④ 类型条 / 卡名：每个文字块的 scrollWidth ≤ clientWidth（最后几个字被切 = 真缺陷）
  const clips = r.flatMap((x) => (x.typeClip || []).filter((t) => t.over > 1));
  check(clips.length === 0, tag + '：卡面各处文字都没被裁（无 scrollWidth > clientWidth）',
    clips.slice(0, 6));
  check(r.every((x) => x.nameText && x.nameText.length > 0 && x.typeText && x.typeText.length > 0),
    tag + '：卡名/类型两处文字都真实渲染出内容', r.map((x) => x.nameText + '|' + x.typeText));
  check(r.every((x) => x.speedText && x.speedText.indexOf('速阶') >= 0), tag + '：速阶文字渲染出内容',
    r.map((x) => x.speedText));
};

await measure('宽屏 1600x1000');
// 切到紧凑档（320x568）再量一遍：加 layout-compact 并重跑自适应判据
await send('Emulation.setDeviceMetricsOverride', { width: 320, height: 568, deviceScaleFactor: 1, mobile: true });
await sleep(600);
await ev(`(function(){
  document.body.classList.add('layout-compact');
  if (typeof applyResponsiveLayout === 'function') applyResponsiveLayout();
  var gs = document.getElementById('game-screen');
  if (gs) gs.classList.add('active');
  var ms = document.getElementById('magic-system');
  if (ms) ms.classList.remove('hand-empty');
  return document.body.className;
})()`);
await sleep(500);
await measure('紧凑 320x568');

console.log('\\n' + (problems.length ? '结果: ' + problems.length + ' 项不通过\\n  - ' + problems.join('\\n  - ') : '结果: 全部通过'));
browser.kill();
process.exit(problems.length ? 1 : 0);
