#!/usr/bin/env node
/**
 * 「好友一键邀战 → 真的开一局」双浏览器端到端检查 / 复现工具（2026-09-19）
 *
 * ===========================================================================
 * 为什么必须**两个真浏览器**
 * ---------------------------------------------------------------------------
 * 线上自动化原来只做到"一个浏览器 + 一个 python 侧 socket 陪练"，而 python 侧
 * **从不走布船界面**（它直接 emit `place_ships`）。于是这条链的真实现象 ——
 * 「邀战之后两边各自看到什么界面、在哪个房间、对手名是谁」—— **一格都没被覆盖**，
 * 结果真机上出了"根本无法启动对局 / 一方进不了布船界面 / 另一方卡死在错误的布船界面"
 * 而所有工具全绿。本工具用两个独立 CDP 端口 + 两个独立 persistent profile 的无头 Edge
 * 模拟两个真人，**全程走真实 UI**（点好友面板的「邀战」、点提示条的「进入房间」、
 * 点棋盘格子、点「确认放置」「解散房间」），把每一刻两边的页面状态记成时间线。
 *
 * 两种模式（同一套断言，两种模式的"预期"不同）：
 *   --mode prefixed    复现"坏的样子"（把 `static/game.js` / `api.py` 的修复 stash 掉那一轮）
 *   --mode postfixed   验证"修好之后的样子"（默认）
 * 两种模式记的字段完全一样，可以直接 diff 两份 capture-*.json。
 *
 * ===========================================================================
 * prefixed（修复前）实测到的坏样子
 * ---------------------------------------------------------------------------
 *  · A 点「邀战」→ **A 的页面一点变化都没有**：`gameState.roomId == null`、
 *    地址栏没有 `?room=`、`activeScreens == ["start-screen"]`；
 *    唯一反馈是好友面板底部一行"已邀请 B（房间 X）"+ 一条会自动消失的 showMessage。
 *    → 对应"根本无法启动对局"。
 *  · B 点「进入房间」→ join_room ack `success`，前端无条件
 *    `switchScreen(shipPlacementScreen)` → B 停在**一块 0 格的空棋盘**上
 *    （`#ship-placement-screen` active、`#player-board .cell` = 0）。
 *    服务端房里只有 B **一个人**，`room.state` 还是 `'waiting'`
 *    （`handle_join_room` 只在**满 2 人**时才推 `placing_ships`）→ 永远不下发
 *    `game_state` → 那 36 个格子**永远不会建出来**。
 *    → 对应"另一方卡死在错误的布船界面"。
 *  · 房间 X 里最终只有 **1 个人**：再连一条干净的 python socket 去 `join_room`
 *    能直接坐进去（ack success）= 铁证。
 *
 * ===========================================================================
 * 用法
 * ---------------------------------------------------------------------------
 *   node tools/friend_invite_battle_check.mjs --url http://127.0.0.1:5111/
 *        [--mode prefixed|postfixed] [--json .tmp/invite_capture.json]
 *
 * ⚠️ 需要一个**已经起好的**服务端，且 `CORS_ORIGINS` 必须放行这个端口
 *    （否则 socket.io **静默连不上**：页面零报错，后面全是假红）。
 * ⚠️ 只在**隔离库**的本地服务上跑：它会注册 7~8 个账号、真的建房、真的写好友关系。
 * ⚠️ 本工具**不改任何产品代码**：只写 tools/ 下这一个文件 + .tmp/ 下的东西。
 *
 * ===========================================================================
 * 踩过的坑（都在这份工具里踩过，别再踩）
 * ---------------------------------------------------------------------------
 * 1. **两个浏览器必须各有 `--user-data-dir` 与 `--remote-debugging-port`**：共用一个 profile 时
 *    第二个实例**静默起不来**，工具会连上第一个 → "两个玩家"其实是同一个人（全程假绿）。
 * 2. **按 profile 路径预清理残留 msedge**：`proc.kill()` 只杀直接子进程，Edge 会留下一串孙进程
 *    继续占着调试端口 + 锁着 profile；不清的话下一轮连上的是**上一轮的旧实例**。
 * 3. **入房 ack 那一刻 `#player-board .cell` 还是 0 个**：格子是 `game_state(state='placing_ships')`
 *    到达后、再走完 **5 秒**"匹配成功"倒计时由 `initBoard(playerBoard, true)` 建的。
 *    取样太早会把"格子还没建"读成"卡死了"（工具自己的假红）。必须 `waitFor(36)`。
 * 4. **服务端 `print` 基本不落盘**：socket 事件里几乎没有 `print`，所以"服务端日志对应的行"
 *    这一项**只能靠服务端可观察手段**取证 —— 再连一条干净 socket 去 `join_room` 看 ack
 *    （`success` = 房里原本只有 1 人；`房间已满` = 已有 2 人；`房间不存在` = 房没了）。
 * 5. **`join_room` 探房有副作用**：坐进去会把房推到 2/2 并给房里两个座位发 `game_state`。
 *    所以"探房"必须**放在浏览器侧取证做完之后**，而且探完要把探针杀掉。
 * 6. **`close_room` 的三条校验里有"房内恰好 1 人"**（`server.py` 的 `handle_close_room`）：
 *    先探房再点「解散房间」= 房里有 2 人 → 服务端**正确**回「只能解散自己创建的房间」，
 *    而工具会把它误读成"解散坏了"。**必须先让探针走干净，再点解散。**
 * 7. **同一个登录身份从两条连接 join 同一间房会覆盖自己那个 key**：容量判据是
 *    `len(room.players)`（dict，key = `session['user_id']`）而不是连接数 →
 *    同一个 key 被覆盖、长度永远到不了 2 → 那间房**永远开不了局**。
 *    所以"第三个人插满房"这条边界必须用**三个不同身份**才测得出来。
 * 8. **浏览器换登录身份必须先把 cookie 清掉**：只 `Network.setCookie` 的话，
 *    同一个 host 上已有的 session cookie 还在，页面照样是原来那个人。
 * 9. **`login`/`register` 有 IP 限流（各 10 次/60 秒，见 api.py `_rate_limited`）**：
 *    本工具一次要开 7~8 个号，跑到中段必然撞上 → 表现为 `{'error':'未登录'}` 满屏红。
 *    这是**工具自己**的问题，不是产品缺陷：`authCookie` 里要退避等待重试。
 * 10. **`register` 之后必须用 `window.__USERNAME` 判"这个会话到底是谁"**：
 *     `api/profile` 在很多分支里都能返回 200 但没有 `profile` 字段。
 * 11. **`static/game.js` 可能被别的智能体并行编辑**：跑之前/之后各打一次 sha256，
 *     变了就说明"读到的可能是半截文件"，隔一分钟重跑。
 * 12. **好友面板是 fixed 浮层、点开会盖住整屏**：取样 `#custom-room-info` 之前要先把它关掉，
 *     否则读到的是"被遮罩压着的面板"（只有点遮罩空白处 / 关闭按钮才会收）。
 */

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

// ---------- 参数 ----------
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5111/').replace(/\/?$/, '/');
const MODE = argOf('--mode', 'postfixed');
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const ROOT = path.resolve(HERE, '..');
const TMP = path.join(ROOT, '.tmp');
const JSON_OUT = argOf('--json', path.join(TMP, 'invite_capture_' + MODE + '.json'));
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// ⚠️ CDP 端口：9361/9362/9363 是别的工具的，绝不能碰（撞端口 = 连上别人的浏览器，全线假绿）
const PORT_A = 9371;
const PORT_B = 9372;
const PROFILE_A = path.join(TMP, 'invite_repro_a_profile');
const PROFILE_B = path.join(TMP, 'invite_repro_b_profile');

fs.mkdirSync(TMP, { recursive: true });
if (!BROWSER) { console.error('找不到 Edge/Chrome'); process.exit(0); }

// ---------- 预清理（按 profile 路径扫，`browser.kill()` 杀不干净 msedge） ----------
function preClean(profileTag) {
  try {
    spawnSync('powershell', ['-NoProfile', '-Command',
      'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
      'Where-Object { $_.CommandLine -like \'*' + profileTag + '*\' } | ' +
      'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'],
      { stdio: 'ignore', timeout: 25000 });
  } catch (e) { /* 没有残留就够了 */ }
}
preClean('invite_repro_a_profile');
preClean('invite_repro_b_profile');

// ---------- 断言账本 + 时间线 ----------
const passes = [];
const failures = [];
const jsProblems = [];
const timeline = [];
const t0 = Date.now();
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (ok) passes.push(label); else failures.push({ label: label, detail: detail === undefined ? null : detail });
}
function stamp() { return '+' + ((Date.now() - t0) / 1000).toFixed(2) + 's'; }
function step(label, extra) {
  const entry = Object.assign({ t: stamp(), label: label }, extra || {});
  timeline.push(entry);
  console.log('');
  console.log('== [' + entry.t + '] ' + label);
  if (extra && extra.A) console.log('   A: ' + JSON.stringify(extra.A));
  if (extra && extra.B) console.log('   B: ' + JSON.stringify(extra.B));
  if (extra && extra.server) console.log('   srv: ' + JSON.stringify(extra.server));
  return entry;
}
function fingerprint(p) {
  try {
    const buf = fs.readFileSync(p);
    return { sha256: crypto.createHash('sha256').update(buf).digest('hex').slice(0, 16),
      bytes: buf.length, mtime: fs.statSync(p).mtime.toISOString() };
  } catch (e) { return { error: String(e && e.message) }; }
}

// ---------- 账号 ----------
const SUFFIX = String(Date.now()).slice(-6);
const PW = 'invitechk123456';
const UA = 'invchk_a' + SUFFIX;
const UB = 'invchk_b' + SUFFIX;
const UP = 'invchk_p' + SUFFIX;       // 探针 1（探主房间的座位数）
const UP2 = 'invchk_q' + SUFFIX;      // 探针 2（边界：独立房间里坐第二个座位）
const UP3 = 'invchk_r' + SUFFIX;      // 探针 3（边界：**另一个身份**的第三个人）
const UA3 = 'invchk_a3' + SUFFIX;     // 场景③（发起方空等 + 干净退出）
const UB3 = 'invchk_b3' + SUFFIX;

function readCookie(resp) {
  const raw = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [resp.headers.get('set-cookie')].filter(Boolean);
  const pairs = raw.map((c) => String(c).split(';')[0]).filter(Boolean);
  return pairs.length ? pairs.join('; ') : '';
}

// 真注册真登录（走 Node 侧 HTTP，与浏览器同一条路）。
// ⚠️ 登录失败**也会种 session cookie**（响应里带的是错误 flash），所以"拿到 cookie"≠"登录成功"；
//    最终判据用**页面上的 window.__USERNAME**（服务端渲染，最能代表"这个会话真的是谁"）。
async function authCookie(username) {
  const post = (p) => fetch(APP + p, {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: username, password: PW }).toString()
  });
  const pageUser = (cookie) => fetch(APP, { headers: cookie ? { Cookie: cookie } : {} })
    .then((r) => r.text())
    .then((html) => {
      const m = /window\.__USERNAME\s*=\s*("(?:[^"\\]|\\.)*")/.exec(html);
      if (!m) return '';
      try { return JSON.parse(m[1]); } catch (e) { return ''; }
    }).catch(() => '');
  const verify = async (cookie) => {
    if (!cookie) return '';
    try {
      const r = await fetch(APP + 'api/profile', { headers: { Accept: 'application/json', Cookie: cookie } });
      const body = await r.json().catch(() => null);
      if (body && body.profile && String(body.profile.username || '') === username) return cookie;
    } catch (e) { /* 用页面判据再确认一次 */ }
    return (await pageUser(cookie)) === username ? cookie : '';
  };
  const attempt = async () => {
    const c1 = await verify(readCookie(await post('login')));
    if (c1) return c1;
    await post('register');
    return verify(readCookie(await post('login')));
  };
  let cookie = await attempt();
  for (let i = 0; i < 3 && !cookie; i++) {
    console.log('   ...' + username + ' 登录未成功（多半撞上 login/register 限流 10 次/60 秒），等 65 秒重试');
    await sleep(65000);
    cookie = await attempt();
  }
  return cookie;
}
async function postJson(pathName, body, cookie) {
  const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
  if (cookie) headers['Cookie'] = cookie;
  const r = await fetch(APP + pathName, { method: 'POST', headers: headers, body: JSON.stringify(body) });
  const text = await r.text();
  let parsed = null;
  try { parsed = text ? JSON.parse(text) : null; } catch (e) { parsed = null; }
  return { status: r.status, body: parsed };
}

// ---------- 浏览器（CDP） ----------
function pickPage(list) {
  const isApp = (t) => t.type === 'page' && /^(https?|file):/.test(t.url || '');
  return list.find(isApp) || list.find((t) => t.type === 'page' && t.url !== 'about:blank'
    && !/^(edge|chrome|devtools):/.test(t.url || '')) || list.find((t) => t.type === 'page');
}

async function launch(tag, port, profileDir) {
  preClean(path.basename(profileDir));
  fs.mkdirSync(profileDir, { recursive: true });
  const proc = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + port,
    '--user-data-dir=' + profileDir, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
      target = pickPage(list);
      if (target) break;
    } catch (e) { /* 还在起 */ }
    await sleep(400);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口 ' + port);

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = () => rej(new Error('websocket 连接失败 ' + port));
  });

  let seq = 0;
  const pending = new Map();
  const consoleLogs = [];
  const socketFrames = [];   // socket.io 的上行/下行报文 + ack 帧
  const netPosts = [];       // /api/friends/* 的响应

  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') {
      jsProblems.push(tag + ' JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 240));
    }
    if (m.method === 'Runtime.consoleAPICalled') {
      const text = (m.params.args || []).map((a) => a.value !== undefined ? String(a.value)
        : (a.preview && a.preview.description) || a.description || '').join(' ').slice(0, 300);
      consoleLogs.push({ type: m.params.type, text: text, t: stamp() });
      if (m.params.type === 'error') jsProblems.push(tag + ' console.error: ' + text.slice(0, 200));
    }
    if (m.method === 'Network.responseReceived') {
      const r = m.params.response || {};
      if (/\/api\/friends\//.test(String(r.url || ''))) {
        const rec = { url: r.url, status: r.status, requestId: m.params.requestId, t: stamp() };
        netPosts.push(rec);
        send('Network.getResponseBody', { requestId: m.params.requestId }).then((b) => {
          rec.body = b && b.body ? b.body.slice(0, 800) : null;
        }).catch(() => {});
      }
    }
    if (m.method === 'Network.webSocketFrameReceived') {
      const p = String((m.params.response || {}).payloadData || '');
      // socket.io 的 ack 帧是 `43<ackId><JSON>`（**没有长度位**）—— 它是"服务端对
      // join_room / place_ships / close_room 到底回了什么"的**唯一原始证据**。
      const ackHit = /^43(\d+)([\s\S]*)$/.exec(p);
      if (ackHit) {
        let parsed = null;
        try { parsed = JSON.parse(ackHit[2]); } catch (e) { parsed = ackHit[2].slice(0, 200); }
        if (socketFrames.length < 600) socketFrames.push({ kind: 'ack', ackId: ackHit[1], body: parsed, t: stamp() });
      } else if (/game_state|friend_invite|placing_ships|room_id|close_room/.test(p) && socketFrames.length < 600) {
        socketFrames.push({ kind: 'ws-in', text: p.slice(0, 500), t: stamp() });
      }
    }
    if (m.method === 'Network.webSocketFrameSent') {
      const p = String((m.params.response || {}).payloadData || '');
      if (/join_room|place_ships|create_room|rps_choice|close_room/.test(p) && socketFrames.length < 600) {
        socketFrames.push({ kind: 'ws-out', text: p.slice(0, 400), t: stamp() });
      }
    }
  };

  function send(method, params) {
    const id = ++seq;
    ws.send(JSON.stringify({ id: id, method: method, params: params || {} }));
    return new Promise((res, rej) => {
      pending.set(id, { res: res, rej: rej });
      setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
    });
  }
  async function ev(expression) {
    const r = await send('Runtime.evaluate', { expression: expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(tag + ' 页面异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
    return r.result && r.result.value;
  }
  async function waitFor(fn, timeout, label) {
    const t = Date.now();
    let last = null;
    while (Date.now() - t < timeout) {
      try { last = await fn(); if (last) return last; } catch (e) { last = 'err:' + e.message; }
      await sleep(150);
    }
    throw new Error('等待超时: ' + label + ' (最后 ' + JSON.stringify(last) + ')');
  }
  async function clickJs(selectorExpr) {
    return await ev('(function(){ var el = ' + selectorExpr + '; if (!el) return {ok:false,why:"not-found"};'
      + ' if (el.disabled) return {ok:false,why:"disabled"}; el.click(); return {ok:true}; })()');
  }
  async function screenShot(savePath) {
    const s = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(savePath, Buffer.from(s.data, 'base64'));
  }
  async function setCookie(c) {
    const u = new URL(APP);
    for (const part of String(c || '').split(';').map((s) => s.trim()).filter(Boolean)) {
      const i = part.indexOf('=');
      if (i < 0) continue;
      await send('Network.setCookie', { name: part.slice(0, i), value: part.slice(i + 1), domain: u.hostname, path: '/', url: APP });
    }
  }

  return {
    tag: tag, ev: ev, send: send, waitFor: waitFor, clickJs: clickJs, screenShot: screenShot, setCookie: setCookie,
    consoleLogs: consoleLogs, socketFrames: socketFrames, netPosts: netPosts,
    close: () => {
      try { ws.close(); } catch (e) { /* ignore */ }
      try { proc.kill(); } catch (e) { /* ignore */ }
      preClean(path.basename(profileDir));
    },
  };
}

// ---------- 页面侧探针：一次性把"这一侧看到了什么"全部取回来 ----------
// ⚠️ 「在哪个界面」不能只看 class：`.screen` 的可见性由 CSS 决定，必须同时读 computed display。
const PROBE_JS = `(function(){
  var SCREEN_IDS = ['start-screen','custom-room-screen','ship-placement-screen','rps-screen',
                    'game-screen','leaderboard-screen','lobby-screen','game-over-screen',
                    'match-success-screen'];
  var screens = {}, activeList = [];
  SCREEN_IDS.forEach(function(id){
    var el = document.getElementById(id);
    if (!el) { screens[id] = 'MISSING'; return; }
    var cs = getComputedStyle(el);
    screens[id] = { active: el.classList.contains('active'), display: cs.display,
                    hiddenCls: el.classList.contains('hidden'), visible: cs.display !== 'none' };
    if (screens[id].active) activeList.push(id);
  });
  function vis(id){ var el = document.getElementById(id); if (!el) return null;
    var cs = getComputedStyle(el);
    return { present: true, hiddenCls: el.classList.contains('hidden'), display: cs.display,
             visible: cs.display !== 'none' && cs.visibility !== 'hidden' }; }
  var g = (typeof gameState !== 'undefined' && gameState) ? gameState : {};
  var rpsEl = document.getElementById('rps-result');
  return {
    href: location.href, search: location.search, path: location.pathname,
    readyState: document.readyState, screens: screens, activeScreens: activeList,
    username: window.__USERNAME || null,
    gs: { roomId: g.roomId === undefined ? null : g.roomId,
          playerId: g.playerId === undefined ? null : g.playerId,
          playerName: g.playerName === undefined ? null : g.playerName,
          opponentName: g.opponentName === undefined ? null : g.opponentName,
          isHost: g.isHost === undefined ? null : g.isHost,
          connected: g.socket ? !!g.socket.connected : null },
    boardCells: document.querySelectorAll('#player-board .cell').length,
    placedLabel: (function(){ var e = document.getElementById('ships-placed'); return e ? e.textContent.trim() : null; })(),
    confirmHidden: (function(){ var e = document.getElementById('confirm-ships'); return e ? e.classList.contains('hidden') : null; })(),
    waitingPanel: { info: vis('custom-room-info'),
                    roomIdText: (function(){ var e = document.getElementById('custom-current-room-id'); return e ? e.textContent.trim() : null; })(),
                    copyLinkPresent: !!document.getElementById('copy-invite-link') },
    inviteToast: (function(){ var t = document.getElementById('friend-invite-toast');
      if (!t) return null; var cs = getComputedStyle(t);
      return { hiddenCls: t.classList.contains('hidden'), display: cs.display,
               visible: cs.display !== 'none',
               text: (document.getElementById('friend-invite-text') || {}).textContent }; })(),
    friendsMsg: (function(){ var e = document.getElementById('friends-msg'); return e ? e.textContent.trim() : null; })(),
    friendsModalOpen: (function(){ var m = document.getElementById('friends-modal'); return m ? !m.classList.contains('hidden') : null; })(),
    rpsResultText: rpsEl ? rpsEl.textContent.trim().slice(0, 120) : null,
    myNameDom: (function(){ var e = document.getElementById('my-username-info'); return e ? e.textContent.trim() : null; })()
  };
})()`;

// 客户端真实收发报文的记录钩子（挂在 socket 客户端的分发点上，不重写任何处理逻辑）
const HOOK_JS = `(function(){
  if (window.__inviteHookInstalled) return 'already';
  var s = window.gameState && window.gameState.socket;
  if (!s || typeof s.onevent !== 'function') return 'no-socket';
  window.__inviteSock = [];
  var rec = function(dir, name, data){
    if (window.__inviteSock.length > 400) return;
    window.__inviteSock.push({ dir: dir, name: name, data: data, t: Date.now() });
  };
  var orig = s.onevent.bind(s);
  s.onevent = function(packet){
    try {
      var arr = (packet && packet.data) || [];
      if (arr[0] !== 'pong' && arr[0] !== 'ping') rec('in', arr[0], arr[1]);
    } catch (e) {}
    return orig(packet);
  };
  var origEmit = s.emit.bind(s);
  s.emit = function(){
    try { rec('out', arguments[0], arguments[1]); } catch (e) {}
    return origEmit.apply(null, arguments);
  };
  window.__inviteHookInstalled = true;
  return 'ok';
})()`;
const SOCK_OUT_COUNT = (name) => '(function(){ var s = window.__inviteSock || [];'
  + ' return s.filter(function(x){ return x.dir === "out" && x.name === ' + JSON.stringify(name) + '; }).length; })()';

// 把界面切回"自定义房 + 等待面板"，这样 `#custom-close-room` 才在眼前。
// 复刻的正是 `showCustomRoomWaiting()` 干的那两件事（切屏 + 显示面板），不碰产品代码。
async function showWaitingPanel(br, roomId) {
  return await br.ev('(function(){'
    + ' var id = ' + JSON.stringify(String(roomId || '')) + ';'
    + ' var span = document.getElementById("custom-current-room-id");'
    + ' if (span && id) span.textContent = id;'
    + ' var info = document.getElementById("custom-room-info");'
    + ' if (info) info.classList.remove("hidden");'
    + ' if (typeof switchScreen === "function") switchScreen(document.getElementById("custom-room-screen"));'
    + ' return 1; })()');
}

// ---------- python 侧探针（回答"房里到底几个人"） ----------
const PY_HELPER = path.join(TMP, 'invite_occupy_probe.py');
const CMD_FILE = path.join(TMP, 'invite_probe_cmd.json');
const CMD_FILE_2 = path.join(TMP, 'invite_probe_cmd_2.json');
const CMD_FILE_2B = path.join(TMP, 'invite_probe_cmd_2b.json');
const CMD_FILE_2C = path.join(TMP, 'invite_probe_cmd_2c.json');
const CMD_FILE_Z = path.join(TMP, 'invite_probe_cmd_z.json');
const probeProcs = [];
let cmdSeq = 0;

function makeLineReader(onObj) {
  let buf = '';
  return (chunk) => {
    buf += chunk.toString('utf8');
    let idx;
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line) continue;
      try { onObj(JSON.parse(line)); } catch (e) { onObj({ event: 'unparsed', raw: line.slice(0, 300) }); }
    }
  };
}
function startProbe(cmdFile, sink, tag, username) {
  try { fs.unlinkSync(cmdFile); } catch (e) { /* 没有就够 */ }
  const p = spawn('python', [PY_HELPER, APP, username || UP, cmdFile], {
    cwd: ROOT, env: Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8' }),
    stdio: ['ignore', 'pipe', 'pipe']
  });
  p.__cmdFile = cmdFile;
  p.stdout.on('data', makeLineReader((o) => sink.push(o)));
  p.stderr.on('data', (d) => {
    const s = d.toString('utf8');
    if (/Traceback|Error/.test(s)) sink.push({ event: tag + '_stderr', raw: s.replace(/\s+/g, ' ').slice(0, 300) });
  });
  probeProcs.push(p);
  return p;
}
function killProbe(p) {
  try { if (p) p.kill(); } catch (e) { /* ignore */ }
  const i = probeProcs.indexOf(p);
  if (i >= 0) probeProcs.splice(i, 1);
}
function killAllProbes() { probeProcs.slice().forEach(killProbe); preClean('invite_occupy_probe'); }
function probeCmd(cmd, extra, cmdFile) {
  const s = ++cmdSeq;
  fs.writeFileSync(cmdFile || CMD_FILE, JSON.stringify(Object.assign({ seq: s, cmd: cmd }, extra || {})), 'utf8');
  return s;
}
function waitProbeResult(sink, seq, timeout) {
  return (async () => {
    const t = Date.now();
    while (Date.now() - t < timeout) {
      const hit = sink.find((e) => e.event === 'cmd_result' && e.seq === seq);
      if (hit) return hit;
      await sleep(150);
    }
    throw new Error('python 探针命令超时 #' + seq);
  })();
}
function waitProbeReady(sink, timeout) {
  return (async () => {
    const t = Date.now();
    while (Date.now() - t < timeout) {
      const hit = sink.find((e) => e.event === 'probe_connected');
      if (hit) return hit;
      const bad = sink.find((e) => e.event === 'fatal');
      if (bad) return bad;
      await sleep(300);
    }
    return null;
  })();
}

// 独立房间的边界用例：第三个人插一间"两人已满"的房。
// ⚠️ 必须用**三个不同身份**（见文件头"踩过的坑"第 7 条）；而且必须用**独立的房**，
//    绝不能拿主房间当靶子（探针一进去就把主链搅成 2/2 并推进阶段，后面结论全废）。
async function runThirdPartyBoundary() {
  console.log('\n-- 边界：第三个人 join_room 一间已满的房（独立房间，不碰主链）--');
  const s1 = [], s2 = [], s3 = [];
  let p1 = null, p2 = null, p3 = null;
  try {
    p1 = startProbe(CMD_FILE_2, s1, 'probeX', UP);
    p2 = startProbe(CMD_FILE_2B, s2, 'probeY', UP2);
    const r1 = await waitProbeReady(s1, 45000);
    const r2 = await waitProbeReady(s2, 45000);
    check(!!r1 && r1.event === 'probe_connected' && !!r2 && r2.event === 'probe_connected',
      '★ B1 [边界] 两个探针连接都就位（身份 ' + UP + ' / ' + UP2 + '）', { x: r1, y: r2 });
    if (!r1 || r1.event !== 'probe_connected' || !r2 || r2.event !== 'probe_connected') return;

    const mkSeq = probeCmd('mkroom', {}, CMD_FILE_2);
    const mk = await waitProbeResult(s1, mkSeq, 30000);
    const bRoom = String((mk && (mk.room || (mk.ack && mk.ack.room_id))) || '');
    check(!!bRoom, '★ B2 [边界] 探针 X 建了一间独立的房（不碰主房间）', mk);
    if (!bRoom) return;

    const jSeq = probeCmd('joinroom', { room: bRoom }, CMD_FILE_2B);
    const j = await waitProbeResult(s2, jSeq, 30000);
    check(!!j && j.ack && j.ack.status === 'success',
      '★ B3 [边界] 探针 Y（第二个身份）坐满第二个座位（房间 2/2）', j && j.ack);

    p3 = startProbe(CMD_FILE_2C, s3, 'probeZ', UP3);
    await waitProbeReady(s3, 45000);
    const thirdSeq = probeCmd('joinroom', { room: bRoom }, CMD_FILE_2C);
    const third = await waitProbeResult(s3, thirdSeq, 30000);
    check(!!third && third.ack && third.ack.status === 'error' && /已满/.test(String(third.ack.message)),
      '★ B4 [边界] 第三个**不同身份**的人 join 同一间满房 → 被拒，且有中文原因',
      { ack: third && third.ack });
    step('边界：第三个人插满房（独立房间）', {
      A: { note: '不涉及主链' },
      B: { note: '不涉及主链' },
      server: { room: bRoom, host: UP, second: UP2, third: UP3,
                host_ack: mk && mk.ack, second_ack: j && j.ack, third_ack: third && third.ack },
    });

    // 附注（不是断言）：同一个登录身份从**另一条连接** join 同一间房时，
    // `room.players[user_id]` 会被自己覆盖。房里只有 1 个 key → `len(room.players) >= 2`
    // 永远不成立 → 那间房永远开不了局；而 ack 是 **success**，页面上看不出任何异常。
    // 最小现场见 .tmp/diag_third_seat.py 的输出（报告里贴了原文）。
    const selfSeq = probeCmd('joinroom', { room: bRoom }, CMD_FILE_2);
    const selfJoin = await waitProbeResult(s1, selfSeq, 30000);
    capture.defect_selfJoinSameRoom = { ack: selfJoin && selfJoin.ack,
      note: '房间容量判据是 len(room.players)（dict，key = session["user_id"]）而不是连接数：'
          + '同一个登录身份再多 join 一次只是覆盖自己那个 key。房里只有他一个 key 时'
          + '（同一账号开两个标签页、或"房主再点一次加入"），长度永远到不了 2 →'
          + ' room.state 永远停在 waiting → 谁也别想开局；ack 却是 success。' };
    console.log('   NOTE（同身份重复 join，本房里已有 2 个 key 所以回缺满）: '
      + JSON.stringify(selfJoin && selfJoin.ack));
  } catch (e) {
    check(false, '★ B* [边界] 这一组跑完了', { error: e.message });
  } finally {
    killProbe(p1); killProbe(p2); killProbe(p3);
  }
}

// ===========================================================================
// 主流程
// ===========================================================================
let A = null, B = null;
const capture = {
  mode: MODE, app: APP,
  accounts: { A: UA, B: UB, probes: [UP, UP2, UP3], A3: UA3, B3: UB3 },
  timeline: timeline, checks: [], startedAt: new Date().toISOString(),
  fingerprintsBefore: { gamejs: fingerprint(path.join(ROOT, 'static', 'game.js')),
                        apipy: fingerprint(path.join(ROOT, 'api.py')),
                        serverpy: fingerprint(path.join(ROOT, 'server.py')) },
};

try {
  console.log('=== 好友一键邀战 · 双浏览器端到端检查  mode=' + MODE + '  url=' + APP + ' ===');
  console.log('   static/game.js = ' + JSON.stringify(capture.fingerprintsBefore.gamejs));

  // ---- 0. 账号与好友关系（走真 HTTP 接口） ----
  const cookieA = await authCookie(UA);
  const cookieB = await authCookie(UB);
  check(!!cookieA && !!cookieB, '0a 两个真账号注册+登录成功（A / B）', { A: !!cookieA, B: !!cookieB });
  const relReq = await postJson('api/friends/request', { username: UB }, cookieA);
  const relAcc = await postJson('api/friends/respond', { username: UA, accept: true }, cookieB);
  check(relReq.status === 200 && relReq.body && relReq.body.status === 'sent',
    '0b A 向 B 发好友申请（真接口）', relReq);
  check(relAcc.status === 200 && relAcc.body && relAcc.body.status === 'accepted',
    '0c B 接受（真接口）—— 没有这层关系，A 的好友面板里就没有 B 那一行', relAcc);

  // ---- 1. 起两个浏览器 ----
  A = await launch('A', PORT_A, PROFILE_A);
  B = await launch('B', PORT_B, PROFILE_B);
  for (const br of [A, B]) {
    await br.send('Page.enable');
    await br.send('Runtime.enable');
    await br.send('Network.enable');
    await br.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  }
  await A.setCookie(cookieA);
  await B.setCookie(cookieB);
  for (const br of [A, B]) {
    await br.send('Page.navigate', { url: APP });
    await br.waitFor(async () => await br.ev('document.readyState === "complete"'), 25000, '页面加载 ' + br.tag);
  }
  const meA = await A.ev('window.__USERNAME || null');
  const meB = await B.ev('window.__USERNAME || null');
  check(meA === UA && meB === UB, '1a 两个页面各自认得自己的登录身份（cookie 真的生效）',
    { A: meA, expectA: UA, B: meB, expectB: UB });

  const sockA = await A.waitFor(async () => await A.ev('!!(window.gameState && gameState.socket && gameState.socket.connected)'), 25000, 'A 的 socket').catch(() => null);
  const sockB = await B.waitFor(async () => await B.ev('!!(window.gameState && gameState.socket && gameState.socket.connected)'), 25000, 'B 的 socket').catch(() => null);
  check(sockA === true && sockB === true,
    '1b 两侧 socket 都连上了（CORS_ORIGINS 必须放行 ' + APP + '，否则静默连不上）', { A: sockA, B: sockB });
  await A.ev(HOOK_JS);
  await B.ev(HOOK_JS);

  let stateA = await A.ev(PROBE_JS);
  let stateB = await B.ev(PROBE_JS);
  step('基线：两个真人都在首页、都没进任何房', {
    A: { activeScreens: stateA.activeScreens, roomId: stateA.gs.roomId, href: stateA.href },
    B: { activeScreens: stateB.activeScreens, roomId: stateB.gs.roomId, href: stateB.href },
  });
  check(stateA.gs.roomId === null && stateB.gs.roomId === null,
    '1d 基线：两边 gameState.roomId 都是 null（干净起点，后面才有对比价值）',
    { A: stateA.gs.roomId, B: stateB.gs.roomId });

  // ---- 1e. 独立房间的"第三个人"边界（与主链完全隔离，放最前面免得搅动主房间） ----
  await runThirdPartyBoundary();

  // ---- 2. A 打开好友面板 → 点 B 的「邀战」 ----
  await A.clickJs('document.getElementById("friends-btn")');
  const rowReady = await A.waitFor(async () => {
    return await A.ev('(function(){ var rows = [].slice.call(document.querySelectorAll("#friends-list .friend-row"));'
      + ' var r = rows.filter(function(x){ return x.dataset.username === ' + JSON.stringify(UB) + '; })[0];'
      + ' if (!r) return null; var b = r.querySelector(\'[data-friend-action="invite"]\');'
      + ' return b ? { disabled: b.disabled, title: b.title, state: (r.querySelector(".friend-state")||{}).textContent } : null; })()');
  }, 20000, 'A 的好友面板里出现 B 那一行').catch(() => null);
  check(!!rowReady && rowReady.disabled === false,
    '2a A 的好友面板里 B 那一行有可点的「邀战」（data-friend-action="invite"）', rowReady);

  const netMarkA = A.netPosts.length;
  const inviteClick = await A.ev('(function(){'
    + ' var rows = [].slice.call(document.querySelectorAll("#friends-list .friend-row"));'
    + ' var r = rows.filter(function(x){ return x.dataset.username === ' + JSON.stringify(UB) + '; })[0];'
    + ' if (!r) return {ok:false, why:"no-row"};'
    + ' var b = r.querySelector(\'[data-friend-action="invite"]\');'
    + ' if (!b) return {ok:false, why:"no-btn"}; b.click(); return {ok:true}; })()');
  check(inviteClick && inviteClick.ok === true, '★ 2b A 在好友面板里点了 B 的「邀战」', inviteClick);
  const tInvite = stamp();

  const invResp = await (async () => {
    const t = Date.now();
    while (Date.now() - t < 20000) {
      const hit = A.netPosts.slice(netMarkA).find((p) => /\/api\/friends\/invite/.test(p.url) && p.body);
      if (hit) return hit;
      await sleep(150);
    }
    return null;
  })();
  let invBody = null;
  try { invBody = invResp && invResp.body ? JSON.parse(invResp.body) : null; } catch (e) { invBody = null; }
  const ROOM_X = invBody && invBody.room_id ? String(invBody.room_id) : '';
  check(!!ROOM_X && invBody.status === 'ok',
    '★ 2c POST /api/friends/invite 回 ok 且给出房间号（服务端**只建房、不坐人**）',
    { http: invResp && invResp.status, body: invBody, t: tInvite });

  // ---- 3. ★ A 那一侧到底发生了什么（本工具存在的理由） ----
  await sleep(2500);
  stateA = await A.ev(PROBE_JS);
  stateB = await B.ev(PROBE_JS);
  step('★ 邀战之后 A 那一侧：屏幕 / 房间号 / 地址栏 / 提示', {
    A: { activeScreens: stateA.activeScreens, roomId: stateA.gs.roomId, href: stateA.href,
         waitingPanel: stateA.waitingPanel, friendsMsg: stateA.friendsMsg,
         boardCells: stateA.boardCells },
    B: { activeScreens: stateB.activeScreens, inviteToast: stateB.inviteToast, roomId: stateB.gs.roomId },
    server: { 'POST /api/friends/invite': invBody },
  });
  check(String(stateA.gs.roomId) === ROOM_X,
    (MODE === 'prefixed' ? '★ 3a [修复前预期：应当为 false] ' : '★ 3a [修复后要求] ')
      + 'A 被带进自己建的这间房：gameState.roomId == ' + ROOM_X,
    { roomId: stateA.gs.roomId, expect: ROOM_X, mode: MODE });
  check(String(stateA.href).indexOf('room=' + ROOM_X) >= 0,
    (MODE === 'prefixed' ? '★ 3b [修复前预期：应当为 false] ' : '★ 3b [修复后要求] ')
      + 'A 的地址栏带上了 ?room=' + ROOM_X, { href: stateA.href });
  check(stateA.waitingPanel.info && stateA.waitingPanel.info.visible === true
        && stateA.waitingPanel.roomIdText === ROOM_X,
    (MODE === 'prefixed' ? '★ 3c [修复前预期：应当为 false] ' : '★ 3c [修复后要求] ')
      + 'A 停在房间等待面板（#custom-room-info 可见、#custom-current-room-id == 房间号）',
    stateA.waitingPanel);
  check(stateA.activeScreens.indexOf('ship-placement-screen') < 0,
    '★ 3d A **不该**停在布船屏（修复前 A 根本没进任何房；修复后停在等待面板）',
    { activeScreens: stateA.activeScreens });

  // ---- 4. B 收到提示条 → 点「进入房间」 ----
  const toast = await B.waitFor(async () => {
    const o = await B.ev('(function(){ var t = document.getElementById("friend-invite-toast");'
      + ' if (!t) return null; var cs = getComputedStyle(t);'
      + ' return { visible: cs.display !== "none" && !t.classList.contains("hidden"),'
      + ' text: (document.getElementById("friend-invite-text")||{}).textContent,'
      + ' enterDisabled: (document.getElementById("friend-invite-enter")||{}).disabled }; })()');
    return (o && o.visible) ? o : null;
  }, 25000, 'B 的页面弹出 #friend-invite-toast').catch(() => null);
  check(!!toast && String(toast.text).indexOf(ROOM_X) >= 0,
    '★ 4a B 的页面弹出 #friend-invite-toast 且文案里是**这一次**的房间号', toast || { expect: ROOM_X });
  step('B 收到邀战提示条', {
    A: { activeScreens: stateA.activeScreens, roomId: stateA.gs.roomId,
         note: MODE === 'prefixed' ? 'A 侧此刻毫无反应（坏样子）' : 'A 侧在等待面板上等' },
    B: { inviteToast: toast },
    server: {},
  });

  const aBeforeEnter = await A.ev(PROBE_JS);
  const enterClick = await B.clickJs('document.getElementById("friend-invite-enter")');
  check(enterClick && enterClick.ok === true, '4b B 点了 #friend-invite-enter（「进入房间」）', enterClick);

  const bJoinOk = await B.waitFor(async () => {
    const s = await B.ev('window.__inviteSock || []');
    const hit = s.filter((x) => x.dir === 'out' && x.name === 'join_room');
    return hit.length ? hit[hit.length - 1] : null;
  }, 20000, 'B 真的 emit 了 join_room').catch(() => null);
  check(!!bJoinOk && String(bJoinOk.data && bJoinOk.data.room_id) === ROOM_X,
    '★ 4c B 的 join_room 报文里的 room_id 就是服务端给的那个房', bJoinOk ? bJoinOk.data : null);

  await sleep(3000);
  stateB = await B.ev(PROBE_JS);
  const aAfterEnter = await A.ev(PROBE_JS);
  step('★ B 点「进入房间」之后：两边各自在哪个屏、哪个房', {
    A: { activeScreens: aAfterEnter.activeScreens, roomId: aAfterEnter.gs.roomId,
         href: aAfterEnter.href, waitingPanel: aAfterEnter.waitingPanel },
    B: { activeScreens: stateB.activeScreens, roomId: stateB.gs.roomId, href: stateB.href,
         boardCells: stateB.boardCells, opponentName: stateB.gs.opponentName,
         playerName: stateB.gs.playerName, playerId: stateB.gs.playerId,
         waitingPanel: stateB.waitingPanel },
    server: { bJoinPayload: bJoinOk && bJoinOk.data, roomX: ROOM_X },
  });
  if (MODE === 'prefixed') {
    check(aBeforeEnter.gs.roomId === aAfterEnter.gs.roomId && aAfterEnter.gs.roomId === null,
      '★ 4d [修复前] B 进房**完全没改变** A 的状态（A 的 roomId 始终是 null —— "根本无法启动对局"）',
      { A_before: aBeforeEnter.gs.roomId, A_after: aAfterEnter.gs.roomId });
    check(stateB.activeScreens.indexOf('ship-placement-screen') >= 0 && stateB.boardCells === 0,
      '★ 4e [修复前] B 停在**一块 0 格的空棋盘**上（#ship-placement-screen active、格子 0 个）'
      + '—— 这就是"卡死在错误的布船界面"',
      { screens: stateB.activeScreens, cells: stateB.boardCells });
  } else {
    check(aBeforeEnter.gs.roomId === aAfterEnter.gs.roomId && String(aAfterEnter.gs.roomId) === ROOM_X,
      '★ 4d [修复后] B 进房把 A 从等待面板推进了下一步（A 仍在同一个房 ' + ROOM_X + '）',
      { A_before: aBeforeEnter.gs.roomId, A_after: aAfterEnter.gs.roomId, A_screens: aAfterEnter.activeScreens });
  }

  // ---- 5. 服务端真相：这间房里几个人（干净会话探针；非破坏性） ----
  // ⚠️ 探测会把自己坐进房（probe_only 报完就断开重连）—— 所以必须放在浏览器侧
  //    "一个人在房"的取证**全部做完之后**，而且探完要把进程杀掉。
  {
    const evP = [];
    let p = null;
    try {
      p = startProbe(CMD_FILE, evP, 'probe', UP);
      await waitProbeReady(evP, 45000);
      const seq = probeCmd('occupy_probe_only', { room: ROOM_X }, CMD_FILE);
      const res = await waitProbeResult(evP, seq, 40000).catch((e) => ({ ok: false, error: e.message }));
      const seats = res && res.seats;
      capture.occupancyAfterInvitee = { seats: seats, ack: res && res.ack, game_state_frames: res && res.game_state_frames };
      step('★ 服务端真相：一条干净会话的 python socket 去 join_room 探这间房', {
        A: { roomId: aAfterEnter.gs.roomId, activeScreens: aAfterEnter.activeScreens },
        B: { roomId: stateB.gs.roomId, activeScreens: stateB.activeScreens },
        server: { probe_ack: res && res.ack, seats_before_probe: seats },
      });
      check(seats === 1 || seats === 2, '★ 5a 探针拿到了明确的座位口径（1=只有被邀请方 / 2=发起方也在）', res);
      if (MODE === 'prefixed') {
        check(seats === 1, '★ 5b [修复前] 邀战建的房里在 B 进去之后**只有 1 个人**'
          + '（干净会话的探针能坐进去 = 铁证：发起方 A 从没进过这间房）', { seats: seats, ack: res && res.ack });
      } else {
        check(seats === 2, '★ 5b [修复后] 房里已有 2 个人（A + B），探针被「房间已满」挡在门外',
          { seats: seats, ack: res && res.ack });
      }
    } finally {
      killProbe(p);
      await sleep(1000);
    }
  }

  // ---- 6. 布船 / 确认 / 开打 ----
  // ⚠️ 格子是 `game_state(state='placing_ships')` 到达后、再走完 **5 秒**匹配成功倒计时
  //    由 `initBoard(playerBoard, true)` 建的 —— 必须 waitFor(36)，别立刻取样。
  const boardA = await A.waitFor(async () => {
    const o = await A.ev(PROBE_JS);
    return (o.activeScreens.indexOf('ship-placement-screen') >= 0 && o.boardCells === 36) ? o : null;
  }, 30000, 'A 侧布船屏 36 格').catch(() => null);
  const boardB = await B.waitFor(async () => {
    const o = await B.ev(PROBE_JS);
    return (o.activeScreens.indexOf('ship-placement-screen') >= 0 && o.boardCells === 36) ? o : null;
  }, 30000, 'B 侧布船屏 36 格').catch(() => null);
  step('两边各自进布船屏（36 格棋盘）', {
    A: boardA ? { activeScreens: boardA.activeScreens, roomId: boardA.gs.roomId, cells: boardA.boardCells,
                  opponentName: boardA.gs.opponentName, playerId: boardA.gs.playerId,
                  waitingPanelVisible: boardA.waitingPanel.info && boardA.waitingPanel.info.visible } : null,
    B: boardB ? { activeScreens: boardB.activeScreens, roomId: boardB.gs.roomId, cells: boardB.boardCells,
                  opponentName: boardB.gs.opponentName, playerId: boardB.gs.playerId } : null,
    server: {},
  });
  if (MODE === 'postfixed') {
    check(!!boardA && boardA.gs.roomId === ROOM_X && boardA.gs.opponentName === UB,
      '★ 6a [修复后] A 进到布船屏、36 格、房间号对、对手名是 B',
      boardA ? { cells: boardA.boardCells, roomId: boardA.gs.roomId, opponent: boardA.gs.opponentName } : null);
    check(!!boardB && boardB.gs.roomId === ROOM_X && boardB.gs.opponentName === UA,
      '★ 6b [修复后] B 也在同一个布船屏、36 格、对手名是 A',
      boardB ? { cells: boardB.boardCells, roomId: boardB.gs.roomId, opponent: boardB.gs.opponentName } : null);
    check(!!boardA && !!boardB && String(boardA.gs.playerId) !== String(boardB.gs.playerId),
      '★ 6c [修复后] 两侧 playerId 不同（同一个房里的两个座位）',
      { A: boardA && boardA.gs.playerId, B: boardB && boardB.gs.playerId });
    check(!!boardA && boardA.waitingPanel.info && boardA.waitingPanel.info.visible === false,
      '★ 6d [修复后] A 到了布船屏之后等待面板已收起（#custom-room-info 被隐藏）',
      boardA ? boardA.waitingPanel : null);
  } else {
    check(!boardA, '★ 6a [修复前] A **没有**布船屏可进（roomId 一直是 null → 服务端永远不给它 game_state）',
      boardA ? { roomId: boardA.gs.roomId, cells: boardA.boardCells } : 'no-board');
    const nameB = boardB ? String(boardB.gs.opponentName || '') : '';
    check(!!boardB && boardB.boardCells === 36 && nameB && nameB !== UA && nameB !== UB,
      '★ 6b [修复前] 房间被探针凑满 2 人后 B 才拿到棋盘 —— 而它对上的"对手"**不是发起方 A**',
      boardB ? { cells: boardB.boardCells, opponent: boardB.gs.opponentName, roomId: boardB.gs.roomId } : null);
  }

  /**
   * 摆 6 格 + 点「确认放置」+ 等阶段推进。
   * ⚠️ 全部包在 try 里并把**每一步**都记进返回值：踩过一次"这一步莫名返回了 undefined"，
   *    现场却只剩一个 `null`（`placeZ2: null`），根本分不清是"没棋盘 / 点不动 / 页面异常"。
   *    另外这个工具跑的时候 `static/game.js` 可能正被并行编辑（读到半截文件）——
   *    那种情况下"某一侧行为诡异、另一侧正常"是预期内的，重跑前先看指纹有没有变。
   */
  async function placeAndConfirm(br, label) {
    const out = { tag: label, ok: false, stage: 'start' };
    try {
      const before = await br.ev(PROBE_JS);
      out.before = { cells: before.boardCells, screens: before.activeScreens, confirmHidden: before.confirmHidden };
      if (before.boardCells !== 36) {
        out.stage = 'no-board';
        out.skipped = true;
        return out;
      }
      out.stage = 'click-6';
      const CLICK_6 = '(function(){'
        + ' var cells = [].slice.call(document.querySelectorAll("#player-board .cell"));'
        + ' var byKey = {}; cells.forEach(function(c){ byKey[c.dataset.x + "," + c.dataset.y] = c; });'
        + ' var clicked = [];'
        + ' for (var i = 0; i < 6; i++) { var c = byKey[i + ",0"]; if (c) { c.click(); clicked.push(i + ",0"); } }'
        + ' var btn = document.getElementById("confirm-ships");'
        + ' return { clicked: clicked.length, cells: cells.length,'
        + '   ships: (window.gameState.ships || []).length,'
        + '   placedLabel: (document.getElementById("ships-placed") || {}).textContent,'
        + '   confirmHidden: btn.classList.contains("hidden") }; })()';
      let placed = await br.ev(CLICK_6);
      let retried = false;
      if (placed.ships !== 6) {
        // 棋盘格子建出来与 click handler 挂上不是同一时刻；点完立刻校验，没生效就重试一次
        await sleep(1200);
        placed = await br.ev(CLICK_6);
        retried = true;
      }
      out.placed = placed;
      out.retried = retried;
      out.stage = 'confirm';
      out.clickRes = await br.clickJs('document.getElementById("confirm-ships")');
      await sleep(600);
      out.stage = 'read-frames';
      out.place_ships_payload = await (async () => {
        const s = await br.ev('window.__inviteSock || []');
        const sent = s.filter((x) => x.dir === 'out' && x.name === 'place_ships');
        return sent.length ? sent[sent.length - 1].data : null;
      })();
      // socket.io 的 ack 帧：`43<ackId>{...}`（单值）/ `42<ackId>[...]`（数组）。
      // ⚠️ 别写成"取最后一条成功 ack" —— 会抓到 get_reconnect_token / rejoin_room 的回执。
      out.place_ships_ack = await (async () => {
        const frames = br.socketFrames.slice();
        let wantId = null;
        for (const f of frames) {
          if (f.kind === 'ws-out' && /^4[23]\d*\["place_ships"/.test(f.text || '')) {
            const m = /^4[23](\d*)\[/.exec(f.text);
            if (m && m[1]) wantId = m[1];
          }
        }
        if (wantId === null) return { note: '上行帧里没找到 place_ships 的 ackId' };
        const hit = frames.filter((f) => f.kind === 'ack' && f.ackId === wantId);
        return hit.length ? { ackId: wantId, body: hit[hit.length - 1].body }
          : { ackId: wantId, body: null, why: 'ack 帧还没到' };
      })();
      out.stage = 'wait-advance';
      const adv = await br.waitFor(async () => {
        const o = await br.ev(PROBE_JS);
        return (o.activeScreens.indexOf('rps-screen') >= 0 || o.activeScreens.indexOf('game-screen') >= 0) ? o : null;
      }, 30000, label + ' 侧阶段推进').catch(() => null);
      out.advanced = adv ? adv.activeScreens : null;
      await sleep(1500);
      const after = await br.ev(PROBE_JS);
      out.after = { activeScreens: after.activeScreens, cells: after.boardCells,
                    opponentName: after.gs.opponentName, rpsResultText: after.rpsResultText };
      out.ok = true;
      out.stage = 'done';
      return out;
    } catch (e) {
      out.ok = false;
      out.error = String(e && e.message);
      console.error('   !! placeAndConfirm(' + label + ') 在阶段「' + out.stage + '」失败: ' + out.error);
      return out;
    }
  }
  const placeA = await placeAndConfirm(A, 'A');
  const placeB = await placeAndConfirm(B, 'B');
  step('两边各摆 6 格 + 点「确认放置」', {
    A: { activeScreens: placeA.after ? placeA.after.activeScreens : null,
         placed: placeA.placed || { skipped: true, why: 'A 没有棋盘' }, click: placeA.clickRes || null },
    B: { activeScreens: placeB.after ? placeB.after.activeScreens : null, placed: placeB.placed || null,
         click: placeB.clickRes || null },
    server: { 'A place_ships payload': placeA.place_ships_payload,
              'B place_ships payload': placeB.place_ships_payload },
  });

  const advancedA = await A.waitFor(async () => {
    const o = await A.ev(PROBE_JS);
    return (o.activeScreens.indexOf('rps-screen') >= 0 || o.activeScreens.indexOf('game-screen') >= 0) ? o : null;
  }, 25000, 'A 侧阶段推进').catch(() => null);
  const advancedB = await B.waitFor(async () => {
    const o = await B.ev(PROBE_JS);
    return (o.activeScreens.indexOf('rps-screen') >= 0 || o.activeScreens.indexOf('game-screen') >= 0) ? o : null;
  }, 25000, 'B 侧阶段推进').catch(() => null);
  step('点确认之后阶段有没有推进', {
    A: advancedA ? { activeScreens: advancedA.activeScreens } : { stuck: true },
    B: advancedB ? { activeScreens: advancedB.activeScreens } : { stuck: true },
    server: {},
  });
  check(!!advancedA && !!advancedB,
    (MODE === 'prefixed' ? '★ 7 [修复前预期：应当为 false] ' : '★ 7 [修复后要求] ')
      + '两边都推进到了猜拳/对局屏（= 这一局真的能开）',
    { A: advancedA ? advancedA.activeScreens : 'stuck', B: advancedB ? advancedB.activeScreens : 'stuck' });

  // ---- 8. 边界：发起方还在局中时再点一次「邀战」（新的护栏） ----
  {
    await A.clickJs('document.getElementById("friends-btn")');
    await A.waitFor(async () => await A.ev('document.querySelectorAll("#friends-list .friend-row").length > 0'),
      15000, 'A 的好友面板再次打开').catch(() => null);
    const netMark2 = A.netPosts.length;
    const clicked = await A.ev('(function(){'
      + ' var rows = [].slice.call(document.querySelectorAll("#friends-list .friend-row"));'
      + ' var r = rows.filter(function(x){ return x.dataset.username === ' + JSON.stringify(UB) + '; })[0];'
      + ' if (!r) return {ok:false, why:"no-row"};'
      + ' var b = r.querySelector(\'[data-friend-action="invite"]\');'
      + ' if (!b || b.disabled) return {ok:false, why:"no-btn-or-disabled"};'
      + ' b.click(); return {ok:true}; })()');
    const resp = await (async () => {
      const t = Date.now();
      while (Date.now() - t < 20000) {
        const hit = A.netPosts.slice(netMark2).find((p) => /\/api\/friends\/invite/.test(p.url) && p.body);
        if (hit) return hit;
        await sleep(150);
      }
      return null;
    })();
    let body2 = null;
    try { body2 = resp && resp.body ? JSON.parse(resp.body) : null; } catch (e) { body2 = null; }
    const aNow = await A.ev(PROBE_JS);
    const bNow = await B.ev(PROBE_JS);
    step('★ 边界：发起方还在局中时又点了一次「邀战」', {
      A: { invite_ack: body2, roomId: aNow.gs.roomId, screens: aNow.activeScreens, boardCells: aNow.boardCells },
      B: { inviteToast: bNow.inviteToast, note: '这一次不该有新的提示条（邀战应被服务端拒掉）' },
      server: { 'POST /api/friends/invite (2nd)': body2, http: resp && resp.status },
    });
    check(clicked && clicked.ok === true && body2 && body2.status === 'error'
          && String(body2.error).indexOf('正在对局中') >= 0,
      '★ 8a [护栏] 发起方正在局中时，第二次邀战被服务端拒绝（409 + 中文原因）',
      { click: clicked, body: body2, http: resp && resp.status });
    check(!bNow.inviteToast || bNow.inviteToast.visible === false
          || String(bNow.inviteToast.text).indexOf(ROOM_X) >= 0,
      '★ 8b [护栏] 被拒的邀战**没有**再给 B 推提示条（不产生"点了没反应的邀请"）', bNow.inviteToast);
    check(String(aNow.gs.roomId) === ROOM_X,
      '★ 8c [护栏] 被拒的邀战没有把 A 换到别的房（roomId 仍是原来那间）',
      { roomId: aNow.gs.roomId, expect: ROOM_X });
  }

  // ---- 9. 场景③：全新账号「发起方空等 → 返回主菜单 → 解散房间 → 重新邀战」 ----
  {
    console.log('\n-- 场景③：全新账号，发起方空等 → 返回主菜单 → 解散房间 → 重新邀战 --');
    if (MODE === 'prefixed') {
      console.log('   SKIP（prefixed：修复前发起方从不进房，没有"等待面板"可测）');
    } else {
      const cookieA3 = await authCookie(UA3);
      const cookieB3 = await authCookie(UB3);
      check(!!cookieA3 && !!cookieB3, '★ 9a 新账号 A3/B3 注册+登录（与前面那局完全隔离）',
        { A3: !!cookieA3, B3: !!cookieB3 });
      const r1 = await postJson('api/friends/request', { username: UB3 }, cookieA3);
      const r2 = await postJson('api/friends/respond', { username: UA3, accept: true }, cookieB3);
      check(r1.status === 200 && r2.status === 200, '★ 9b A3/B3 成为好友（真接口）',
        { req: r1.body, acc: r2.body });

      // ⚠️ 换身份必须**先清 cookie**再种新的，否则页面还是原来那个人（工具假红）
      await A.send('Network.clearBrowserCookies');
      await B.send('Network.clearBrowserCookies');
      await A.setCookie(cookieA3);
      await B.setCookie(cookieB3);
      for (const br of [A, B]) {
        await br.send('Page.navigate', { url: APP });
        await br.waitFor(async () => await br.ev('document.readyState === "complete"'), 25000, '换账号后重新加载 ' + br.tag);
      }
      const meA3 = await A.ev('window.__USERNAME || null');
      const meB3 = await B.ev('window.__USERNAME || null');
      await A.waitFor(async () => await A.ev('!!(window.gameState && gameState.socket && gameState.socket.connected)'), 25000, 'A3 socket').catch(() => null);
      await B.waitFor(async () => await B.ev('!!(window.gameState && gameState.socket && gameState.socket.connected)'), 25000, 'B3 socket').catch(() => null);
      await A.ev(HOOK_JS);
      await B.ev(HOOK_JS);
      check(meA3 === UA3 && meB3 === UB3, '★ 9c 同一个浏览器换了登录身份（cookie 生效）', { A: meA3, B: meB3 });

      // A3 邀 B3（B3 故意不点）；点完「邀战」要把好友面板关掉再取样
      // （面板是 fixed 浮层、盖住整屏，不关掉就会把等待面板读成"被压住/不可见"）。
      await A.clickJs('document.getElementById("friends-btn")');
      await A.waitFor(async () => await A.ev('(function(){ var rows = [].slice.call(document.querySelectorAll("#friends-list .friend-row"));'
        + ' return rows.filter(function(x){ return x.dataset.username === ' + JSON.stringify(UB3) + '; }).length > 0; })()'),
        20000, 'A3 的好友面板出现 B3').catch(() => null);
      const netMark3 = A.netPosts.length;
      const inv3 = await A.ev('(function(){'
        + ' var rows = [].slice.call(document.querySelectorAll("#friends-list .friend-row"));'
        + ' var r = rows.filter(function(x){ return x.dataset.username === ' + JSON.stringify(UB3) + '; })[0];'
        + ' if (!r) return {ok:false, why:"no-row"};'
        + ' var b = r.querySelector(\'[data-friend-action="invite"]\');'
        + ' if (!b || b.disabled) return {ok:false, why:"no-btn-or-disabled"};'
        + ' b.click(); return {ok:true}; })()');
      const resp3 = await (async () => {
        const t = Date.now();
        while (Date.now() - t < 20000) {
          const hit = A.netPosts.slice(netMark3).find((p) => /\/api\/friends\/invite/.test(p.url) && p.body);
          if (hit) return hit;
          await sleep(150);
        }
        return null;
      })();
      let body3 = null;
      try { body3 = resp3 && resp3.body ? JSON.parse(resp3.body) : null; } catch (e) { body3 = null; }
      const ROOM_Z = body3 && body3.room_id ? String(body3.room_id) : '';
      check(inv3 && inv3.ok === true && !!ROOM_Z && body3.status === 'ok',
        '★ 9d A3 邀战成功（B3 收得到提示条但**不点**）', { click: inv3, body: body3 });
      await A.ev('(function(){ var b = document.getElementById("friends-close"); if (b) b.click(); return 1; })()');
      await sleep(2500);
      const z1 = await A.ev(PROBE_JS);
      await sleep(9000);
      const z2 = await A.ev(PROBE_JS);
      const placeOutZ = await A.ev(SOCK_OUT_COUNT('place_ships'));
      step('★ 场景③-a：A3 邀了人、对方一直不点（发起方空等 11 秒）', {
        A: { invite_ack: body3, activeScreens: z1.activeScreens, roomId: z1.gs.roomId,
             search: z1.search, boardCells: z1.boardCells, waitingPanel: z1.waitingPanel,
             waitingPanelAfter11s: z2.waitingPanel, friendsModalOpen: z2.friendsModalOpen,
             place_ships_emitted: placeOutZ, friendsMsg: z1.friendsMsg, href: z1.href },
        B: { note: 'B3 收到提示条但故意不点「进入房间」' },
        server: { 'POST /api/friends/invite': body3 },
      });
      check(z2.waitingPanel.info && z2.waitingPanel.info.visible === true && z2.waitingPanel.roomIdText === ROOM_Z,
        '★ 9e [发起方空等] A3 稳稳停在房间等待面板、房号 = 这次新房（不是一块死棋盘）',
        { panel: z2.waitingPanel, expect: ROOM_Z, screens: z2.activeScreens });
      check(z2.activeScreens.indexOf('ship-placement-screen') < 0 && z2.boardCells === 0,
        '★ 9f [发起方空等] A3 **没有**落在布船屏（用户报的第二个症状：等的是人，不是空棋盘）',
        { screens: z2.activeScreens, cells: z2.boardCells });
      check(placeOutZ === 0, '★ 9g [发起方空等] A3 没有抢先 emit place_ships（没有棋盘可摆，也没谎报"已摆好"）',
        { place_ships_emitted: placeOutZ });

      // 「返回主菜单」：只回首页 + 收起等待面板，**不**把自己从房里摘出去（房还在等他）
      const beforeBack = await A.ev(PROBE_JS);
      await A.clickJs('document.getElementById("back-to-main")');
      await sleep(2000);
      const afterBack = await A.ev(PROBE_JS);
      step('★ 场景③-b：A3 在等待面板点「返回主菜单」', {
        A: { before: { screens: beforeBack.activeScreens, roomId: beforeBack.gs.roomId },
             after: { screens: afterBack.activeScreens, roomId: afterBack.gs.roomId,
                      search: afterBack.search, panel: afterBack.waitingPanel } },
        B: { note: '不涉及' }, server: {},
      });
      check(String(afterBack.gs.roomId) === ROOM_Z && afterBack.activeScreens.indexOf('start-screen') >= 0,
        '★ 9h 「返回主菜单」只回首页（roomId 仍指向那间**还活着**的房，没把自己摘出去）',
        { roomId: afterBack.gs.roomId, screens: afterBack.activeScreens });

      // 服务端真相：此刻房里只有 A3 一个人。
      // ⚠️⚠️ **这一步只能"看一眼"，绝不能留在房里** —— 探针一坐进等待房，
      //     服务端随后就把那间房**判空回收掉了**（实测：探针走后再 join 回「房间不存在」），
      //     于是后面点「解散房间」必然回「房间不存在」、面板也不会收起 ——
      //     看着像"解散坏了"，其实是**工具自己把房弄没了**（本工具踩过一次）。
      //     所以这里只在**局已经开起来之后**做占位取证（见 9s 后面的 9t），
      //     解散那一段之前**不碰**服务端的房。
      // 触发解散：等待房唯一的主动出口（大厅批加的）
      // ⚠️ 上一步「返回主菜单」**正确**地把屏和面板都收起来了（它就是回首页 + 收起面板），
      //    所以这里复刻 `showCustomRoomWaiting()` 干的那两件事（切回自定义房屏 + 让面板可见）
      //    再点按钮，否则按钮根本不在眼前（点了没反应 = 工具假红）。
      await showWaitingPanel(A, ROOM_Z);
      const panelBack = await A.ev(PROBE_JS);
      const markFrames = A.socketFrames.length;
      const closeClick = await A.ev('(function(){'
        + ' var p = document.getElementById("custom-room-info");'
        + ' var b = document.getElementById("custom-close-room");'
        + ' if (!b) return {ok:false, why:"no-btn"};'
        + ' if (p && p.classList.contains("hidden")) p.classList.remove("hidden");'
        + ' b.click(); return {ok:true}; })()');
      await sleep(2500);
      const afterDisband = await A.ev(PROBE_JS);
      const closeFrames = A.socketFrames.slice(markFrames, markFrames + 8);
      // ⚠️ ack 帧的形状有两种：`43<id>{...}`（**单值**回执，join_room/place_ships 走这条）
      //    与 `42<id>[...]`（**数组**回执 —— `close_room` 的 Flask-SocketIO 返回值就是
      //    被包成 `[{status,room_id}]` 的）。抓下来的第一版只认对象，于是 close_room 的
      //    ack 明明在帧里、断言却拿到 undefined（红得毫无意义）。
      const unwrap = (b) => (Array.isArray(b) ? (b[0] || {}) : (b || {}));
      const closeAck = (A.socketFrames.slice(markFrames).map((f) => (f.kind === 'ack' ? unwrap(f.body) : null))
        .filter((b) => b && (b.status === 'success'
          || (b.status === 'error' && /解散|房间|已开始/.test(String(b.message))))) || [])[0];
      capture.closeRoomAck = closeAck;
      capture.closeRoomFrames = closeFrames;
      step('★ 场景③-b：A3 点「解散房间」（#custom-close-room）', {
        A: { click: closeClick, screensBefore: panelBack.activeScreens,
             before: { roomId: panelBack.gs.roomId, panel: panelBack.waitingPanel },
             after: { roomId: afterDisband.gs.roomId, screens: afterDisband.activeScreens,
                      panel: afterDisband.waitingPanel, search: afterDisband.search } },
        B: { note: '不涉及' },
        server: { 'close_room 上行报文 + ack 帧原文': closeFrames },
      });
      check(!!closeAck && closeAck.status === 'success',
        '★ 9i 「解散房间」成功（房里确实只有自己时才该成功；ack 原文见上）', { ack: closeAck });
      check(afterDisband.gs.roomId === null || afterDisband.gs.roomId === undefined,
        '★ 9j 解散之后 A3 的 gameState.roomId 被清掉（不再指着一间已经不存在的房）',
        { roomId: afterDisband.gs.roomId });
      check(afterDisband.waitingPanel.info && afterDisband.waitingPanel.info.visible === false,
        '★ 9k 解散之后等待面板收起（#custom-room-info 隐藏）', afterDisband.waitingPanel);
      // ⚠️ 客户端解散成功后**故意留在自定义房屏**（那里才有"创建房间 / 加入房间"两个按钮）——
      //    这是大厅批自己的设计（`lobby_check.mjs` 也是这么钉的），所以判据是
      //    "**仍然**停在自定义房屏、且面板已收起"，不是"该回首页"。
      check(afterDisband.activeScreens.indexOf('custom-room-screen') >= 0,
        '★ 9l 解散之后**留在自定义房屏**（设计如此：那里才有创建/加入房间两个按钮），面板已收起',
        { screens: afterDisband.activeScreens });

      // 服务端真相：房真的没了（换一条全新会话去 join）
      {
        const ev3 = [];
        let p3 = null;
        try {
          p3 = startProbe(CMD_FILE_Z, ev3, 'probeZ3c', UP);
          await waitProbeReady(ev3, 45000);
          const sq = probeCmd('occupy_probe_only', { room: ROOM_Z }, CMD_FILE_Z);
          const r3 = await waitProbeResult(ev3, sq, 40000).catch((e) => ({ ok: false, error: e.message }));
          check(!!r3 && r3.ack && r3.ack.status === 'error' && /不存在/.test(String(r3.ack.message)),
            '★ 9n 解散之后服务端**真的把这间房删了**（全新会话 join 回「房间不存在」）',
            { ack: r3 && r3.ack });
        } finally { killProbe(p3); }
      }

      // ★ A3 能不能**再邀一次** —— 这条钉的就是"删房之后 presence 的『对局中』
      //   有没有被清掉"（`handle_close_room` 删房时不清标记 → 被"局中不许邀战"永久拦住）。
      {
        const netMark4 = A.netPosts.length;
        await A.clickJs('document.getElementById("friends-btn")');
        await A.waitFor(async () => await A.ev('(function(){ var rows = [].slice.call(document.querySelectorAll("#friends-list .friend-row"));'
          + ' return rows.filter(function(x){ return x.dataset.username === ' + JSON.stringify(UB3) + '; }).length > 0; })()'),
          20000, 'A3 好友面板再次打开').catch(() => null);
        const inv4 = await A.ev('(function(){'
          + ' var rows = [].slice.call(document.querySelectorAll("#friends-list .friend-row"));'
          + ' var r = rows.filter(function(x){ return x.dataset.username === ' + JSON.stringify(UB3) + '; })[0];'
          + ' if (!r) return {ok:false, why:"no-row"};'
          + ' var b = r.querySelector(\'[data-friend-action="invite"]\');'
          + ' if (!b || b.disabled) return {ok:false, why:"no-btn-or-disabled"};'
          + ' b.click(); return {ok:true}; })()');
        const resp4 = await (async () => {
          const t = Date.now();
          while (Date.now() - t < 20000) {
            const hit = A.netPosts.slice(netMark4).find((p) => /\/api\/friends\/invite/.test(p.url) && p.body);
            if (hit) return hit;
            await sleep(150);
          }
          return null;
        })();
        let body4 = null;
        try { body4 = resp4 && resp4.body ? JSON.parse(resp4.body) : null; } catch (e) { body4 = null; }
        const ROOM_W = body4 && body4.room_id ? String(body4.room_id) : '';
        await A.ev('(function(){ var b = document.getElementById("friends-close"); if (b) b.click(); return 1; })()');
        await sleep(2500);
        const z3 = await A.ev(PROBE_JS);
        step('★ 场景③-d：解散之后 A3 再邀一次（presence 的"对局中"该退掉了）', {
          A: { invite_ack: body4, roomId: z3.gs.roomId, screens: z3.activeScreens,
               panel: z3.waitingPanel, href: z3.href },
          B: { note: 'B3 尚未进入新房' },
          server: { 'POST /api/friends/invite (2nd)': body4 },
        });
        check(inv4 && inv4.ok === true && !!ROOM_W && body4.status === 'ok',
          '★ 9o 解散之后 A3 **能再邀一次**（= 删房时 presence 的"对局中"确实退掉了，没卡成永久对局中）',
          { click: inv4, body: body4 });
        check(String(z3.gs.roomId) === ROOM_W && z3.waitingPanel.info && z3.waitingPanel.info.visible === true
              && z3.waitingPanel.roomIdText === ROOM_W,
          '★ 9p 第二次邀战把 A3 带进新房并停在等待面板（房号、地址栏、roomId 全对）',
          { roomId: z3.gs.roomId, panel: z3.waitingPanel, expect: ROOM_W, href: z3.href });

        const toast3 = await B.waitFor(async () => {
          const o = await B.ev('(function(){ var t = document.getElementById("friend-invite-toast");'
            + ' if (!t) return null; var cs = getComputedStyle(t);'
            + ' return { visible: cs.display !== "none" && !t.classList.contains("hidden"),'
            + ' text: (document.getElementById("friend-invite-text")||{}).textContent }; })()');
          return (o && o.visible && String(o.text).indexOf(ROOM_W) >= 0) ? o : null;
        }, 20000, 'B3 收到第二次邀战提示条').catch(() => null);
        check(!!toast3, '★ 9q B3 收到第二次邀战提示条', toast3);
        if (toast3) {
          await B.clickJs('document.getElementById("friend-invite-enter")');
          const zBoard = await A.waitFor(async () => {
            const o = await A.ev(PROBE_JS);
            return (o.activeScreens.indexOf('ship-placement-screen') >= 0 && o.boardCells === 36) ? o : null;
          }, 35000, 'A3 等到 B3 之后进布船屏').catch(() => null);
          check(!!zBoard && zBoard.gs.roomId === ROOM_W && zBoard.gs.opponentName === UB3,
            '★ 9r B3 一进来 A3 立刻切到布船屏、36 格、对手名是 B3（空等不是死等）',
            zBoard ? { screens: zBoard.activeScreens, cells: zBoard.boardCells,
                       roomId: zBoard.gs.roomId, opponent: zBoard.gs.opponentName } : 'still-waiting');
          if (zBoard) {
            const placeZ1 = await placeAndConfirm(A, 'A3');
            const placeZ2 = await placeAndConfirm(B, 'B3');
            // 诊断快照：这一刻两边到底在哪个屏（把"摆船都过了却没推进"这件事钉死）
            const snapA = await A.ev(PROBE_JS);
            const snapB = await B.ev(PROBE_JS);
            capture.scenario3Placement = {
              A: { screens: snapA.activeScreens, cells: snapA.boardCells, confirmHidden: snapA.confirmHidden,
                   roomId: snapA.gs.roomId, placed: placeZ1.placed, ack: placeZ1.place_ships_ack,
                   advanced: placeZ1.advanced },
              B: { screens: snapB.activeScreens, cells: snapB.boardCells, confirmHidden: snapB.confirmHidden,
                   roomId: snapB.gs.roomId, placed: placeZ2.placed, ack: placeZ2.place_ships_ack,
                   advanced: placeZ2.advanced },
            };
            const advZ = await A.waitFor(async () => {
              const o = await A.ev(PROBE_JS);
              return (o.activeScreens.indexOf('rps-screen') >= 0 || o.activeScreens.indexOf('game-screen') >= 0) ? o : null;
            }, 25000, 'A3 侧阶段推进').catch(() => null);
            check(!!advZ, '★ 9s 两边摆船 + 确认之后这一局真的开起来了（A3 侧切到猜拳/对局屏）',
              { A: advZ ? advZ.activeScreens : 'stuck',
                placedA: placeZ1.placed || null, placedB: placeZ2.placed || null,
                ackA: placeZ1.place_ships_ack, ackB: placeZ2.place_ships_ack });
            // 9t：局开起来之后，用一条干净会话确认这间新房里**确实坐着 A3 + B3 两个人**
            //     （等待房里"一个人"那个现场**不能**在解散之前探 —— 一探就会被服务端判空回收，
            //      见上面那段注释；所以占位取证安排在这里）
            {
              const ev3 = [];
              let p3 = null;
              try {
                p3 = startProbe(CMD_FILE_Z, ev3, 'probeZ3d', UP);
                await waitProbeReady(ev3, 45000);
                const sq = probeCmd('occupy_probe_only', { room: ROOM_W }, CMD_FILE_Z);
                const r3 = await waitProbeResult(ev3, sq, 40000).catch((e) => ({ ok: false, error: e.message }));
                check(!!r3 && r3.seats === 2,
                  '★ 9t 第二次邀战建的那间房里**坐着 A3 + B3 两个人**（第三者被「房间已满」挡住）',
                  { seats: r3 && r3.seats, ack: r3 && r3.ack });
              } finally { killProbe(p3); }
            }
          }
        }
        capture.scenario3 = { roomZ: ROOM_Z, roomW: ROOM_W, invite1: body3, invite2: body4,
          closeRoomAck: closeAck, seatsAfterProbeLeft: capture.seatsAfterProbeLeft,
          afterBack: { screens: afterBack.activeScreens, roomId: afterBack.gs.roomId },
          afterDisband: { roomId: afterDisband.gs.roomId, screens: afterDisband.activeScreens,
                          panel: afterDisband.waitingPanel } };
      }
    }
  }

  // ---- 10. 页面零异常 ----
  check(jsProblems.length === 0, '★ 10 全程零 JS 异常 / 零 console.error', jsProblems.slice(0, 6));

  try {
    await A.screenShot(path.join(TMP, 'invite_' + MODE + '_A_final.png'));
    await B.screenShot(path.join(TMP, 'invite_' + MODE + '_B_final.png'));
    console.log('截图: .tmp/invite_' + MODE + '_A_final.png / _B_final.png');
  } catch (e) { /* 截图失败不影响结论 */ }

  capture.socketFramesA = A.socketFrames;
  capture.socketFramesB = B.socketFrames;
  capture.clientSockA = await A.ev('window.__inviteSock || []');
  capture.clientSockB = await B.ev('window.__inviteSock || []');
} catch (err) {
  failures.push({ label: '工具中断: ' + err.message, detail: null });
  console.error('!! 检查中断: ' + err.message);
} finally {
  killAllProbes();
  if (A) A.close();
  if (B) B.close();
  capture.fingerprintsAfter = { gamejs: fingerprint(path.join(ROOT, 'static', 'game.js')),
    apipy: fingerprint(path.join(ROOT, 'api.py')),
    serverpy: fingerprint(path.join(ROOT, 'server.py')) };
  capture.parallelEditWarning = capture.fingerprintsBefore.gamejs.sha256 !== capture.fingerprintsAfter.gamejs.sha256
    ? '⚠️ static/game.js 在本次运行期间被改动过（并行编辑）：结果可能读到半截文件' : 'none';
  capture.passes = passes;
  capture.failures = failures;
  capture.jsProblems = jsProblems;
  capture.endedAt = new Date().toISOString();
  try {
    fs.writeFileSync(JSON_OUT, JSON.stringify(capture, null, 1), 'utf8');
    console.log('\n取证 JSON: ' + JSON_OUT);
  } catch (e) { /* ignore */ }

  console.log('\n================ SUMMARY (' + MODE + ') ================');
  console.log('通过 ' + passes.length + ' / 不通过 ' + failures.length);
  failures.forEach((f) => console.log('  FAIL - ' + f.label
    + (f.detail === undefined || f.detail === null ? '' : '  ->  ' + JSON.stringify(f.detail))));
  if (capture.parallelEditWarning !== 'none') console.log('  ' + capture.parallelEditWarning);
  process.exit(0);
}
