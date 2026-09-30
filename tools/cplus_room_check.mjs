#!/usr/bin/env node
/**
 * C+ 好友房 · **席位与规则摘要**的定向检查（W3）
 *
 * 覆盖 2026-09-29 新加的：两格席位（自己 / 对手）、真实房号、四条规则摘要，
 * 以及任务书 §W3 点名的那条边界 ——
 *   **"双方名称和状态只从真实房间数据取；缺字段显示等待，不伪造第二人"**。
 *
 * 这条边界是本工具存在的理由：席位面板最容易写坏的地方就是"没对手也画一个人"，
 * 而那种缺陷在截图里**看着完全正常**（一个名字、一个"已加入"标签）。
 * 所以这里专门构造"只有自己"的载荷，断言对手那一格必须是**等待态**。
 *
 * 做法与 cplus_deploy_check 同一手法：直接驱动渲染函数 + 置 gameState，
 * 不伪造业务字段、不碰产品代码。真实两客户端进房那条路已由
 * friend_invite_battle_check / room_invite_check 覆盖（本工具不重复它）。
 *
 * 用法：node tools/cplus_room_check.mjs --url http://127.0.0.1:5097/ [--shots <dir>]
 * 退出码：0 全过；1 有 FAIL；2 SKIP（没有浏览器）。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..');
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = Number(argOf('--port', '9379'));
const SHOTS = argOf('--shots', '');
const KNOWN_BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const EDGE = KNOWN_BROWSERS.find((p) => fs.existsSync(p));
const PROFILE = argOf('--profile', path.join(REPO, '.tmp', 'cplus-room', 'profile'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

if (!EDGE) {
  console.log('SKIP  没有找到可用的 Edge/Chrome —— 这**不是**通过，是未验收。');
  process.exit(2);
}
fs.mkdirSync(PROFILE, { recursive: true });
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

const HARNESS = `(function(){
  if (window.__roomHarness) return window.__roomHarness;
  var H = {};
  /* 把房间面板摆到"已建好房、正在等"这一态。roomId 与名字都从参数来 ——
     不读服务端，因为本工具验的是**渲染**对真实字段的忠实度。 */
  H.show = function(roomId, meName, oppName, seat){
    document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
    document.querySelectorAll('.modal-overlay').forEach(function(m){ m.classList.add('hidden'); });
    document.getElementById('custom-room-screen').classList.add('active');
    document.getElementById('custom-current-room-id').textContent = roomId || '';
    gameState.roomId = roomId || null;
    gameState.playerName = meName || '';
    gameState.opponentName = (oppName === undefined ? '对手' : oppName);   // '对手' = gameState 的默认值
    gameState.playerSeat = seat || 'p1';
    document.getElementById('custom-room-info').classList.remove('hidden');
    if (typeof renderCustomRoomSeats === 'function') renderCustomRoomSeats();
    if (typeof renderCustomRoomRules === 'function') renderCustomRoomRules();
    return H.snap();
  };
  H.refresh = function(){ if (typeof refreshCustomRoomInfo === 'function') refreshCustomRoomInfo(); return H.snap(); };
  H.snap = function(){
    var seats = [].slice.call(document.querySelectorAll('#custom-room-seats .room-seat'));
    var rules = [].slice.call(document.querySelectorAll('#custom-room-rules .room-rule'));
    return {
      seats: seats.map(function(li){
        return { label: (li.querySelector('.room-seat-label') || {}).textContent || '',
                 name: (li.querySelector('.room-seat-name') || {}).textContent || '',
                 tag: (li.querySelector('.room-seat-tag') || {}).textContent || '',
                 on: li.classList.contains('on') };
      }),
      rules: rules.map(function(d){
        return ((d.querySelector('dt') || {}).textContent || '') + '=' + ((d.querySelector('dd') || {}).textContent || '');
      }),
      roomId: (document.getElementById('custom-current-room-id') || {}).textContent || '',
      infoHidden: document.getElementById('custom-room-info').classList.contains('hidden'),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      worst: (function(){
        var w = 0, el = null;
        document.querySelectorAll('#custom-room-screen *').forEach(function(e){
          if (!e.clientWidth) return;
          var ox = getComputedStyle(e).overflowX;
          if (ox === 'auto' || ox === 'scroll') return;
          var d = e.scrollWidth - e.clientWidth;
          if (d > w) { w = d; el = e.className || e.tagName; }
        });
        return { delta: w, el: String(el).slice(0, 60) };
      })(),
    };
  };
  window.__roomHarness = H;
  return H;
})()`;

console.log('== C+ 好友房 · 席位与规则定向检查（W3）==');
console.log('   目标 ' + APP);

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
  '--user-data-dir=' + PROFILE, 'about:blank'], { stdio: 'ignore' });

let ws = null;
let exitCode = 0;
try {
  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还没起来 */ }
    await sleep(500);
  }
  if (!target) { console.error('无法连接无头浏览器调试端口 ' + PORT); process.exit(3); }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  let seq = 0;
  const pending = new Map();
  const jsProblems = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const id = ++seq; pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
  });
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 400) };
    return r.result && r.result.value;
  };
  await send('Page.enable');
  await send('Runtime.enable');

  for (const [vlabel, w, h] of [['1440x900', 1440, 900], ['390x844', 390, 844]]) {
    console.log('');
    console.log('-- 视口 ' + vlabel + ' --');
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
    await send('Page.navigate', { url: APP });
    for (let i = 0; i < 60; i++) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break; await sleep(300); }
    await sleep(500);
    await ev(HARNESS);

    // ① 只有自己：对手那一格必须是等待态（**不许伪造第二个人**）
    const alone = await ev('(function(){ return window.__roomHarness.show("a7c2e1", "老船长"); })()');
    check(alone && alone.seats.length === 2, '[' + vlabel + '] 席位是两格', alone && alone.seats);
    check(alone && alone.seats[0] && alone.seats[0].name === '老船长' && alone.seats[0].on === true,
      '[' + vlabel + '] 席位 1 是自己（名字来自 gameState.playerName）', alone && alone.seats[0]);
    check(alone && alone.seats[1] && alone.seats[1].on === false && /等待加入/.test(alone.seats[1].name),
      '[' + vlabel + '] **没人进来时席位 2 是等待态**（不伪造第二个人）', alone && alone.seats[1]);
    check(alone && alone.roomId === 'a7c2e1', '[' + vlabel + '] 房号就是真实房号', alone && alone.roomId);

    // ② 对手进房：席位 2 变成已加入，名字是服务端给的那个
    const paired = await ev('(function(){ return window.__roomHarness.show("a7c2e1", "老船长", "新水手"); })()');
    check(paired && paired.seats[1] && paired.seats[1].on === true && paired.seats[1].name === '新水手',
      '[' + vlabel + '] 对手进来后席位 2 显示真实名字且是"已加入"', paired && paired.seats[1]);
    const joiner = await ev('(function(){ return window.__roomHarness.show("a7c2e1", "新水手", "老船长", "p2"); })()');
    check(joiner && joiner.seats[0].name === '老船长' && joiner.seats[0].tag === '房主'
      && joiner.seats[1].name === '新水手' && joiner.seats[1].tag === '已加入',
      '[' + vlabel + '] 加入者视角房主标签留在席位 1', joiner && joiner.seats);

    // ③ `opponentName` 还是默认字面量 '对手' 时**不算有人**（这是最容易漏的一档）
    const defaulted = await ev('(function(){ return window.__roomHarness.show("a7c2e1", "老船长"); })()');
    check(defaulted && defaulted.seats[1] && defaulted.seats[1].on === false,
      '[' + vlabel + '] opponentName 仍是默认值「对手」时按"没人"处理（不把默认值当玩家）',
      defaulted && defaulted.seats[1]);

    // ④ 规则摘要：四条都在，且"每人战舰"与页面上的 #total-ships 同源
    check(paired && paired.rules.length === 4, '[' + vlabel + '] 规则摘要四条都在', paired && paired.rules);
    check(paired && paired.rules.some((r) => /每人战舰=6/.test(r)),
      '[' + vlabel + '] 「每人战舰」的 6 来自 #total-ships（同一份数据，不写死第二份）',
      paired && paired.rules);
    check(paired && paired.rules.some((r) => /模式=休闲/.test(r)),
      '[' + vlabel + '] 规则里写明自定义房是休闲局（不计排位）', paired && paired.rules);

    // ⑤ 刷新路径（game_state 到达时走的那条）也要更新席位
    const afterRefresh = await ev(`(function(){
      var H = window.__roomHarness;
      H.show('a7c2e1', '老船长');           // 先回到"只有自己"
      gameState.opponentName = '后来的水手';  // 模拟服务端 game_state 带上了 opponent_name
      return H.refresh();
    })()`);
    check(afterRefresh && afterRefresh.seats[1] && afterRefresh.seats[1].name === '后来的水手'
      && afterRefresh.seats[1].on === true,
      '[' + vlabel + '] game_state 到达后刷新（refreshCustomRoomInfo）也会更新席位',
      afterRefresh && afterRefresh.seats[1]);

    // ⑥ 窄屏也不溢出（两格席位 + 四条规则在手机要能排下）
    const back = await ev('(function(){ return window.__roomHarness.show("a7c2e1", "老船长", "新水手"); })()');
    check(back && back.overflow <= 1 && back.worst.delta <= 1,
      '[' + vlabel + '] 好友房（含席位与规则）无横向溢出', back && { page: back.overflow, worst: back.worst });

    if (SHOTS) {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(SHOTS, 'room-' + vlabel + '.png'), Buffer.from(shot.data, 'base64'));
    }
  }

  check(jsProblems.length === 0, '全程零 JS 异常', jsProblems.slice(0, 4));
  console.log('');
  if (problems.length) {
    console.log('✗ ' + problems.length + ' 项未通过：');
    problems.slice(0, 30).forEach((p) => console.log('   · ' + p));
    exitCode = 1;
  } else {
    console.log('✓ 全部通过');
  }
} finally {
  try { if (ws) ws.close(); } catch (e) { /* 已断 */ }
  try { browser.kill(); } catch (e) { /* 已经退了 */ }
}
process.exit(exitCode);
