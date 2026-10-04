#!/usr/bin/env node
/** 主题预设收口检查：设置页只展示竞技场，旧值也不能重新激活旧主题。 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const APP = process.argv[process.argv.indexOf('--url') + 1] || 'http://127.0.0.1:5075/';
const PORT = 9472;
const PROFILE = `C:/Windows/Temp/theme_preset_check_${process.pid}`;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
if (!EDGE) { console.log('skip: 没找到 Edge/Chrome'); process.exit(0); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let pass = 0; let fail = 0;
const check = (label, value, detail) => {
  if (value) { pass++; console.log(`PASS  ${label}${detail === undefined ? '' : ` -> ${JSON.stringify(detail)}`}`); }
  else { fail++; console.log(`FAIL  ${label} -> ${JSON.stringify(detail)}`); }
};
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--window-size=1440,900', APP], { stdio: 'ignore' });
let ws;
try {
  await sleep(3000);
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const page = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || ''));
  if (!page) { console.log('skip: 没有可用页面'); process.exitCode = 0; }
  else {
    ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
    let id = 0; const pending = new Map();
    ws.onmessage = (m) => { const x = JSON.parse(m.data); if (!x.id || !pending.has(x.id)) return; const p = pending.get(x.id); pending.delete(x.id); x.error ? p.reject(new Error(JSON.stringify(x.error))) : p.resolve(x.result); };
    const send = (method, params = {}) => new Promise((resolve, reject) => { const n = ++id; pending.set(n, { resolve, reject }); ws.send(JSON.stringify({ id: n, method, params })); setTimeout(() => { if (pending.has(n)) { pending.delete(n); reject(new Error('timeout')); } }, 20000); });
    const ev = async (expression) => { const x = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }); if (x.exceptionDetails) throw new Error(JSON.stringify(x.exceptionDetails)); return x.result?.value; };
    await send('Runtime.enable');
    await ev(`(function(){try{localStorage.removeItem('battleship_theme_preset');localStorage.removeItem('battleship_primary_color')}catch(e){};return true})()`);
    await sleep(300);
    const structure = await ev(`(function(){var g=document.getElementById('theme-preset-grid');return {cards:g?[...g.querySelectorAll('.theme-card[data-preset]')].map(function(e){return {preset:e.dataset.preset,text:e.textContent.trim()}}):[],groups:g?[...g.querySelectorAll(':scope > .theme-group')].map(function(e){return e.dataset.group}):[]}})()`);
    check('设置页存在主题预设区', structure.cards.length > 0, structure);
    check('主题预设只展示竞技场', structure.cards.length === 1 && structure.cards[0].preset === 'arena', structure.cards);
    check('主题预设只有竞技场分组', structure.groups.length === 1 && structure.groups[0] === 'arena', structure.groups);
    const oldNames = ['fluent', 'classic', 'deep', 'lava', 'cyber', 'dusk', 'aurora'];
    for (const name of oldNames) {
      const result = await ev(`(function(){var r=applyThemePreset(${JSON.stringify(name)});return {r:r,preset:document.documentElement.dataset.themePreset,stored:localStorage.getItem('battleship_theme_preset')}})()`);
      check(`旧预设 ${name} 会回退到竞技场`, result.r === 'arena' && result.preset === 'arena' && result.stored === 'arena', result);
    }
    const custom = await ev(`(function(){var r=applyCustomPrimaryColor('#123456');return {r:r,preset:document.documentElement.dataset.themePreset,stored:localStorage.getItem('battleship_theme_preset')}})()`);
    check('主色微调仍可单独使用自定义模式', custom.preset === 'custom' && custom.stored === 'custom', custom);
  }
} catch (e) { console.error('fatal:', e.stack || e); fail++; }
finally { try { if (ws) ws.close(); } catch {} try { browser.kill(); } catch {} try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {} }
console.log(`\n结果：PASS ${pass} / FAIL ${fail}`);
process.exitCode = fail ? 1 : 0;
