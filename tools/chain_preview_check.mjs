#!/usr/bin/env node
/**
 * 连锁响应窗口「对方发动的那张卡可预览」回归检查（无头 Edge + CDP）
 *
 * 作者要求（2026-09-17）：连锁询问窗口里，标题写「对方发动了魔法卡【XXX】」，
 * 只给个卡名等于让人猜效果 —— 鼠标移上去要能看、移动端点一下也要能看。
 *
 * 断言：P1 标题里的卡名是可交互锚点 / P2 桌面悬停出浮层且带真实卡面描述 /
 *       P3 移开收起 / P4 点击出详情小窗 / P5 点它【不会】被当成"响应连锁" /
 *       P6 详情可关闭 / P7 触摸分支（无 hover）点一下也能看 /
 *       P8 原有点卡出牌逻辑未被破坏。
 *
 * 用法：
 *   node tools/chain_preview_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 *
 * 被检查的服务端必须放行该来源：
 *   PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 python server.py
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9343;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = new URL('../.tmp/chain_preview_profile', import.meta.url).pathname.replace(/^\//, '');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过连锁预览检查'); process.exit(0); }

let browser = null, ws = null;
const pending = new Map();
const problems = [];
let seq = 0;

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
  });
}

async function ev(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await fn()) return true; } catch (e) { /* keep polling */ }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label);
}

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

async function enterGame() {
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="预览检查"; document.getElementById("ai-match").click(); return true;})()');
  await waitFor(async () => await ev('document.getElementById("ship-placement-screen").classList.contains("active")'), 30000, '布船界面');
  await ev('document.getElementById("random-ships").click()');
  await sleep(400);
  await ev('document.getElementById("confirm-ships").click()');
  await waitFor(async () => await ev('document.getElementById("rps-screen").classList.contains("active")'), 30000, '猜拳界面');
  for (let i = 0; i < 5; i++) {
    await ev('document.querySelectorAll(".rps-choice")[0].click()');
    await sleep(3000);
    if (await ev('document.getElementById("game-screen").classList.contains("active")')) break;
  }
  await waitFor(async () => await ev('document.getElementById("game-screen").classList.contains("active")'), 20000, '对局界面');
  await sleep(600);
}

// 用真实监听器触发 chain_request（socket.io v4: socket._callbacks），
// 卡面数据同时写进 payload 与 window.magicCards，确保断言用的是真实来源。
const TRIGGER_CARD = {
  name: '百亿补贴', speed: 3, type: '普通',
  description: '在这张牌成功生效之后，接下来如果自己的船被对方不管用什么手段击败了，自己的攻击次数每有一艘船死亡就加3。',
};

function fireChain(cards) {
  return '(function(){ var s = gameState.socket; var cbs = s && s._callbacks && s._callbacks["$chain_request"];' +
    ' if (!cbs || !cbs.length) return "no-handler";' +
    ' var payload = { speed3_cards: ' + JSON.stringify(cards) +
    ', card: ' + JSON.stringify(TRIGGER_CARD) +
    ', caster: "opponent-x", countdown: 10 };' +
    ' cbs.slice().forEach(function (f) { f(payload); }); return "ok"; })()';
}

const PROMPT_STATE = '(function(){' +
  ' var prompt = document.querySelector(".chain-request-prompt");' +
  ' var ref = prompt && prompt.querySelector("#chain-request-activated");' +
  ' return { prompt: !!prompt,' +
  '   ref: !!ref,' +
  '   refText: ref ? ref.textContent.trim() : null,' +
  '   titleText: prompt ? (prompt.querySelector("h3") || {}).textContent : null,' +
  '   hint: prompt ? (prompt.querySelector(".chain-request-hint") || {}).textContent : null,' +
  '   tooltip: (document.querySelector(".card-tooltip") || {}).textContent || "",' +
  '   tooltipName: (document.querySelector(".card-tooltip-name") || {}).textContent || "",' +
  '   detail: !!document.getElementById("card-detail-overlay"),' +
  '   detailText: (document.getElementById("card-detail-overlay") || {}).textContent || "" }; })()';

const HOVER_REF = '(function(){ var r = document.getElementById("chain-request-activated");' +
  ' if (!r) return "no-ref"; r.dispatchEvent(new MouseEvent("mouseenter")); return "hovered"; })()';
const UNHOVER_REF = '(function(){ var r = document.getElementById("chain-request-activated");' +
  ' if (!r) return "no-ref"; r.dispatchEvent(new MouseEvent("mouseleave")); return "left"; })()';

try {
  browser = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^(https?|about|file):/.test(t.url || ''))
        || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* browser still starting */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  const jsProblems = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await enterGame();

  // 拦截 emit：验证"点卡名"不会被当成响应连锁
  const stub = await ev('(function(){ window.__cap = []; var s = gameState.socket;' +
    ' if (!s) return "no-socket"; s.emit = function (ev, data, cb) { window.__cap.push({ ev: ev, data: data }); if (typeof cb === "function") { try { cb({status:"success"}); } catch (e) {} } };' +
    ' return "stubbed"; })()');
  check(stub === 'stubbed', 'P0 拦截前端 emit（断言点卡名不会误发 chain_response）', stub);

  const canHover = await ev('(!window.matchMedia || window.matchMedia("(hover: hover)").matches)');
  check(canHover === true, 'P0b 桌面环境下识别到 hover 能力（走悬停预览分支）', canHover);

  // ---------- 桌面分支 ----------
  const fired = await ev(fireChain([{ name: '失灵！', speed: 3, type: '普通', description: '无效化上一张魔法卡' }]));
  check(fired === 'ok', 'P1 触发连锁请求窗口', fired);

  const s1 = await ev(PROMPT_STATE);
  check(s1 && s1.prompt === true, 'P1b 弹窗出现', s1 && s1.prompt);
  check(s1 && s1.ref === true, 'P1c 标题里有可交互的卡名锚点（#chain-request-activated）', s1 && s1.refText);
  check(s1 && (s1.refText || '').indexOf('百亿补贴') >= 0, 'P1d 锚点显示的就是"对方发动的那张卡"', s1 && s1.refText);
  check(s1 && (s1.titleText || '').indexOf('对方发动了') >= 0, 'P1e 文案仍是「对方发动了魔法卡…」', s1 && s1.titleText);
  check(s1 && /卡名/.test(s1.hint || ''), 'P1f 提示文案写明可以看卡名', s1 && s1.hint);

  const hov = await ev(HOVER_REF);
  await sleep(250);
  const s2 = await ev(PROMPT_STATE);
  check(hov === 'hovered', 'P2 悬停卡名', hov);
  check(s2 && s2.tooltipName === '百亿补贴', 'P2b 悬停浮层显示卡名', s2 && s2.tooltipName);
  // 描述来自 window.magicCards（真实卡面），断言其中一段
  check(s2 && (s2.tooltip || '').indexOf('攻击次数每有一艘船死亡就加3') >= 0,
    'P2c 浮层带完整效果描述（不是只有卡名）', (s2 && s2.tooltip || '').slice(0, 60));

  const unhov = await ev(UNHOVER_REF);
  await sleep(200);
  const s3 = await ev(PROMPT_STATE);
  check(unhov === 'left' && s3 && s3.tooltip === '', 'P3 移开鼠标后浮层收起', { left: unhov, tooltip: s3 && s3.tooltip });

  const clicked = await ev('(function(){ var r = document.getElementById("chain-request-activated"); if (!r) return "no-ref"; r.click(); return "clicked"; })()');
  await sleep(250);
  const s4 = await ev(PROMPT_STATE);
  const cap = await ev('(function(){ return window.__cap.length; })()');
  check(clicked === 'clicked', 'P4 点击卡名', clicked);
  check(s4 && s4.detail === true, 'P4b 弹出卡牌详情小窗', s4 && s4.detail);
  check(s4 && (s4.detailText || '').indexOf('百亿补贴') >= 0 && (s4.detailText || '').indexOf('每有一艘船死亡就加3') >= 0,
    'P4c 详情里有卡名与效果描述', (s4 && s4.detailText || '').replace(/\s+/g, ' ').slice(0, 60));
  check(cap === 0, 'P5 点卡名【不会】发出任何 socket 事件（不等于响应连锁）', { emits: cap });

  const closed = await ev('(function(){ var b = document.querySelector("#card-detail-overlay .card-detail-close"); if (!b) return "no-close"; b.click(); return "closed"; })()');
  await sleep(200);
  const s5 = await ev(PROMPT_STATE);
  check(closed === 'closed' && s5 && s5.detail === false, 'P6 详情可关闭，连锁窗口仍在', { closed, detail: s5 && s5.detail, prompt: s5 && s5.prompt });

  if (SHOT) {
    await ev(HOVER_REF);
    await sleep(250);
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(png.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }

  // ---------- 触摸分支 ----------
  // showChainRequestPrompt 在调用时才读 matchMedia，因此可以直接桩掉它来
  // 确定性地走"无 hover"那条分支（比设备模拟稳定，不受无头浏览器差异影响）。
  await ev('(function(){ window.__cap = []; window.__origMM = window.matchMedia;' +
    ' window.matchMedia = function () { return { matches: false, addEventListener: function(){}, removeEventListener: function(){} }; };' +
    ' return true; })()');
  const fired2 = await ev(fireChain([]));
  check(fired2 === 'ok', 'P7 触摸分支：再次触发连锁请求', fired2);
  const t1 = await ev(PROMPT_STATE);
  check(t1 && /点一下先看效果/.test(t1.hint || ''), 'P7b 走的是触摸文案分支（无 hover）', t1 && t1.hint);
  const tHover = await ev(HOVER_REF);
  await sleep(200);
  const t2 = await ev(PROMPT_STATE);
  check(t2 && t2.tooltip === '', 'P7c 触摸分支不再绑悬停（移上去不会出浮层）', { hover: tHover, tooltip: t2 && t2.tooltip });
  const tClick = await ev('(function(){ var r = document.getElementById("chain-request-activated"); if (!r) return "no-ref"; r.click(); return "clicked"; })()');
  await sleep(250);
  const t3 = await ev(PROMPT_STATE);
  const tCap = await ev('(function(){ return window.__cap.length; })()');
  check(tClick === 'clicked' && t3 && t3.detail === true, 'P7d 触摸分支：点卡名照样能看到效果', { click: tClick, detail: t3 && t3.detail });
  check(tCap === 0, 'P7e 触摸分支点卡名同样不发 socket 事件', { emits: tCap });
  await ev('(function(){ var b = document.querySelector("#card-detail-overlay .card-detail-close"); if (b) b.click(); window.matchMedia = window.__origMM; return true; })()');

  // ---------- 原有出牌逻辑未被破坏 ----------
  await ev('(function(){ window.__cap = [];' +
    ' var p = document.querySelector(".chain-request-prompt"); if (p) p.remove();' +
    ' var c = document.getElementById("card-detail-overlay"); if (c) c.remove(); return true; })()');
  await ev(fireChain([{ name: '失灵！', speed: 3, type: '普通', description: '无效化上一张魔法卡' }]));
  const playClick = await ev('(function(){ var el = document.querySelector(".chain-request-card"); if (!el) return "no-item"; el.click(); return "clicked"; })()');
  await sleep(300);
  const lastCap = await ev('(function(){ var last = window.__cap[window.__cap.length - 1] || null; return last; })()');
  check(playClick === 'clicked', 'P8 点手牌里的速阶3卡', playClick);
  check(!!lastCap && lastCap.ev === 'chain_response' && lastCap.data && lastCap.data.card
    && lastCap.data.card.name === '失灵！', 'P8b 仍然正常发出 chain_response（预览锚点没抢走点击）',
    lastCap && lastCap.data && lastCap.data.card);

  check(jsProblems.length === 0, '全程无 JS 异常 / console.error', jsProblems.slice(0, 4));
} catch (err) {
  console.error('检查中断: ' + err.message);
  problems.push('中断: ' + err.message);
} finally {
  try { if (ws) ws.close(); } catch (e) { /* ignore */ }
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
}

console.log('');
console.log(problems.length ? ('✗ ' + problems.length + ' 项未通过: ' + problems.join(' | ')) : '✓ 全部通过');
process.exit(problems.length ? 1 : 0);
