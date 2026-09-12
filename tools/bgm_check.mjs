#!/usr/bin/env node
/**
 * 背景音乐（BGM）回归检查（无头 Edge + CDP）
 *
 * 背景：仓库里没有任何音频素材，`static/music/` 目录根本不存在，6 条预设路径全 404。
 * 原实现只是 console.error 后静默 playNext，轮完一圈就无声无息地停下。
 * 现在改为：整轮音轨失败时自动切到**内置合成环境音**（Web Audio 现场合成，零素材），
 * 并在界面上写明"已自动切换"。
 *
 * 本脚本用桩 AudioContext 验证：
 *   1. 所有音轨 404 后真的启用了合成音（创建了振荡器/LFO，并写进 debug 状态）；
 *   2. 界面文案说明了已切换，而不是只报错；
 *   3. 暂停/继续能挂起与恢复合成音；音量/静音会作用到合成音的输出增益；
 *   4. "上一首/下一首"在合成音模式下不会把 404 循环又拉起来。
 *
 * 用法：node tools/bgm_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9341;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/bgm_check_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过 BGM 检查'); process.exit(0); }

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

const STUB_AUDIO = '(function(){' +
  ' window.__audio = { osc: 0, gain: 0, filter: 0, started: 0, suspended: 0, resumed: 0 };' +
  ' function Ctx() { this.currentTime = 0; this.sampleRate = 44100; this.state = "running"; this.destination = { connect: function () {} }; }' +
  ' Ctx.prototype.resume = function () { this.state = "running"; window.__audio.resumed++; return Promise.resolve(); };' +
  ' Ctx.prototype.suspend = function () { this.state = "suspended"; window.__audio.suspended++; return Promise.resolve(); };' +
  ' Ctx.prototype.close = function () { return Promise.resolve(); };' +
  ' function node(extra) { var o = { connect: function () {}, disconnect: function () {} }; for (var k in extra) o[k] = extra[k]; return o; }' +
  ' Ctx.prototype.createGain = function () { window.__audio.gain++; return node({ gain: { value: 0.5 } }); };' +
  ' Ctx.prototype.createOscillator = function () { window.__audio.osc++; return node({ type: "", frequency: { value: 0 }, start: function () { window.__audio.started++; }, stop: function () {} }); };' +
  ' Ctx.prototype.createBiquadFilter = function () { window.__audio.filter++; return node({ type: "", frequency: { value: 0 } }); };' +
  ' window.AudioContext = Ctx; window.webkitAudioContext = Ctx;' +
  ' window.__bgmErrors = 0;' +
  ' return 1; })()';

// 让播放器认为 6 条音轨全部加载失败（真实环境里就是全部 404）
const FAIL_ALL = '(function(){' +
  ' var p = window.bgMusicPlayer;' +
  ' if (!p) return "no-player";' +
  ' for (var i = 0; i < p.playlist.length; i++) {' +
  '   p.currentIndex = i;' +
  '   p.audio.dispatchEvent(new Event("error"));' +
  '   if (p.synth) break;' +
  ' }' +
  ' return p.isSynthActive() ? "synth-on" : "synth-off"; })()';

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
  await waitFor(async () => await ev('!!window.bgMusicPlayer'), 10000, '音乐播放器实例');

  // 装桩必须在任何声音播放之前（播放器会把 AudioContext 缓存在实例上）
  const stubbed = await ev(STUB_AUDIO);
  check(stubbed === 1, '桩 AudioContext 安装成功', stubbed);

  const player = await ev('(function(){ var p = window.bgMusicPlayer; return { playlist: p.playlist.length, synth: p.isSynthActive(), hasReport: typeof p.reportAllTracksMissing === "function" }; })()');
  check(player && player.playlist >= 6, '播放列表已装载（现实里这些路径全是 404）', player);
  check(player.synth === false, '初始状态没有合成音', player.synth);

  const before = await ev('JSON.parse(JSON.stringify(window.__audio))');
  const failResult = await ev(FAIL_ALL);
  const after = await ev('JSON.parse(JSON.stringify(window.__audio))');
  check(failResult === 'synth-on', '整轮音轨 404 后自动启用合成环境音', failResult);
  check(after.osc > before.osc && after.started > before.started,
    '合成音真的创建并启动了振荡器（不是空实现）', { before: before, after: after });

  const label = await ev('(function(){ var el = document.getElementById("current-track"); return el ? el.textContent : null; })()');
  check(typeof label === 'string' && label.indexOf('内置合成环境音') >= 0, '界面写明已切换到内置合成音', label);
  const playing = await ev('window.bgMusicPlayer.isPlaying');
  check(playing === true, '播放状态为「正在播放」', playing);

  // 暂停 / 继续
  const paused = await ev('(function(){ window.bgMusicPlayer.pause(); return { playing: window.bgMusicPlayer.isPlaying, suspended: window.__audio.suspended }; })()');
  check(paused.playing === false && paused.suspended >= 1, '暂停会挂起合成音', paused);
  const resumed = await ev('(function(){ window.bgMusicPlayer.play(); return { playing: window.bgMusicPlayer.isPlaying, resumed: window.__audio.resumed }; })()');
  check(resumed.playing === true && resumed.resumed >= 1, '继续播放会恢复合成音', resumed);

  // 音量 / 静音作用到合成音输出增益
  const gainState = await ev('(function(){ var p = window.bgMusicPlayer; p.setVolume(1);' +
    ' var loud = p.synth.master.gain.value;' +
    ' p.toggleMute(); var muted = p.synth.master.gain.value;' +
    ' p.toggleMute(); var back = p.synth.master.gain.value;' +
    ' p.setVolume(0.5);' +
    ' return { loud: loud, muted: muted, back: back }; })()');
  check(gainState.loud > 0 && gainState.muted === 0 && gainState.back > 0,
    '音量与静音会作用到合成音（静音时增益为 0）', gainState);

  // 上/下一首在合成音模式下不应把 404 循环重新拉起来
  const nav = await ev('(function(){ var p = window.bgMusicPlayer;' +
    ' var turns = 0; var orig = p.playTrack; p.playTrack = function () { turns++; };' +
    ' p.playNext(); p.playPrevious(); p.playTrack = orig;' +
    ' return { turns: turns, synth: p.isSynthActive() }; })()');
  check(nav.turns === 0 && nav.synth === true, '合成音模式下上/下一首不会重新触发 404 音轨', nav);

  // 状态自省
  const status = await ev('window.bgMusicPlayer.getStatus()');
  check(status && status.synthFallback === true, 'getStatus() 暴露 synthFallback 便于排查', status && status.synthFallback);

  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  console.log(NL + (problems.length ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL) : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
