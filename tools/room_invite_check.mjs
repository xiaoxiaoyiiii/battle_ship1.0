#!/usr/bin/env node
/**
 * 房间邀请链接回归检查（无头 Edge + CDP）
 *
 * 背景：前端早就有 `?room=XXXX` 的自动入房逻辑，但**没有任何入口生成这个链接** ——
 * 只能口头报房间号。本脚本验证新增的「🔗 复制邀请链接」按钮：
 *   1. 创建房间后按钮可见；
 *   2. 点击后复制的是 `<origin><path>?room=<房间号>`（前端自动入房认的就是这个参数）；
 *   3. 剪贴板不可用时降级到 prompt（把同一个链接给玩家手动复制）。
 *
 * 用法：
 *   node tools/room_invite_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9337;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/room_invite_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过邀请链接检查'); process.exit(0); }

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
    await sleep(200);
  }
  throw new Error('等待超时: ' + label);
}

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

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
      target = list.find((t) => t.type === 'page');
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
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');

  // 进入自定义房间界面并真的建一个房（走服务端 create_room）
  await ev('(function(){ document.getElementById("custom-room").click(); return 1; })()');
  await waitFor(async () => await ev('document.getElementById("custom-room-screen").classList.contains("active")'), 10000, '自定义房间界面');
  await ev('(function(){ document.getElementById("custom-create-room").click(); return 1; })()');
  await waitFor(async () => await ev('(function(){ var el = document.getElementById("custom-room-info"); return el && !el.classList.contains("hidden"); })()'), 20000, '房间创建完成');
  const roomId = await ev('document.getElementById("custom-current-room-id").textContent.trim()');
  check(!!roomId, '创建房间后界面上有房间号', roomId);

  const btn = await ev('(function(){ var b = document.getElementById("copy-invite-link"); if (!b) return null;' +
    ' return { text: b.textContent.trim(), visible: !!(b.offsetWidth || b.offsetHeight), hidden: b.closest(".hidden") ? true : false }; })()');
  check(!!btn && btn.visible && !btn.hidden, '房间号旁出现可见的「复制邀请链接」按钮', btn);

  // 剪贴板可用：断言复制的正是自动入房认的那个 URL。
  // 注意必须同时把 window.prompt 换掉：真实剪贴板被拒时会走 prompt 降级，
  // 而 headless 下原生 prompt 会**阻塞渲染进程**，后续 evaluate 全部超时。
  await ev('(function(){ window.__copied = null; window.__prompted = null;' +
    ' window.prompt = function (text, def) { window.__prompted = def; return null; };' +
    ' Object.defineProperty(navigator, "clipboard", { configurable: true,' +
    '   value: { writeText: function (t) { window.__copied = t; return Promise.resolve(); } } });' +
    ' return 1; })()');
  await ev('document.getElementById("copy-invite-link").click()');
  await sleep(400);
  const copied = await ev('window.__copied');
  const origin = await ev('window.location.origin');
  check(typeof copied === 'string' && copied.indexOf('?room=' + roomId) >= 0,
    '复制的是带 ?room=<房间号> 的邀请链接', copied);
  check(typeof copied === 'string' && copied.indexOf(origin) === 0,
    '邀请链接以当前站点为前缀（点开即自动入房）', { copied: copied, origin: origin });
  const msg = await ev('(function(){ var m = document.getElementById("invite-link-msg"); return m ? m.textContent.trim() : null; })()');
  check(!!msg, '复制后给出反馈文案', msg);

  // 剪贴板不可用：必须降级到 prompt 且给的是同一个链接
  await ev('(function(){ window.__prompted = null;' +
    ' Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });' +
    ' return 1; })()');
  await ev('document.getElementById("copy-invite-link").click()');
  await sleep(400);
  const prompted = await ev('window.__prompted');
  check(typeof prompted === 'string' && prompted.indexOf('?room=' + roomId) >= 0,
    '剪贴板不可用时降级到 prompt，链接一致', prompted);

  if (SHOT) { const s = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(SHOT, Buffer.from(s.data, 'base64')); console.log('截图已保存: ' + SHOT); }
  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  console.log(NL + (problems.length ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL) : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
