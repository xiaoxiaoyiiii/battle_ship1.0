#!/usr/bin/env node
/**
 * 绝处逢生生效期间的出牌提示回归检查（无头 Edge + CDP）
 *
 * 覆盖的问题：绝处逢生生效后，玩家出牌被拒时看到的提示与真实原因无关 ——
 * 前端 `canPlayCard` 只判阶段/回合，不认识 `last_stand`，于是速阶1/2 的卡
 * 一路掉进兜底分支，弹出「当前阶段battle不允许使用速阶1的魔法卡」。
 * 阶段明明是对的，玩家据此以为游戏坏了。
 *
 * 修法：
 *   · game.js 新增 isLastStandActive()（兼容服务端两种下发口径），
 *     canPlayCard 最前面拦掉，playMagicCard 弹出点名绝处逢生的提示；
 *   · 连锁响应窗口在绝处逢生前不再弹出，直接替玩家放弃并说明原因；
 *   · 服务端 handle_use_magic_card 补上绝处逢生的专属理由（别再甩锅给阶段）。
 *
 * 本脚本在真实页面上驱动真实函数，读页内 toast 的实际文案逐项断言。
 *
 * 用法：
 *   node tools/last_stand_message_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

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
const PROFILE = 'C:/Windows/Temp/last_stand_msg_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过绝处逢生提示检查'); process.exit(0); }

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

// 清空并读取页内 toast 的实际文案（showMessage 渲染成 #game-message-container 下的 .game-message）
async function drainToasts() {
  return await ev(`(function(){
    var box = document.getElementById('game-message-container');
    if (!box) return [];
    var texts = Array.prototype.map.call(box.querySelectorAll('.game-message'), function(el){
      return (el.textContent || '').trim();
    }).filter(Boolean);
    box.innerHTML = '';
    return texts;
  })()`);
}

async function main() {
  browser = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + PROFILE, APP,
  ], { stdio: 'ignore' });

  await sleep(2500);
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const page = list.find((t) => t.type === 'page');
  if (!page) throw new Error('找不到页面目标');

  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      const { res, rej } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
    }
  };
  await send('Runtime.enable');

  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  await waitFor(async () => await ev('typeof canPlayCard === "function" && typeof isLastStandActive === "function"'), 20000, 'game.js 就绪');
  // ---- 1. 判定函数本身：三种口径都要认 ----
  check(await ev('typeof isLastStandActive === "function"'), 'isLastStandActive 已定义');

  const cases = [
    [[], false, '空数组'],
    [['百亿补贴'], false, '无关效果'],
    [['绝处逢生'], true, 'active_effects 的中文标签'],
    [['last_stand'], true, 'room_sync 的键名'],
    [['last_stand_cells'], true, 'room_sync 的带后缀键名'],
    [['百亿补贴', '绝处逢生'], true, '混在其它效果里'],
  ];
  for (const [effects, want, label] of cases) {
    const got = await ev(`(function(){
      gameState.activeEffects = ${JSON.stringify(effects)};
      return isLastStandActive();
    })()`);
    check(got === want, `isLastStandActive：${label}`, { want, got });
  }

  // ---- 2. canPlayCard 在绝处逢生生效时必须一律 false ----
  const blocked = await ev(`(function(){
    gameState.activeEffects = ['绝处逢生'];
    gameState.currentAttacker = gameState.playerId || 'me';
    gameState.currentPhase = 'battle';
    var out = {};
    [1,2,3].forEach(function(sp){
      out['speed'+sp] = canPlayCard({name:'测试卡', speed: sp, type:'普通'});
    });
    return out;
  })()`);
  check(blocked.speed1 === false && blocked.speed2 === false && blocked.speed3 === false,
    '绝处逢生生效时，三个速阶都不可出牌', blocked);

  // ---- 3. playMagicCard 的提示必须点名绝处逢生 ----
  const msg = await ev(`(function(){
    gameState.activeEffects = ['绝处逢生'];
    gameState.currentAttacker = gameState.playerId || 'me';
    gameState.currentPhase = 'battle';
    gameState.hand = [{name:'增援', speed:1, type:'普通'}];
    playMagicCard(0);
    return true;
  })()`);
  await sleep(300);
  const toasts = await drainToasts();
  const joined = toasts.join(' | ');
  check(/绝处逢生/.test(joined), '提示里点名了绝处逢生', joined);
  check(!/当前阶段/.test(joined), '提示不再甩锅给「当前阶段」', joined);

  // ---- 4. 速阶3 也一样（它平时不受阶段限制，最容易漏判）----
  await ev(`(function(){
    gameState.activeEffects = ['绝处逢生'];
    gameState.currentPhase = 'battle';
    gameState.hand = [{name:'八方来财', speed:3, type:'普通'}];
    playMagicCard(0);
    return true;
  })()`);
  await sleep(300);
  const toasts3 = await drainToasts();
  const joined3 = toasts3.join(' | ');
  check(/绝处逢生/.test(joined3), '速阶3 也被拦且提示正确', joined3);

  // ---- 5. 反证：没有绝处逢生时，提示照旧（别把正常路径改坏）----
  await ev(`(function(){
    gameState.activeEffects = [];
    gameState.currentAttacker = 'someone-else';
    gameState.currentPhase = 'battle';
    gameState.playerId = 'me';
    gameState.hand = [{name:'增援', speed:1, type:'普通'}];
    playMagicCard(0);
    return true;
  })()`);
  await sleep(300);
  const normal = (await drainToasts()).join(' | ');
  check(/不是你的回合/.test(normal), '无绝处逢生时仍报「不是你的回合」', normal);
  check(!/绝处逢生/.test(normal), '无绝处逢生时不该出现绝处逢生文案', normal);

  // ---- 6. 连锁窗口：绝处逢生生效时不弹窗，直接放弃 ----
  // showChainRequestPrompt 是 setupSocketListeners 内部的闭包，不暴露到全局，
  // 因此走真实路径：用页面上已注册的 socket 监听器触发 chain_request。
  const hasListener = await ev(`(function(){
    var s = gameState.socket;
    if (!s || !s._callbacks) return false;
    return !!s._callbacks['$chain_request'];
  })()`);

  if (!hasListener) {
    check(false, '连锁窗口检查', '页面上没有 chain_request 监听器（socket 未就绪）');
  } else {
    const emitted = await ev(`(function(){
      gameState.activeEffects = ['绝处逢生'];
      var fired = [];
      var s = gameState.socket;
      var realEmit = s.emit;
      s.emit = function(name, payload){ fired.push({name:name, payload:payload}); return realEmit.apply(s, arguments); };
      try {
        s._callbacks['$chain_request'].forEach(function(cb){
          cb({ card: {name:'轰炸', speed:3}, caster: 'opp', speed3_cards: [{name:'失灵！', speed:3}], countdown: 10 });
        });
      } finally { s.emit = realEmit; }
      window.__chainProbe = fired;
      return true;
    })()`);

    await sleep(400);
    const fired = await ev('window.__chainProbe || []');
    const gaveUp = fired.some((e) => e.name === 'chain_response' && e.payload && e.payload.chain === false);
    check(gaveUp, '绝处逢生生效时连锁窗口直接放弃（不弹窗）', fired);
    const promptShown = await ev('document.querySelectorAll(".magic-prompt").length');
    check(promptShown === 0, '不该弹出连锁响应窗口', { promptShown });
    const chainToast = (await drainToasts()).join(' | ');
    check(/绝处逢生/.test(chainToast), '放弃时给出了原因', chainToast);
  }

  console.log('');
  if (problems.length) {
    console.log(`✗ ${problems.length} 项未通过：`);
    problems.forEach((p) => console.log('   · ' + p));
  } else {
    console.log('✓ 全部通过');
  }
  try { ws.close(); } catch (e) {}
  if (browser) browser.kill();
  process.exit(problems.length ? 1 : 0);
}

main().catch((e) => {
  console.error('检查脚本异常：', e.message);
  try { ws && ws.close(); } catch (x) {}
  try { browser && browser.kill(); } catch (x) {}
  process.exit(1);
});
