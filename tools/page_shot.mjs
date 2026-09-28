#!/usr/bin/env node
/**
 * 通用页面出图（无头 Edge + CDP）—— 给"某一屏改了要看一眼"用。
 *
 * 为什么需要它：项目里已有的出图工具都是**对局专用**（要么真打一局、要么带业务前提），
 * 而改一屏之后想立刻看一眼这种情况，用它们要么太重、要么会被对局状态污染。
 *
 * ⚠️ 三个必须做对的地方（本项目都栽过）：
 *   ① **禁用缓存**：style.css 没有内容戳，持久 profile 会命中旧 CSS → 「改了没效果」的假象；
 *   ② **干净 profile**：残留无头进程会让新浏览器静默起不来（用项目内 .tmp 下的独立目录）；
 *   ③ 切视口后要等布局稳定再截。
 *
 * 用法：
 *   node tools/page_shot.mjs --url http://127.0.0.1:5099/ --out .tmp/home.png
 *   node tools/page_shot.mjs --url http://127.0.0.1:5099/ --out .tmp/home-390.png --w 390 --h 844 --dsf 2
 *   node tools/page_shot.mjs --url http://127.0.0.1:5099/ --out .tmp/after.png --script "document.getElementById('help-btn').click()"
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5099/');
const OUT = argOf('--out', '.tmp/page_shot.png');
const W = Number(argOf('--w', '1440'));
const H = Number(argOf('--h', '900'));
const DSF = Number(argOf('--dsf', '1'));
const SCRIPT = argOf('--script', '');   // 可选：截图前在页面里执行一句（例如点开某个弹窗）
const EVAL = argOf('--eval', '');       // 可选：打印一句表达式的返回值（排查用，例如查 CSSOM）
const PORT = 9351;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PROFILE = path.join(ROOT, '.tmp', 'page_shot_profile');

const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
if (!EDGE) { console.error('找不到 Edge/Chrome'); process.exit(1); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws = null, browser = null;
const pending = new Map();
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
  if (r.exceptionDetails) throw new Error('页面异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 240));
  return r.result && r.result.value;
}

(async () => {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) { /* 无所谓 */ }
  fs.mkdirSync(path.dirname(path.resolve(OUT)), { recursive: true });

  browser = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE, `--window-size=${W},${H}`, '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || ''))
        || list.find((t) => t.type === 'page' && !/^(edge|chrome|devtools):/.test(t.url || ''));
      if (target) break;
    } catch (e) { /* 还在启动 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });   // ← ① 关键
  await send('Emulation.setDeviceMetricsOverride', {
    width: W, height: H, deviceScaleFactor: DSF, mobile: DSF > 1, screenWidth: W, screenHeight: H,
  });

  await send('Page.navigate', { url: APP });
  await sleep(1400);                       // 等首屏 + socket 连接
  if (SCRIPT) { await ev(SCRIPT); await sleep(900); }

  const shot = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.resolve(OUT), Buffer.from(shot.data, 'base64'));
  console.log(`已出图 ${OUT}  (${W}x${H} dsf=${DSF})`);

  // 顺手报一句页面真实状态，省得"图糊了但不知道为什么"
  const info = await ev(`JSON.stringify({
    inner: innerWidth + 'x' + innerHeight,
    dpr: devicePixelRatio,
    hero: (function(){ var e = document.querySelector('.home-hero'); if (!e) return 'no-.home-hero';
      var cs = getComputedStyle(e); var r = e.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height), border: cs.borderTopColor, bg: cs.backgroundImage.slice(0, 60) }; })(),
    tt: (function(){ var e = document.querySelector('.mode-btn .tt'); if (!e) return 'no-.tt';
      return getComputedStyle(e).display; })()
  })`);
  console.log('页面状态: ' + info);
  if (EVAL) console.log('eval: ' + JSON.stringify(await ev(EVAL)));

  try { ws.close(); } catch (e) { /* 忽略 */ }
  try { browser.kill(); } catch (e) { /* 忽略 */ }
  process.exit(0);
})().catch((e) => {
  console.error('失败: ' + e.message);
  try { browser && browser.kill(); } catch (_) { /* 忽略 */ }
  process.exit(1);
});
