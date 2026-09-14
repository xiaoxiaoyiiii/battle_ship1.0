#!/usr/bin/env node
/**
 * 「生效中效果」角标的浏览器检查。
 *
 * 覆盖作者要的三件事：
 *   1. 角标挂在【各自头像下方】（我的在我这边、对方的在对方那边），不是中间一条；
 *   2. 桌面【鼠标移上去】、手机【点击】都能展开具体效果阐释框（卡面原文 + 失效时机）；
 *   3. 【双方都可见】：对方挂着五险一金时，我这边也要看到那个角标。
 *
 * 用法：node tools/effect_badge_check.mjs --url http://127.0.0.1:5000/ [--shots 目录]
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOTS = argOf('--shots', '');
const PORT = 9411;
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
  '--user-data-dir=C:/Windows/Temp/eff_badge', '--window-size=1280,900', APP], { stdio: 'ignore' });
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

// 进对局界面并绑好事件
// ⚠️ switchScreen(screen) 收的是【元素】不是字符串：传 'game-screen' 会在
// classList 上抛异常被静默吞掉，页面还停在开始界面 —— 于是角标全部
// getBoundingClientRect() = 0，后面所有"没有重叠/没出屏"的断言都会假通过。
await ev(`(function(){
  if (typeof switchScreen === 'function' && typeof gameScreen !== 'undefined' && gameScreen) {
    switchScreen(gameScreen);
  } else {
    document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
    var el = document.getElementById('game-screen');
    if (el) el.classList.add('active');
  }
  if (typeof bindEffectIndicators === 'function') bindEffectIndicators();
  gameState.playerId = 'me';
  return true;
})()`);
await sleep(300);
const screenActive = await ev(`(function(){
  var el = document.getElementById('game-screen');
  return el ? el.classList.contains('active') : 'missing';
})()`);
check(screenActive === true, '（前提）已进入对局界面 #game-screen.active', screenActive);

// 从页面自身的 socket 回调喂一份和真实服务端同形状的数据
const fire = async (payload) => ev(`(function(){
  var s = gameState.socket;
  var cbs = s && s._callbacks && s._callbacks['$active_effects'];
  if (!cbs || !cbs.length) return 'no-listener';
  cbs.forEach(function(cb){ cb(${JSON.stringify(payload)}); });
  return 'ok';
})()`);

const PAYLOAD = {
  self: [{ name: '百亿补贴', description: '每次自己或对方有战舰被击沉时，自己本回合攻击次数+1。', expires: '本回合结束时失效' }],
  opponent: [{ name: '五险一金', description: '这一回合自己的攻击次数第一次用尽时，若自己未曾对对方造成一点伤害，则攻击次数再加3。', expires: '本回合攻击次数第一次归零时触发一次，触发后失效' }],
};

const fired = await fire(PAYLOAD);
check(fired === 'ok', '页面注册了 active_effects 监听', fired);
await sleep(400);

// ---- 1. 角标挂在各自【角落头像】下方 ----
// 注意：对局中可见的头像是左上/右上两个固定定位的角落头像，
// <img> 已被脚本从 .player-info 搬走，所以角标必须在这两个容器里。
await ev(`(function(){
  // 角落头像只在有 roomId 时显示。真实触发方式是派发 gameStateUpdate 事件
  // （脚本里 window.addEventListener('gameStateUpdate', controlGameElementsVisibility)），
  // 不要去硬改 style.display —— 那测的就不是真实行为了。
  gameState.roomId = 'r1';
  window.dispatchEvent(new Event('gameStateUpdate'));
  return true;
})()`);
await sleep(300);
const cornerVisible = await ev(`(function(){
  var c = document.getElementById('avatar-corner');
  return c ? getComputedStyle(c).display : 'missing';
})()`);
check(cornerVisible !== 'none' && cornerVisible !== 'missing',
  '（前提）角落头像已显示（模拟对局中）', cornerVisible);
// 角标容器挂在这里，所以这个容器必须有实际尺寸，
// 否则后面的"没重叠 / 没出屏"断言全是 0×0 的假通过。
const cornerSized = await ev(`(function(){
  var el = document.getElementById('avatar-corner');
  if (!el) return 'missing';
  var r = el.getBoundingClientRect();
  return { w: Math.round(r.width), h: Math.round(r.height) };
})()`);
check(cornerSized !== 'missing' && cornerSized.w > 0 && cornerSized.h > 0,
  '（前提）角落头像有实际尺寸（否则后面的重叠断言都是假通过）', cornerSized);
// 容器是按需建到角落头像里的，再喂一次确保已对位
await fire(PAYLOAD);
await sleep(300);

const layout = await ev(`(function(){
  var myCorner = document.getElementById('avatar-corner');
  var oppCorner = document.getElementById('opponent-avatar-corner');
  var myBox = document.getElementById('my-effect-indicators');
  var oppBox = document.getElementById('opponent-effect-indicators');
  var rect = function(el){ if(!el) return null; var r = el.getBoundingClientRect(); return {left:Math.round(r.left), top:Math.round(r.top), w:Math.round(r.width)}; };
  return {
    mine: myBox ? Array.prototype.map.call(myBox.querySelectorAll('.effect-icon'), function(b){ return b.textContent; }) : null,
    theirs: oppBox ? Array.prototype.map.call(oppBox.querySelectorAll('.effect-icon'), function(b){ return b.textContent; }) : null,
    myBoxInCorner: !!(myCorner && myBox && myCorner.contains(myBox)),
    oppBoxInCorner: !!(oppCorner && oppBox && oppCorner.contains(oppBox)),
    myAvatarInCorner: !!(myCorner && myCorner.querySelector('#my-avatar-in-game')),
    oppAvatarInCorner: !!(oppCorner && oppCorner.querySelector('#opponent-avatar-in-game')),
    myBoxTopBelowAvatar: (function(){
      if (!myCorner || !myBox) return null;
      var av = myCorner.querySelector('#my-avatar-in-game');
      if (!av) return null;
      return Math.round(myBox.getBoundingClientRect().top) >= Math.round(av.getBoundingClientRect().top);
    })(),
    myRect: rect(myCorner), oppRect: rect(oppCorner),
    oldCentralBox: !!document.getElementById('effect-indicators'),
  };
})()`);

check(Array.isArray(layout.mine) && layout.mine.length === 1 && layout.mine[0] === '百亿补贴',
  '我的效果渲染出来了', layout.mine);
check(Array.isArray(layout.theirs) && layout.theirs.length === 1 && layout.theirs[0] === '五险一金',
  '★ 对方的效果也渲染出来了（双方可见）', layout.theirs);
check(layout.myBoxInCorner && layout.myAvatarInCorner,
  '★ 我的角标挂在【我的角落头像】那一块里', {
    inCorner: layout.myBoxInCorner, avatarThere: layout.myAvatarInCorner });
check(layout.oppBoxInCorner && layout.oppAvatarInCorner,
  '★ 对方的角标挂在【对手的角落头像】那一块里', {
    inCorner: layout.oppBoxInCorner, avatarThere: layout.oppAvatarInCorner });
check(layout.myBoxTopBelowAvatar !== false, '角标在头像下方（不是盖在头像上）', layout.myBoxTopBelowAvatar);
// 镜像：我在左、对手在右
check(layout.myRect && layout.oppRect && layout.myRect.left < layout.oppRect.left,
  '★ 左右镜像对称（我在左、对手在右）', { mine: layout.myRect, opp: layout.oppRect });
check(layout.oldCentralBox === false, '旧的居中 effect-indicators 已移除', layout.oldCentralBox);
await shot('1-badges-under-avatars');

// ---- 2. 桌面：鼠标移上去展开 ----
const hover = await ev(`(function(){
  var btn = document.querySelector('#opponent-effect-indicators .effect-icon');
  if (!btn) return 'no-badge';
  btn.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
  return 'ok';
})()`);
check(hover === 'ok', '（前提）找到对方角标', hover);
await sleep(350);
const popOpp = await ev(`(function(){
  var p = document.querySelector('.effect-popover');
  if (!p || p.classList.contains('hidden')) return null;
  return {
    who: (p.querySelector('.effect-popover-who') || {}).textContent,
    name: (p.querySelector('.effect-popover-name') || {}).textContent,
    body: (p.querySelector('.effect-popover-body') || {}).textContent,
    expiry: (p.querySelector('.effect-popover-expiry') || {}).textContent,
  };
})()`);
check(!!popOpp, '★ 鼠标移上去弹出了阐释框', popOpp);
if (popOpp) {
  check(popOpp.who === '对方', '浮层标明这是「对方」的效果', popOpp.who);
  check(popOpp.name === '五险一金', '浮层显示效果名', popOpp.name);
  check(/攻击次数第一次用尽/.test(popOpp.body || ''),
    '★ 浮层显示卡面原文（不是只有名字）', popOpp.body);
  check(/触发/.test(popOpp.expiry || ''), '★ 浮层显示失效时机', popOpp.expiry);
}
await shot('2-hover-popover');

// 移开 → 收起
await ev(`(function(){
  var btn = document.querySelector('#opponent-effect-indicators .effect-icon');
  btn.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }));
  return true;
})()`);
await sleep(400);
const hidden = await ev(`(function(){
  var p = document.querySelector('.effect-popover');
  return !p || p.classList.contains('hidden');
})()`);
check(hidden === true, '鼠标移开后浮层收起', hidden);

// ---- 3. 手机端：点一下展开，再点一下收起 ----
const clickOpen = await ev(`(function(){
  var btn = document.querySelector('#my-effect-indicators .effect-icon');
  if (!btn) return 'no-badge';
  btn.click();
  return 'ok';
})()`);
check(clickOpen === 'ok', '（前提）找到我的角标', clickOpen);
await sleep(300);
const popMine = await ev(`(function(){
  var p = document.querySelector('.effect-popover');
  if (!p || p.classList.contains('hidden')) return null;
  return {
    who: (p.querySelector('.effect-popover-who') || {}).textContent,
    name: (p.querySelector('.effect-popover-name') || {}).textContent,
    body: (p.querySelector('.effect-popover-body') || {}).textContent,
    expiry: (p.querySelector('.effect-popover-expiry') || {}).textContent,
  };
})()`);
check(!!popMine, '★ 点击（手机端）也能展开', popMine);
if (popMine) {
  check(popMine.who === '你', '浮层标明这是「你」的效果', popMine.who);
  check(/击沉/.test(popMine.body || ''), '浮层显示我这条效果的卡面原文', popMine.body);
  check(/本回合/.test(popMine.expiry || ''), '浮层显示失效时机', popMine.expiry);
}
const inViewport = await ev(`(function(){
  var p = document.querySelector('.effect-popover');
  if (!p) return null;
  var r = p.getBoundingClientRect();
  return { left: Math.round(r.left), top: Math.round(r.top), right: Math.round(r.right), bottom: Math.round(r.bottom),
           vw: window.innerWidth, vh: window.innerHeight };
})()`);
check(inViewport && inViewport.left >= 0 && inViewport.top >= 0
  && inViewport.right <= inViewport.vw && inViewport.bottom <= inViewport.vh,
  '浮层没有超出视口', inViewport);
await shot('3-click-popover');

// 再点同一个 → 收起
await ev(`(function(){
  var btn = document.querySelector('#my-effect-indicators .effect-icon');
  if (btn) btn.click();
  return true;
})()`);
await sleep(250);
check(await ev(`(function(){ var p=document.querySelector('.effect-popover'); return !p || p.classList.contains('hidden'); })()`) === true,
  '再点一下收起（手机端同一个按钮切换）');

// 点别处 → 收起
await ev(`(function(){ document.querySelector('#my-effect-indicators .effect-icon').click(); return true; })()`);
await sleep(250);
await ev(`(function(){
  var el = document.querySelector('#turn-indicator') || document.body;
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  return true;
})()`);
await sleep(250);
check(await ev(`(function(){ var p=document.querySelector('.effect-popover'); return !p || p.classList.contains('hidden'); })()`) === true,
  '点空白处收起');

// ---- 4. 没有效果时整块隐藏 ----
await fire({ self: [], opponent: [] });
await sleep(300);
const emptyState = await ev(`(function(){
  var m = document.getElementById('my-effect-indicators');
  var o = document.getElementById('opponent-effect-indicators');
  return {
    mineCount: m ? m.querySelectorAll('.effect-icon').length : -1,
    theirsCount: o ? o.querySelectorAll('.effect-icon').length : -1,
    mineDisplay: m ? getComputedStyle(m).display : null,
    theirsDisplay: o ? getComputedStyle(o).display : null,
  };
})()`);
check(emptyState.mineCount === 0 && emptyState.theirsCount === 0, '效果清空后角标都消失', emptyState);
check(emptyState.mineDisplay === 'none' && emptyState.theirsDisplay === 'none',
  '空的时候整块不占位置（:empty 隐藏）', emptyState);

// ---- 5. 兼容旧的纯字符串数组（升级瞬间不白屏） ----
await fire(['百亿补贴']);
await sleep(300);
const legacy = await ev(`(function(){
  var m = document.getElementById('my-effect-indicators');
  return Array.prototype.map.call(m.querySelectorAll('.effect-icon'), function(b){ return b.textContent; });
})()`);
check(legacy.length === 1 && legacy[0] === '百亿补贴', '旧形状（字符串数组）也不会白屏', legacy);

// ---- 6. 手机视口：角标不能互相压 / 不能出屏 / 不能盖住棋盘 ----
// 角标挂在固定定位的角落头像里，窄屏上最容易出问题，必须专门测。
console.log('--- 场景 6：手机窄屏（320×568 / 390×844）---');
for (const [w, h] of [[320, 568], [390, 844]]) {
  await send('Emulation.setDeviceMetricsOverride',
    { width: w, height: h, deviceScaleFactor: 1, mobile: true });
  await sleep(400);
  await fire(PAYLOAD);
  await sleep(400);

  const m = await ev(`(function(){
    var myCorner = document.getElementById('avatar-corner');
    var oppCorner = document.getElementById('opponent-avatar-corner');
    var myBox = document.getElementById('my-effect-indicators');
    var oppBox = document.getElementById('opponent-effect-indicators');
    var r = function(el){ if(!el) return null; var b = el.getBoundingClientRect();
      return {left:Math.round(b.left), right:Math.round(b.right), top:Math.round(b.top), bottom:Math.round(b.bottom)}; };
    var a = r(myCorner), b2 = r(oppCorner);
    return {
      vw: window.innerWidth, vh: window.innerHeight,
      my: r(myBox), opp: r(oppBox),
      myCorner: a, oppCorner: b2,
      cornersOverlap: !!(a && b2 && a.right > b2.left && a.bottom > b2.top),
      boardsOverlap: (function(){
        var vps = [[myBox, '#game-player-board'], [myBox, '#opponent-board'],
                   [oppBox, '#game-player-board'], [oppBox, '#opponent-board']];
        var bad = [];
        vps.forEach(function(pair){
          var box = pair[0], bd = document.querySelector(pair[1]);
          if (!box || !bd) return;
          var x = box.getBoundingClientRect(), y = bd.getBoundingClientRect();
          if (x.width > 0 && y.width > 0 &&
              x.right > y.left && x.left < y.right && x.bottom > y.top && x.top < y.bottom) {
            bad.push(pair[1]);
          }
        });
        return bad;
      })(),
      badgeCount: (myBox ? myBox.querySelectorAll('.effect-icon').length : 0)
        + (oppBox ? oppBox.querySelectorAll('.effect-icon').length : 0),
    };
  })()`);

  const tag = `${w}x${h}`;
  // 前提：这一视口下角标真的有尺寸，否则下面的重叠/出屏断言全是假通过
  const sized = m.my && m.opp && (m.my.right - m.my.left) > 0 && (m.opp.right - m.opp.left) > 0;
  check(sized, `[${tag}] （前提）角标有实际尺寸`, { my: m.my, opp: m.opp });
  check(m.badgeCount === 2, `[${tag}] 两侧角标都渲染出来了`, m.badgeCount);
  check(!sized || (m.my.left >= 0 && m.my.right <= m.vw && m.opp.left >= 0 && m.opp.right <= m.vw),
    `[${tag}] 角标没有横向出屏`, { my: m.my, opp: m.opp, vw: m.vw });
  check(!sized || (m.my.bottom <= m.vh && m.opp.bottom <= m.vh),
    `[${tag}] 角标没有纵向出屏`, { my: m.my, opp: m.opp, vh: m.vh });
  check(!sized || m.cornersOverlap === false,
    `[${tag}] ★ 左右两个角落头像没有互相压住`, { my: m.myCorner, opp: m.oppCorner });
  check(!sized || m.boardsOverlap.length === 0,
    `[${tag}] ★ 角标没有盖住棋盘`, m.boardsOverlap);
  if (SHOTS) await shot(`mobile-${tag}`);

  // 手机上点一下也能展开（触屏没有 hover）
  const tap = await ev(`(function(){
    var b = document.querySelector('#opponent-effect-indicators .effect-icon');
    if (!b) return 'no-badge';
    b.click();
    return 'ok';
  })()`);
  await sleep(300);
  const popMobile = await ev(`(function(){
    var p = document.querySelector('.effect-popover');
    if (!p || p.classList.contains('hidden')) return null;
    var r = p.getBoundingClientRect();
    return { name: (p.querySelector('.effect-popover-name')||{}).textContent,
             left: Math.round(r.left), right: Math.round(r.right), vw: window.innerWidth };
  })()`);
  check(!!popMobile, `[${tag}] 手机上点角标能展开浮层`, tap);
  check(popMobile && popMobile.left >= 0 && popMobile.right <= popMobile.vw + 1,
    `[${tag}] 手机上的浮层没有出屏`, popMobile);
  if (SHOTS && popMobile) await shot(`mobile-popover-${tag}`);
  await ev(`(function(){ document.dispatchEvent(new MouseEvent('click', {bubbles:true})); return true; })()`);
  await sleep(200);
}
await send('Emulation.clearDeviceMetricsOverride');
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
