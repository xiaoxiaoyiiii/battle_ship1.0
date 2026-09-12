#!/usr/bin/env node
/**
 * 战斗音效（SFX）回归检查（无头 Edge + CDP）
 *
 * 背景：项目此前全站零音效 —— 唯一的 new Audio() 是 BGM，而 static/music/ 目录
 * 根本不存在（6 条预设路径全 404）。现在音效改为 Web Audio **现场合成**，
 * 不需要任何音频素材，本脚本用桩 AudioContext 验证：
 *   1. 模块加载出 9 个音效；
 *   2. play() 真的会驱动振荡器/噪声缓冲（不是空函数）；
 *   3. 真实 socket 事件（炮击命中/落空/击沉、胜负、回合、连锁、摸牌）会触发对应音效；
 *   4. 静音开关生效（不再创建任何音频节点）。
 *
 * 用法：
 *   node tools/sfx_check.mjs --url http://127.0.0.1:5000/ [--shot out.png]
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const SHOT = argOf('--shot', '');
const PORT = 9338;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/sfx_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过音效检查'); process.exit(0); }

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
  await ev('(function(){var i=document.getElementById("player-name"); if(i) i.value="音效检查"; document.getElementById("ai-match").click(); return true;})()');
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

const STUB_AUDIO = '(function(){' +
  ' window.__audio = { oscillators: 0, buffers: 0, gains: 0, filters: 0, starts: 0, resumes: 0 };' +
  ' function FakeAudioContext() { this.currentTime = 0; this.sampleRate = 44100; this.state = "running"; this.destination = { connect: function () {} }; }' +
  ' FakeAudioContext.prototype.resume = function () { window.__audio.resumes++; return Promise.resolve(); };' +
  ' FakeAudioContext.prototype.createGain = function () { window.__audio.gains++; return { gain: { setValueAtTime: function () {}, exponentialRampToValueAtTime: function () {} }, connect: function () {} }; };' +
  ' FakeAudioContext.prototype.createOscillator = function () { window.__audio.oscillators++; return { type: "", frequency: { setValueAtTime: function () {}, exponentialRampToValueAtTime: function () {} }, connect: function () {}, start: function () { window.__audio.starts++; }, stop: function () {} }; };' +
  ' FakeAudioContext.prototype.createBiquadFilter = function () { window.__audio.filters++; return { type: "", frequency: { setValueAtTime: function () {}, exponentialRampToValueAtTime: function () {} }, connect: function () {} }; };' +
  ' FakeAudioContext.prototype.createBuffer = function (ch, len) { window.__audio.buffers++; return { getChannelData: function () { return new Float32Array(len); } }; };' +
  ' FakeAudioContext.prototype.createBufferSource = function () { return { buffer: null, connect: function () {}, start: function () { window.__audio.starts++; }, stop: function () {} }; };' +
  ' window.AudioContext = FakeAudioContext; window.webkitAudioContext = FakeAudioContext;' +
  ' window.__played = [];' +
  ' var orig = window.sfx.play;' +
  ' window.sfx.play = function (n) { window.__played.push(n); return orig.call(window.sfx, n); };' +
  ' return 1; })()';

function fireEvent(name, payload) {
  return '(function(){ var cbs = gameState.socket && gameState.socket._callbacks && gameState.socket._callbacks["$' + name + '"];' +
    ' if (!cbs || !cbs.length) return "no-handler";' +
    ' cbs.slice().forEach(function (f) { f(' + JSON.stringify(payload) + '); }); return "ok"; })()';
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

  const api = await ev('(function(){ return { hasSfx: !!(window.sfx && window.sfx.play), sounds: (window.sfx && window.sfx.sounds) || [] }; })()');
  check(api.hasSfx === true, '页面加载出音效模块（static/sfx.js）', api);
  check(Array.isArray(api.sounds) && api.sounds.length >= 8, '合成音效齐备', api.sounds);

  // 必须在进入对局之前装桩：sfx.js 会把 AudioContext 缓存在模块作用域里，
  // 一旦先跑了真实上下文，后面的桩就再也观测不到任何音频节点了。
  const stubbed = await ev(STUB_AUDIO);
  check(stubbed === 1, '桩 AudioContext 安装成功（真实合成路径可被观测）', stubbed);

  await enterGame();

  const before = await ev('JSON.parse(JSON.stringify(window.__audio))');
  const played = await ev('window.sfx.play("hit")');
  const after = await ev('JSON.parse(JSON.stringify(window.__audio))');
  check(played === true, 'sfx.play("hit") 返回 true', played);
  check(after.oscillators > before.oscillators && after.starts > before.starts,
    'play() 真的驱动了振荡器（不是空函数）', { before: before, after: after });

  // 静音：不应再创建任何节点
  await ev('window.sfx.setMuted(true)');
  const muteBefore = await ev('JSON.parse(JSON.stringify(window.__audio))');
  const mutePlayed = await ev('window.sfx.play("hit")');
  const muteAfter = await ev('JSON.parse(JSON.stringify(window.__audio))');
  check(mutePlayed === false && muteAfter.oscillators === muteBefore.oscillators,
    '静音后 play() 直接返回 false 且不创建音频节点', { played: mutePlayed, before: muteBefore.oscillators, after: muteAfter.oscillators });
  await ev('window.sfx.setMuted(false)');

  // 真实 socket 事件 → 对应音效
  const cases = [
    ['attack_result', { hit: true, ship_sunk: false, remaining_attacks: 3 }, 'hit'],
    ['attack_result', { hit: true, ship_sunk: true, remaining_attacks: 2 }, 'sunk'],
    ['attack_result', { hit: false, ship_sunk: false, remaining_attacks: 1 }, 'miss'],
  ];
  for (const [evt, payload, expected] of cases) {
    await ev('window.__played.length = 0');
    const r = await ev(fireEvent(evt, payload));
    const got = await ev('window.__played.slice()');
    check(r === 'ok' && got.indexOf(expected) >= 0,
      '收到 ' + evt + '（' + JSON.stringify(payload) + '）播放 ' + expected, got);
  }

  await ev('window.__played.length = 0');
  await ev('(function(){ gameState.playerId = "me"; return 1; })()');
  await ev(fireEvent('game_over', { winner: 'me' }));
  check((await ev('window.__played.slice()')).indexOf('win') >= 0, '获胜播放 win', await ev('window.__played.slice()'));

  await ev('window.__played.length = 0');
  await ev(fireEvent('game_over', { winner: 'other' }));
  check((await ev('window.__played.slice()')).indexOf('lose') >= 0, '落败播放 lose', await ev('window.__played.slice()'));

  await ev('window.__played.length = 0');
  await ev(fireEvent('turn_change', { current_attacker: 'me', attacks_remaining: 6, phase: 'preparation' }));
  check((await ev('window.__played.slice()')).indexOf('turn') >= 0, '轮到自己播放 turn', await ev('window.__played.slice()'));

  await ev('window.__played.length = 0');
  await ev('(function(){ gameState.hand = []; return 1; })()');
  await ev(fireEvent('hand_updated', { hand: [{ name: '冻结', speed: 2, type: '普通' }] }));
  check((await ev('window.__played.slice()')).indexOf('draw') >= 0, '摸牌播放 draw', await ev('window.__played.slice()'));

  await ev('window.__played.length = 0');
  const chainFired = await ev(fireEvent('chain_request', {
    card: { name: '无中生有', speed: 1, type: '普通' },
    caster: 'other',
    speed3_cards: [{ name: '失灵！', speed: 3, type: '普通' }],
    countdown: 10,
  }));
  check(chainFired === 'ok' && (await ev('window.__played.slice()')).indexOf('chain') >= 0,
    '连锁请求播放 chain', await ev('window.__played.slice()'));
  await ev('(function(){ var el = document.querySelector(".magic-prompt"); if (el) el.remove(); return 1; })()');

  // 设置面板里的静音开关
  const cb = await ev('(function(){ var el = document.getElementById("sfx-muted"); return el ? { exists: true, checked: el.checked } : { exists: false }; })()');
  check(cb && cb.exists === true, '设置面板里有「音效静音」开关', cb);
  const toggled = await ev('(function(){ var el = document.getElementById("sfx-muted"); el.checked = true; el.dispatchEvent(new Event("change")); return window.sfx.isMuted(); })()');
  check(toggled === true, '勾选后 sfx.isMuted() 为 true 且写入本地存储', toggled);
  await ev('(function(){ var el = document.getElementById("sfx-muted"); el.checked = false; el.dispatchEvent(new Event("change")); return 1; })()');

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
