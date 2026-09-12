#!/usr/bin/env node
/**
 * 人机对战难度选择回归检查（无头 Edge + CDP）
 *
 * 覆盖 2026-09-13 新增能力：AI 会打出手上的魔法卡（此前一张都不出）。
 * 难度分档：easy = 电脑不出牌（新手保底）；normal / hard = 电脑会出牌。
 * 本脚本验证「所选难度确实随 create_ai_room 发给了服务端」，以及下拉框本身可用。
 *
 * 用法：
 *   node tools/ai_difficulty_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9336;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/ai_difficulty_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过人机难度检查'); process.exit(0); }

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

  const opts = await ev('(function(){ var s = document.getElementById("ai-difficulty"); if (!s) return null;' +
    ' return { options: [].slice.call(s.options).map(function (o) { return o.value; }), value: s.value,' +
    ' visible: !!(s.offsetWidth || s.offsetHeight) }; })()');
  check(!!opts, '首页存在人机难度下拉框', opts);
  if (!opts) throw new Error('缺少 #ai-difficulty');
  check(opts.options.join(',') === 'easy,normal,hard', '三档难度齐备', opts.options);
  check(opts.value === 'normal', '默认难度为普通（电脑会出牌）', opts.value);
  check(opts.visible === true, '下拉框可见（不是 hidden）', opts.visible);

  // 拦 emit：先确保 socket 已建，再替换 emit 只做捕获
  const stubbed = await ev('(function(){ if (typeof ensureSocket === "function") { try { ensureSocket(); } catch (e) {} }' +
    ' if (!gameState.socket) return "no-socket";' +
    ' window.__cap = [];' +
    ' gameState.socket.emit = function (ev, data, cb) { window.__cap.push({ ev: ev, data: data }); return this; };' +
    ' return "stubbed"; })()');
  check(stubbed === 'stubbed', '成功拦截 emit（用于断言真实 payload）', stubbed);

  for (const level of ['easy', 'normal', 'hard']) {
    await ev('(function(){ var s = document.getElementById("ai-difficulty"); s.value = "' + level + '";' +
      ' document.getElementById("ai-match").click(); return true; })()');
    await sleep(400);
    const cap = await ev('(function(){ var last = window.__cap[window.__cap.length - 1]; return last || null; })()');
    check(!!cap && cap.ev === 'create_ai_room' && cap.data && cap.data.difficulty === level,
      '选择“' + level + '”时 create_ai_room 带上对应难度', cap && { ev: cap.ev, difficulty: cap.data && cap.data.difficulty });
  }

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
