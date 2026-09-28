#!/usr/bin/env node
/**
 * 「绝处逢生」两条效果不能互相冒认的前端回归检查（无头 Edge + CDP，喂真实事件）。
 *
 * 背景：绝处逢生在服务端原来是【一个】标记 `last_stand`，兼职两件事：
 *   ① 发动回合内自己的其余魔法卡全部无效（锁卡，该过期）
 *   ② 击杀对方任何一艘船即直接获胜（本意是活到对局结束）
 * 合成了一个标记，第 2 件事就跟着第 1 件在换小回合时被一起清掉了 ——
 * 作者实测「只会在绝处逢生生效的那一个回合有效，到了下一个回合就没有这个效果了」。
 * 修复后拆成两个：`last_stand`（锁卡，本回合结束失效）/ `last_stand_win`（击杀即胜，活到对局结束）。
 *
 * ⚠️ 拆开之后**前端反而多了一个更隐蔽的坑**：服务端下发的角标对象里
 * `name` = 卡名，两条都是「绝处逢生」（浮层要靠它回查卡面原文，所以不能改）；
 * `label` = 显示名，分别是「绝处逢生·锁卡 / 绝处逢生·击杀即胜」；只有 `key` 是标记名。
 * 修 bug 之前 `isLastStandActive()` 是**按卡名匹配**的：
 *     return s === '绝处逢生' || s === 'last_stand' || s.indexOf('last_stand') === 0;
 * 现在「击杀即胜」的角标名也叫「绝处逢生」→ 它会被一直当成「锁卡」→
 * 玩家点魔法卡被**前端本地**拦下、弹出「绝处逢生生效中，本回合你的其余魔法卡全部无效」，
 * 而服务端其实早就放行了。这条回归必须钉死，否则玩家会以为"卡坏了"（零提示、零报错）。
 *
 * 覆盖（对应作者订正后的口径：击杀即胜不能连带把魔法卡继续锁住）：
 *   1. 两条角标同时喂 → 都渲染、文字能区分、都有实际尺寸（否则后面是 0×0 假通过）；
 *   2. 只喂「击杀即胜」（模拟换小回合后锁卡过期）→ 点速阶3 魔法卡【不能】被拦、不能弹拒绝提示；
 *   3. 只喂「锁卡」（模拟发动当回合）→ 点速阶3 魔法卡【必须】被拦并给出「绝处逢生生效中」的理由
 *      —— 这条是**反证**，防止把门禁整个改没了；
 *   4. 浮层（hover/click 角标弹出的框）显示的是**卡面原文**，不是空字符串（验 `name` 没被写花）；
 *   5. 兼容旧的纯字符串数组（如 ['百亿补贴']）不白屏；
 *   6. 旧形状（只有 name/description/expires，没有 key/label）也要能渲染。
 *
 * 用法：node tools/last_stand_win_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
// 端口别和别的工具撞（现有工具占了 9341 / 9411 / 9437 等），这里用 9455。
const PORT = 9455;
// ⚠️ 无头浏览器必须用【独立】profile：和其它工具共用 profile 会互相抢锁，
// 新浏览器静默起不来 → /json/list 拿不到页面，看着像"页面函数没定义"。
const PROFILE = 'C:/Windows/Temp/last_stand_win_profile';
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.error('找不到 Edge/Chrome，跳过绝处逢生（击杀即胜）检查'); process.exit(0); }

// 上一轮残留的无头进程会占着 profile / 调试端口，让这一轮静默起不来（工具的经典假红）。
// ⚠️ 只按【调试端口】精确杀，绝不 taskkill 全部 msedge.exe —— 那会把作者正在用的浏览器一起关掉。
try {
  const out = execSync(`netstat -ano -p TCP | findstr ":${PORT} "`,
    { stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true }).toString();
  const pids = new Set();
  out.split(/\r?\n/).forEach((line) => {
    const m = /\s(\d+)\s*$/.exec(line.trim());
    if (m && m[1] !== '0') pids.add(m[1]);
  });
  pids.forEach((pid) => {
    try { execSync(`taskkill /F /PID ${pid}`, { stdio: 'ignore', windowsHide: true }); } catch (e) {}
  });
} catch (e) { /* 没有残留进程时 findstr 返回非 0，正常 */ }
try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// 只报不判的信息行：用来把「已知的、本次任务范围外的」现象记进输出，不制造假红。
function note(label, detail) {
  console.log('INFO  ' + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
}

// 测量用卡：速阶3、且 needsTargetSelection 里没有它（点下去会直接 emit use_magic_card），
// 这样"有没有被前端拦下"能靠【有没有发出 socket 事件】直接读出来。
const CARD = { name: '测试用速阶三卡', speed: 3, type: '普通' };

// 服务端 _effect_badges 的真实形状（server.py：name=卡名、key=标记名、label=显示名）。
// 两条 last_stand 的 name **故意相同**，这正是这条回归的病灶所在。
const BADGE_LOCK = {
  name: '绝处逢生', key: 'last_stand', label: '绝处逢生·锁卡',
  description: '（占位，真的卡面原文由服务端下发）', expires: '本回合结束时失效',
};
const BADGE_WIN = {
  name: '绝处逢生', key: 'last_stand_win', label: '绝处逢生·击杀即胜',
  description: '（占位，真的卡面原文由服务端下发）', expires: '活到对局结束',
};

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--mute-audio',
  '--remote-debugging-port=' + PORT, '--user-data-dir=' + PROFILE,
  '--window-size=1280,900', APP], { stdio: 'ignore' });

let ws = null;
let page = null;
try {
  await sleep(3000);
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  // ⚠️ 必须优先挑 http 页面：新 profile 首次启动会带一个
  // edge://sync-confirmation-dialog 的 page 目标，连错页面会得到一堆 undefined。
  page = list.find((t) => t.type === 'page' && /^http/.test(t.url || ''))
      || list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || ''));
  if (!page) { console.error('找不到页面目标'); process.exit(1); }
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
} catch (e) {
  console.error('连不上无头浏览器：' + e.message);
  try { browser.kill(); } catch (x) {}
  process.exit(1);
}

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
  setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
});
await send('Runtime.enable');
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
};
async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await fn()) return true; } catch (e) { /* 页面还没就绪，继续等 */ }
    await sleep(200);
  }
  throw new Error('等待超时：' + label);
}

await waitFor(async () => await ev(
  'document.readyState === "complete" && typeof window.gameState === "object"'), 25000, '页面加载');
await waitFor(async () => await ev(
  'typeof canPlayCard === "function" && typeof isLastStandActive === "function"'
  + ' && typeof renderActiveEffects === "function" && typeof updateHandUI === "function"'),
  25000, 'game.js 就绪');

// ===========================================================================
// 0. 进入对局界面 + 换掉 socket + 造一手牌
// ===========================================================================
// ⚠️ switchScreen(screen) 收的是【元素】不是字符串：传 'game-screen' 会在
// classList 上抛异常、被静默吞掉，页面还停在开始界面 —— 于是角标和手牌
// getBoundingClientRect() 全是 0，后面所有断言都会变成 0×0 的假通过。
const setup = await ev(`(function(){
  if (typeof switchScreen === 'function' && typeof gameScreen !== 'undefined' && gameScreen) {
    switchScreen(gameScreen);
  } else {
    document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
    var el = document.getElementById('game-screen');
    if (el) el.classList.add('active');
  }
  // 手牌容器是 game.js 动态建的，页面刚加载时还不存在。
  if (!document.getElementById('magic-hand') && typeof createMagicCardUI === 'function') {
    createMagicCardUI();
  }
  if (typeof bindEffectIndicators === 'function') bindEffectIndicators();

  // 角落头像只在有 roomId 时显示；走真实入口（派发 gameStateUpdate）而不是硬改 display。
  gameState.roomId = 'r1';
  gameState.playerId = 'me';
  gameState.currentPhase = 'battle';
  gameState.currentAttacker = 'me';
  gameState.frozen = false;
  gameState.hand = [{ name: ${JSON.stringify(CARD.name)}, speed: ${CARD.speed}, type: ${JSON.stringify(CARD.type)} }];
  window.dispatchEvent(new Event('gameStateUpdate'));
  updateHandUI();

  // ⚠️ 换掉 socket 之前先把页面【真实注册】的监听器抄下来，
  // 后面喂 active_effects 事件走的还是页面自己的回调（测真实路径，不是测我写的桩）。
  if (!window.__realCallbacks) {
    if (!gameState.socket && typeof ensureSocket === 'function') { ensureSocket(); }
    window.__realCallbacks = (gameState.socket && gameState.socket._callbacks) || {};
  }
  window.__sent = [];
  window.__msgs = [];
  gameState.socket = {
    emit: function(name, payload){ window.__sent.push({ name: name, payload: payload }); },
    on: function(){ return this; }
  };
  window.showAlert = function(m){ window.__msgs.push(String(m)); };
  window.showMessage = function(m){ window.__msgs.push(String(m)); };
  if (typeof playSfx === 'function') window.playSfx = function(){};

  var hand = document.getElementById('magic-hand');
  var card = hand && hand.querySelector('.magic-card');
  return {
    screenActive: !!(document.getElementById('game-screen')
        && document.getElementById('game-screen').classList.contains('active')),
    hasHand: !!hand,
    hasCard: !!card,
  };
})()`);
check(setup.screenActive === true, '（前提）已进入对局界面 #game-screen.active', setup.screenActive);
check(setup.hasHand && setup.hasCard, '（前提）手牌区与那张速阶3卡都渲染出来了', setup);

const registered = await ev(`Object.keys(window.__realCallbacks || {}).filter(function(k){
  return k.indexOf('active_effects') >= 0;
})`);
check(Array.isArray(registered) && registered.includes('$active_effects'),
  '页面注册了 active_effects 监听（角标走真实回调渲染）', registered);

// 喂一份和真实服务端同形状的 active_effects（self=我，opponent 留空）。
//
// ⚠️ 同时把 room_sync 的那两个布尔字段清掉：`isLastStandActive()` 的**第一条**判断是
// `gameState.lastStandLock === true`，只要它还留着上一段的 true，后面"只剩击杀即胜"那一轮
// 就会被这个残留字段拦下 —— 于是 v3 断言成了"另一个原因造成的假绿/假红"。
// 清空 = 明确模拟"room_sync 说锁卡没生效，角标列表里只有击杀即胜"。
async function feed(self) {
  const r = await ev(`(function(){
    var cbs = (window.__realCallbacks || {})['$active_effects'];
    if (!cbs || !cbs.length) return 'no-listener';
    gameState.lastStandLock = false;
    gameState.lastStandWin = false;
    cbs.forEach(function(cb){ cb({ self: ${JSON.stringify(self)}, opponent: [] }); });
    return 'ok';
  })()`);
  await sleep(350);
  return r;
}

// 读我这边角标的实际渲染结果：显示文字 / data 属性 / 有没有实际尺寸。
async function readBadges() {
  return await ev(`(function(){
    var box = document.getElementById('my-effect-indicators');
    if (!box) return { error: 'no-box' };
    var btns = Array.prototype.slice.call(box.querySelectorAll('.effect-icon'));
    return btns.map(function(b){
      var r = b.getBoundingClientRect();
      return {
        text: (b.textContent || '').trim(),
        name: b.dataset.effectName || '',
        key: b.dataset.effectKey || '',
        w: Math.round(r.width), h: Math.round(r.height),
      };
    });
  })()`);
}

// 点击那张速度3卡（真实 UI 路径：点一次选中、再点一次才发动）。
// 返回：有没有发出 use_magic_card + 页内提示文案。
async function clickMeasureCard() {
  await ev(`(function(){
    window.__sent = []; window.__msgs = [];
    gameState.selectedCardIndex = -1; gameState.selectedCardKey = null;
    updateHandUI();
    // 卡片可能在视口外（对局页较长），滚动一下省得点到看不见的东西上。
    var c = document.querySelector('#magic-hand .magic-card');
    if (c && c.scrollIntoView) c.scrollIntoView({ block: 'center' });
    return true;
  })()`);
  await sleep(200);
  const geom = await ev(`(function(){
    var box = document.getElementById('magic-hand');
    var c = box && box.querySelector('.magic-card');
    if (!box || !c) return null;
    var rb = box.getBoundingClientRect(), rc = c.getBoundingClientRect();
    return { boxW: Math.round(rb.width), boxH: Math.round(rb.height),
             cardW: Math.round(rc.width), cardH: Math.round(rc.height) };
  })()`);
  const clicked = await ev(`(function(){
    var c = document.querySelector('#magic-hand .magic-card');
    if (!c) return 'no-card';
    c.click();                       // 第一次：选中
    updateHandUI();
    var c2 = document.querySelector('#magic-hand .magic-card');
    if (!c2) return 'no-card-after-select';
    c2.click();                      // 第二次：发动
    return 'ok';
  })()`);
  await sleep(300);
  return {
    geom,
    clicked,
    sent: await ev('window.__sent || []'),
    alerts: await ev('window.__msgs || []'),
  };
}

const usesMagic = (r) => (r.sent || []).filter((e) => e.name === 'use_magic_card');
const LAST_STAND_REJECT = /绝处逢生生效中|本回合你的其余魔法卡全部无效/;

// ===========================================================================
// 1. 两条角标同时喂：都渲染、文字能区分、都有实际尺寸
// ===========================================================================
console.log('--- 1. 两条角标并存（发动当回合：锁卡 + 击杀即胜）---');
await feed([BADGE_LOCK, BADGE_WIN]);
const both = await readBadges();
check(Array.isArray(both) && both.length === 2,
  '★ 两条角标都渲染出来了（不是只剩一条 / 合成一条）', both);
check(Array.isArray(both) && both.some((b) => b.text === '绝处逢生·锁卡'),
  '★ 锁卡那条显示名是「绝处逢生·锁卡」', both);
check(Array.isArray(both) && both.some((b) => b.text === '绝处逢生·击杀即胜'),
  '★ 「击杀即胜」那条显示名是「绝处逢生·击杀即胜」', both);
check(Array.isArray(both) && both.length === 2 && both[0].text !== both[1].text,
  '★ 两条角标文字能区分开（玩家一眼看得出是两个效果）', both);
check(Array.isArray(both) && both.length === 2
      && both.every((b) => b.w > 0 && b.h > 0),
  '★ 两条角标都有实际尺寸（否则后面的点击断言全是 0×0 假通过）', both);
check(Array.isArray(both) && both.length === 2
      && both[0].key === 'last_stand' && both[1].key === 'last_stand_win',
  '★ 角标带回了标记名 key（门禁靠它区分，不能靠卡名）', both.map((b) => b.key));

// ===========================================================================
// 2. 只有「击杀即胜」：魔法卡【不能】被拦（本次要钉死的回归）
// ===========================================================================
console.log('');
console.log('--- 2. 只喂「击杀即胜」（模拟换小回合后锁卡已过期）---');
await feed([BADGE_WIN]);
const winOnly = await readBadges();
check(Array.isArray(winOnly) && winOnly.length === 1 && winOnly[0].text === '绝处逢生·击杀即胜',
  '（前提）此时只剩「击杀即胜」一条角标', winOnly);

const r2 = await clickMeasureCard();
check(r2.clicked === 'ok' && r2.geom && r2.geom.cardW > 0 && r2.geom.cardH > 0,
  '（前提）点了真实的速阶3手牌元素，且它有实际尺寸', { clicked: r2.clicked, geom: r2.geom });
check(usesMagic(r2).length === 1,
  '★★ 只剩「击杀即胜」时，速阶3魔法卡【没有被前端本地拦下】（真的发出了 use_magic_card）', r2.sent);
check(!(r2.alerts || []).some((m) => LAST_STAND_REJECT.test(m)),
  '★★ 也没有弹出「绝处逢生生效中，本回合你的其余魔法卡全部无效」这种拒绝提示', r2.alerts);
check((r2.alerts || []).length === 0,
  '★★ 整条出牌路径零拒绝提示（跟服务端放行的口径一致）', r2.alerts);

// 顺带把判定函数本身钉一遍：新口径的标记名必须区分开，卡名兜底不能反过来吃掉门禁。
const markerCases = await ev(`(function(){
  var out = {};
  var probe = function(effects, lock){
    gameState.lastStandLock = !!lock;
    gameState.activeEffectsSelf = [];
    gameState.activeEffects = effects;
    return isLastStandActive();
  };
  out.winOnly      = probe([{ key: 'last_stand_win', name: '绝处逢生', label: '绝处逢生·击杀即胜' }], false);
  out.lockOnly     = probe([{ key: 'last_stand', name: '绝处逢生', label: '绝处逢生·锁卡' }], false);
  out.syncLockTrue = probe([], true);      // room_sync 的 last_stand_lock 字段
  out.syncBothOff  = probe([], false);
  out.legacyString = probe(['绝处逢生'], false);                        // 老的纯字符串数组口径
  out.other        = probe(['百亿补贴'], false);
  return out;
})()`);
check(markerCases.winOnly === false,
  '★ isLastStandActive：只挂「击杀即胜」时必须为 false（这就是原始 bug 的开关）', markerCases);
check(markerCases.lockOnly === true,
  '★ isLastStandActive：挂「锁卡」时必须为 true', markerCases);
check(markerCases.syncLockTrue === true,
  '★ isLastStandActive：room_sync 的 last_stand_lock=true 也认', markerCases);
check(markerCases.syncBothOff === false, 'isLastStandActive：两个标记都关时是 false', markerCases);
check(markerCases.legacyString === true,
  '★ isLastStandActive：兼容老的纯字符串「绝处逢生」口径（升级瞬间不能把门禁整个放开）', markerCases);
check(markerCases.other === false, 'isLastStandActive：无关效果不会误判', markerCases);

// ===========================================================================
// 3. 只有「锁卡」：魔法卡【必须】被拦（反证，防止把门禁改没了）
// ===========================================================================
console.log('');
console.log('--- 3. 只喂「锁卡」（模拟发动当回合）：必须被拦 ---');
await feed([BADGE_LOCK]);
const lockOnly = await readBadges();
check(Array.isArray(lockOnly) && lockOnly.length === 1 && lockOnly[0].text === '绝处逢生·锁卡',
  '（前提）此时只剩「锁卡」一条角标', lockOnly);

const r3 = await clickMeasureCard();
check(r3.clicked === 'ok' && r3.geom && r3.geom.cardW > 0,
  '（前提）点了真实的速阶3手牌元素', { clicked: r3.clicked, geom: r3.geom });
check(usesMagic(r3).length === 0,
  '★★ 锁卡生效时，速阶3魔法卡【必须】被前端拦下（不能发出 use_magic_card）', r3.sent);
check((r3.alerts || []).some((m) => /绝处逢生生效中/.test(m)),
  '★★ 拦下时给出的理由点名「绝处逢生生效中」（不是甩锅给阶段）', r3.alerts);
check(!(r3.alerts || []).some((m) => /当前阶段/.test(m)),
  '拦下的理由不甩锅给「当前阶段」（阶段明明是对的）', r3.alerts);

// ===========================================================================
// 4. 浮层显示的是卡面原文（不是空字符串）—— 两条角标都要能取到
// ===========================================================================
console.log('');
console.log('--- 4. 浮层（hover/click 角标）显示卡面原文 ---');
// 页面自带卡表里的「绝处逢生」原文：服务端 description 与它是同一份，用来比对"没写花"。
const cardDesc = await ev(`(function(){
  var c = (typeof lookupCard === 'function') ? lookupCard('绝处逢生') : null;
  return c ? String(c.description || '') : '';
})()`);
note('页面卡表里「绝处逢生」的卡面原文', cardDesc ? cardDesc.slice(0, 40) + '…' : '(空)');

// 服务端真下发时的 description 用页面卡表原文替代占位符，
// 免得断言只是证明了"我喂进去什么就显示什么"。
const realBadge = (b) => Object.assign({}, b, { description: cardDesc });

async function popoverFor(index, how) {
  await ev(`(function(){ if (typeof hideEffectPopover === 'function') hideEffectPopover(); return true; })()`);
  await sleep(150);
  const fired = await ev(`(function(){
    var btns = document.querySelectorAll('#my-effect-indicators .effect-icon');
    var b = btns[${index}];
    if (!b) return 'no-badge';
    if (${JSON.stringify(how)} === 'hover') {
      b.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    } else {
      b.click();
    }
    return 'ok';
  })()`);
  await sleep(350);
  const pop = await ev(`(function(){
    var p = document.querySelector('.effect-popover');
    if (!p || p.classList.contains('hidden')) return null;
    var r = p.getBoundingClientRect();
    return {
      who: (p.querySelector('.effect-popover-who') || {}).textContent,
      name: (p.querySelector('.effect-popover-name') || {}).textContent,
      body: (p.querySelector('.effect-popover-body') || {}).textContent,
      expiry: (p.querySelector('.effect-popover-expiry') || {}).textContent,
      anchorName: p.dataset.for || '',
      w: Math.round(r.width), h: Math.round(r.height),
    };
  })()`);
  return { fired, pop };
}

await feed([realBadge(BADGE_LOCK), realBadge(BADGE_WIN)]);
const hov0 = await popoverFor(0, 'hover');
check(hov0.fired === 'ok' && !!hov0.pop,
  '★ 鼠标移到第 1 条角标（锁卡）弹出了浮层', hov0);
if (hov0.pop) {
  check(hov0.pop.w > 0 && hov0.pop.h > 0, '浮层有实际尺寸（不是 hidden 的空壳）', hov0.pop);
  check(hov0.pop.name === '绝处逢生',
    '★ 浮层标题用的是服务端下发的 name（卡名=绝处逢生）', hov0.pop.name);
  check(typeof hov0.pop.body === 'string' && hov0.pop.body.trim().length > 0,
    '★★ 浮层正文是卡面原文，不是空字符串（说明 name 没被写花、能回查到卡面）', hov0.pop.body);
  check(cardDesc.length > 0 && hov0.pop.body === cardDesc,
    '★ 浮层正文逐字等于卡表里「绝处逢生」的卡面原文', {
      got: String(hov0.pop.body).slice(0, 40), want: cardDesc.slice(0, 40) });
}

const hov1 = await popoverFor(1, 'hover');
check(hov1.fired === 'ok' && !!hov1.pop,
  '★ 鼠标移到第 2 条角标（击杀即胜）也弹出了浮层', hov1);
if (hov1.pop) {
  check(hov1.pop.name === '绝处逢生',
    '★ 「击杀即胜」的浮层标题同样是卡名「绝处逢生」', hov1.pop.name);
  check(typeof hov1.pop.body === 'string' && hov1.pop.body.trim().length > 0,
    '★★ 「击杀即胜」的浮层正文也是卡面原文，不是空字符串', hov1.pop.body);
  check(cardDesc.length > 0 && hov1.pop.body === cardDesc,
    '★ 「击杀即胜」的浮层正文逐字等于卡面原文', String(hov1.pop.body).slice(0, 40));
}

// 只报不判：两条角标的 name 相同，浮层是按 name 回查的 —— 说明它取到的是
// 列表里第一个同名项，于是「击杀即胜」的失效时机可能显示成「锁卡」那条。
// 这不属于本次回归的必修项，但玩家会看到"击杀即胜 · 本回合结束时失效"这种错话，故记进报告。
if (hov0.pop && hov1.pop) {
  note('浮层回查是否被同名卡名串台',
    { 锁卡的expires: hov0.pop.expiry, 击杀即胜的expires: hov1.pop.expiry });
  if (hov0.pop.expiry === hov1.pop.expiry) {
    note('⚠️ 两条角标的失效时机显示成了同一句（服务端 truth 是：last_stand=_EFFECT_EXPIRY_TURN「本回合结束时失效」'
      + ' / last_stand_win=_EFFECT_EXPIRY_MATCH「本局一直有效」）'
      + ' —— effectOfBadge（static/game.js）按 name 回查，两条 name 都是「绝处逢生」所以都命中列表里第一条');
  }
}

// 手机端：触屏没有 hover，点一下也要能展开
await ev(`(function(){ if (typeof hideEffectPopover === 'function') hideEffectPopover(); return true; })()`);
const tap = await ev(`(function(){
  var b = document.querySelectorAll('#my-effect-indicators .effect-icon')[1];
  if (!b) return 'no-badge';
  b.click();
  return 'ok';
})()`);
await sleep(350);
const tapPop = await ev(`(function(){
  var p = document.querySelector('.effect-popover');
  if (!p || p.classList.contains('hidden')) return null;
  return { body: (p.querySelector('.effect-popover-body') || {}).textContent };
})()`);
check(tap === 'ok' && !!tapPop && String(tapPop.body || '').trim().length > 0,
  '★ 点击（手机端）也能展开出卡面原文', { tap, tapPop });

// ===========================================================================
// 5. 兼容：旧的纯字符串数组（升级瞬间不白屏）
// ===========================================================================
console.log('');
console.log('--- 5. 兼容旧的纯字符串数组 ---');
const legacyFeed = await feed(['百亿补贴']);
check(legacyFeed === 'ok', '（前提）喂进旧形状没有抛异常', legacyFeed);
const legacyBadges = await readBadges();
check(Array.isArray(legacyBadges) && legacyBadges.length === 1
      && legacyBadges[0].text === '百亿补贴',
  '★ active_effects 喂 [\'百亿补贴\'] 不白屏，角标照常渲染', legacyBadges);
check(Array.isArray(legacyBadges) && legacyBadges[0].w > 0 && legacyBadges[0].h > 0,
  '旧形状的角标也有实际尺寸', legacyBadges);
const legacyPageAlive = await ev(
  'typeof updateHandUI === "function" && document.querySelectorAll("#magic-hand .magic-card").length === 1');
check(legacyPageAlive === true, '★ 旧形状喂完之后页面还活着（手牌区没被搞坏）', legacyPageAlive);

const legacyClick = await clickMeasureCard();
check(usesMagic(legacyClick).length === 1 && !(legacyClick.alerts || []).some((m) => LAST_STAND_REJECT.test(m)),
  '★ 旧形状下的速阶3卡照常打得出去（无关效果不会误锁魔法卡）', legacyClick);

// ===========================================================================
// 6. 旧形状的角标对象（只有 name/description/expires，没有 key/label）
// ===========================================================================
console.log('');
console.log('--- 6. 兼容没有 key/label 的旧角标对象 ---');
const legacyObj = { name: '百亿补贴', description: cardDesc, expires: '本回合结束时失效' };
await feed([legacyObj]);
const legacyObjBadges = await readBadges();
check(Array.isArray(legacyObjBadges) && legacyObjBadges.length === 1
      && legacyObjBadges[0].text === '百亿补贴',
  '★ 缺 label 时退回用 name 显示，不会渲染成空角标', legacyObjBadges);
check(Array.isArray(legacyObjBadges) && legacyObjBadges[0].w > 0 && legacyObjBadges[0].h > 0,
  '旧形状角标有实际尺寸', legacyObjBadges);

// 旧形状的 last_stand（只有 name='绝处逢生'）：兜底必须仍然锁卡，否则升级瞬间门禁全开
await feed([{ name: '绝处逢生', description: cardDesc, expires: '本回合结束时失效' }]);
const legacyLockBadges = await readBadges();
check(Array.isArray(legacyLockBadges) && legacyLockBadges.length === 1
      && legacyLockBadges[0].text === '绝处逢生',
  '★ 旧形状的「绝处逢生」角标（没有 key）照常渲染', legacyLockBadges);
const legacyLockClick = await clickMeasureCard();
check(usesMagic(legacyLockClick).length === 0
      && (legacyLockClick.alerts || []).some((m) => LAST_STAND_REJECT.test(m)),
  '★★ 旧形状（只有卡名、没有 key）时【仍然锁卡】 —— 兜底不能把门禁整个放开',
  { sent: legacyLockClick.sent, alerts: legacyLockClick.alerts });

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
