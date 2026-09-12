#!/usr/bin/env node
/**
 * 多级连锁「无效化」提示的前端回归检查（无头 Edge + CDP）
 *
 * 覆盖：chain_resolved 里两种 success=false 必须给出不同文案 ——
 *   · negated_skip=true  → 【X】被Y无效化了（这张牌是被别人康掉的）
 *   · negated_skip 缺失  → X未能生效：…（这张牌自己发动失败）
 * 旧实现两者共用同一句「X未能生效：X被无效化」，实测让玩家
 * 误判成"加百列没康住失灵"。
 *
 * 用法：node tools/chain_negation_message_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9361;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!EDGE) { console.error('找不到 Edge/Chrome，跳过检查'); process.exit(0); }

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=' + PORT,
  '--user-data-dir=C:/Windows/Temp/chain_negation_profile', APP], { stdio: 'ignore' });

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

await sleep(2800);
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.url.startsWith('http')) ||
             list.find((t) => t.type === 'page');
if (!page) { console.error('找不到页面目标'); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });

let seq = 0; const pending = new Map();
ws.onmessage = (m) => {
  const x = JSON.parse(m.data);
  if (x.id && pending.has(x.id)) {
    const { res, rej } = pending.get(x.id); pending.delete(x.id);
    x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result);
  }
};
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq; pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method, params }));
  setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
});
await send('Runtime.enable');
const ev = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 200));
  return r.result && r.result.value;
};

const t0 = Date.now();
while (Date.now() - t0 < 20000) {
  if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break;
  await sleep(200);
}

async function drainToasts() {
  return await ev(`(function(){
    var box = document.getElementById('game-message-container');
    if (!box) return [];
    var t = Array.prototype.map.call(box.querySelectorAll('.game-message'), function(el){ return (el.textContent||'').trim(); }).filter(Boolean);
    box.innerHTML = '';
    return t;
  })()`);
}

async function fireChainResolved(results) {
  return await ev(`(function(){
    var s = gameState.socket;
    if (!s || !s._callbacks || !s._callbacks['$chain_resolved']) return 'no-listener';
    s._callbacks['$chain_resolved'].forEach(function(cb){ cb({ results: ${JSON.stringify(results)} }); });
    return 'ok';
  })()`);
}

// ---- 1. 被康：应说「被X无效化」 ----
let r = await fireChainResolved([
  { card: { name: '加百列之光', speed: 3, type: '普通' }, caster: 'me', success: true, message: '成功无效化1个效果' },
  { card: { name: '失灵！', speed: 3, type: '普通' }, caster: 'opp', success: false,
    message: '失灵！被加百列之光无效化', negated_skip: true, negated_by: '加百列之光' },
]);
check(r === 'ok', '页面注册了 chain_resolved 监听', r);
await sleep(350);
let toasts = (await drainToasts()).join(' | ');
check(/被加百列之光无效化/.test(toasts), '被康的牌提示「被X无效化」', toasts);
check(!/未能生效/.test(toasts), '被康时不再误用「未能生效」措辞', toasts);

// ---- 2. 自己发动失败：仍用「未能生效」 ----
await fireChainResolved([
  { card: { name: '失灵！', speed: 3, type: '普通' }, caster: 'me', success: false,
    message: '加百列之光免疫失灵！' },
]);
await sleep(350);
toasts = (await drainToasts()).join(' | ');
check(/未能生效/.test(toasts), '发动失败仍提示「未能生效」', toasts);
check(!/被.*无效化/.test(toasts), '发动失败不该被说成"被无效化"', toasts);

// ---- 3. 没带 negated_by 时的兜底措辞 ----
await fireChainResolved([
  { card: { name: '轰炸', speed: 3, type: '普通' }, caster: 'opp', success: false,
    message: '轰炸被无效化', negated_skip: true },
]);
await sleep(350);
toasts = (await drainToasts()).join(' | ');
check(/被.*无效化/.test(toasts), '缺 negated_by 时也有兜底措辞', toasts);

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
