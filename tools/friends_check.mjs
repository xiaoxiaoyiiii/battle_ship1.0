#!/usr/bin/env node
/**
 * 好友功能 UI 回归检查（无头 Edge + CDP，全部断言真实 DOM）。
 *
 * 覆盖（票面 8 条 + 好友批补的开关）：
 *   1. 首页有 #friends-btn；点开 #friends-modal 可见；GET /api/friends **点之前不该有请求**
 *      （用 CDP 的 Fetch 域数请求，不是"看着像"）。
 *   2. 两个真账号：A 给 B 发申请 → B 的页面收到 friend_request → 红点 == 接口 counts.incoming
 *      → B 打开面板看到待确认 → B 点接受 → 双方列表里都有对方。
 *   3. 邀战真链路：B 点 A 的「邀战」→ A 的 socket 真的收到 friend_invite
 *      → B 的页面弹出 #friend-invite-toast → 点 #friend-invite-enter **真的进了同一个房间**
 *      （断言页面上的房间号 == 接口给的 room_id）。
 *   4. 删除好友后两边列表都空。
 *   5. 未登录（全新 profile，无 cookie）点「加好友」→ 提示「请先登录」，且**没有 401 刷屏**。
 *   6. 390x844 视口下：面板不横向溢出、行不被压住（矩形采样 + elementFromPoint 遮挡探针）。
 *   7. 全程零 JS 异常 / 零 console.error。
 *   8. 数字与文案一致性：红点数字取自接口 counts.incoming（在页面里现取接口对照），**不写死**。
 *   9. **T9「允许他人加我好友」开关**（决策④的后半句）：默认勾上 → 取消勾选保存（抓请求体，
 *      必须是 11 个字段且 friend_requests_open=0）→ 关掉后 A 发申请 **403** 且 B 的 incoming
 *      里没有 A（**两侧都断言**）→ **刷新后仍关着** → 勾回来恢复成开并再验一次 200/sent。
 *      为什么单独立一段：这个开关的失败形状**全是静默的**（见 T9 那段的注释）。
 *
 * 用法：
 *   node tools/friends_check.mjs --url http://127.0.0.1:5101/
 *                               [--db <隔离库>] [--shot <png>] [--stub] [--keep-open]
 *
 * ⚠️ 服务端必须带 CORS_ORIGINS=http://127.0.0.1:<端口>，否则 socket.io **静默连不上**
 *    （页面无报错，只是所有 socket 断言全成假红）。
 * ⚠️ 只在**隔离库**的本地服务上跑：它会注册 friendschk_* 账号并真的写好友关系。
 *    默认库路径 <repo>/.tmp/friends_ui.db（要与服务端 BATTLESHIP_DB_PATH 指向同一份）。
 * ⚠️ 降级说明（**现状**：好友批的接口已全部上线、本工具实测全绿）：万一 /api/friends
 *    探测不可用（旧分支 / 只起了半个后端），本工具仍会自动降级为离线 UI 检查
 *    （用 CDP 的 Fetch 域伪造一份符合冻结契约的响应，只验渲染/红点/窄屏/零异常），
 *    网络类断言报 SKIP 并在结尾明确列出来 —— 绝不把"接口还没有"伪装成 PASS。
 *    想显式强制离线模式：加 --stub。
 */

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

// ---------- 参数 ----------
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5101/').replace(/\/?$/, '/');
const SHOT = argOf('--shot', '');
const FORCE_STUB = argv.includes('--stub');

let HERE;
try { HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')); }
catch (e) { HERE = process.cwd(); }
const ROOT = path.resolve(HERE, '..');
const TMP = path.join(ROOT, '.tmp');
const DB = argOf('--db', path.join(TMP, 'friends_ui.db'));
const PORT = 9361;
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(TMP, 'friends_check_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳好友检查'); process.exit(0); }
fs.mkdirSync(TMP, { recursive: true });

// ---------- 预清理：残留的无头进程会占着调试端口 + 锁住 profile ----------
// （不清的话新浏览器**静默起不来**，工具连上的是上一轮的旧实例 → 查不出所以然的假红）
try {
  spawnSync('powershell', ['-NoProfile', '-Command',
    'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
    'Where-Object { $_.CommandLine -like \'*friends_check_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'],
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没有残留就够 */ }

// ---------- 断言账本 ----------
const passes = [];
const failures = [];
const skips = [];
const jsProblems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label +
    (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (ok) passes.push(label); else failures.push(label);
}
function skip(label, why) {
  console.log('SKIP  ' + label + '  ->  ' + why);
  skips.push(label + ' (' + why + ')');
}

// ---------- 账号 ----------
const SUFFIX = String(Date.now()).slice(-6);
const PW = 'check123456';
const A = 'friendschk_a' + SUFFIX;     // python 侧（socket 旁观 + 发起邀战的人）
const B = 'friendschk_b' + SUFFIX;     // 浏览器里的那个人
const TARGET_USER = 'friendschk_t' + SUFFIX;   // 只是"被游客点加好友"的靶子账号

// ---------- 离线模式用的假响应（**严格照冻结契约的形状**） ----------
const STUB_FRIENDS = {
  friends: [
    { user_id: 9001, username: 'stub_online', avatar: '/static/avatars/default.png', level: 7, rank_label: '水手长Ⅱ 90分', online: true, in_game: false },
    { user_id: 9002, username: 'stub_ingame', avatar: '/static/avatars/default.png', level: 12, rank_label: '船长Ⅰ 2100分', online: true, in_game: true },
    { user_id: 9003, username: 'stub_offline', avatar: '/static/avatars/default.png', level: 3, rank_label: '二级水手Ⅰ 30分', online: false, in_game: false }
  ],
  incoming: [{ user_id: 9101, username: 'stub_wants_in', avatar: '/static/avatars/default.png', created_at: Math.floor(Date.now() / 1000) }],
  outgoing: [{ user_id: 9201, username: 'stub_i_asked', avatar: '/static/avatars/default.png', created_at: Math.floor(Date.now() / 1000) }],
  limits: { max_friends: 50, requests_per_hour: 20 },
  counts: { friends: 3, incoming: 1 }
};

// ---------- 服务端探测：/api/friends 上线了没有 ----------
async function probeFriendsApi(cookie) {
  const headers = { 'Accept': 'application/json' };
  if (cookie) headers['Cookie'] = cookie;
  try {
    const r = await fetch(APP + 'api/friends', { headers });
    const text = await r.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch (e) { body = null; }
    const usable = !!(body && (Array.isArray(body.friends) || Array.isArray(body.incoming) || Array.isArray(body.outgoing)));
    return { status: r.status, usable: usable, guest: r.status === 401 };
  } catch (e) {
    return { status: 0, usable: false, guest: false, error: String(e && e.message) };
  }
}

// ---------- Node 侧的账号辅助（注册 + 登录 + 拿 cookie） ----------
//
// ⚠️ 这里有个坑（实测踩过）：**登录失败也会种 session cookie**（那次响应里带的是
//    "用户名或密码错误"的 flash）。所以"拿到了 cookie"根本不等于"登录成功了"——
//    必须拿它去 /api/profile 反查一次 username 才算数。否则后面所有以该身份发起的
//    请求全是 401，而现象是"断言莫名其妙地红"，很难往回追。
//
// ⚠️⚠️ 第二个坑（2026-09-19 私聊批实测）：`api.py` 对 `/login` 有**同 IP 限流**
//    （`_rate_limited('login')`，60 秒窗口内 10 次）。超了之后 `/login` 回 302 到
//    `/login` 并 flash「操作过于频繁，请稍后再试」—— 于是"cookie 拿到了但 /api/profile
//    是 401"，本工具会**静默降级成离线模式**（探测那一步判成"接口没上线"、全链路那几条
//    被 SKIP 或判红），而真正的原因跟前后端都没关系。
//    本工具跑一次要登录 3~4 个账号（探针 + 靶子 + A + B），和别的工具一起跑很容易撞上
//    （大家共用 127.0.0.1 这一个 remote_addr）。所以登录要**认得出被限流**并等窗口过去。
const LOGIN_BUSY_RE = /操作过于频繁/;

// 一次登录尝试。返回 {setCookie, ok, limited}
// 判据用**响应正文里的 flash**，不用 Location（flash 只在那一次渲染里出现，
// 而 `redirect: 'manual'` 拿到的正文里恰好带着它）。
async function loginAttempt(base, username) {
  const r = await fetch(base + 'login', {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: username, password: PW }).toString()
  });
  const text = await r.text().catch(() => '');
  return { setCookie: readCookie(r), limited: LOGIN_BUSY_RE.test(text), http: r.status };
}

async function nodeAuth(base, username) {
  const verify = async (cookie) => {
    if (!cookie) return '';
    try {
      const r = await fetch(base + 'api/profile', { headers: { Accept: 'application/json', Cookie: cookie } });
      if (!r.ok) return '';
      const body = await r.json();
      const me = body && body.profile ? String(body.profile.username || '') : '';
      return me === username ? cookie : '';
    } catch (e) { return ''; }
  };
  const register = () => fetch(base + 'register', {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: username, password: PW }).toString()
  });
  // ⚠️ 顺序很要紧：**先注册**。`/register` 也走同一套 IP 限流，但注册成功时它会
  //    **直接种好 session**（api.py 里 `session['user_id'] = uid`），所以正常路径下
  //    一次 `/login` 都不用发 —— 省配额，也避免"先试登录（账号还不存在，白扣一次配额）"。
  // ⚠️ 但**只注册一次**：第二次同一账号再去 /register 会回「用户名已存在」并且**不会**
  //    种 session（第一版写成"注册 4 次"就是这样白等 20 秒的）。之后一律走登录重试。
  const reg = await register();
  let cookie = await verify(readCookie(reg));
  if (cookie) return cookie;
  // 被限流多久就等多久：窗口是 60 秒，最多等 ~70 秒（宁可慢，也别把"限流"误判成"登不上"）。
  // ⚠️ 只有"限流"才值得等：登录**成功但 cookie 没用**（或账号真有问题）时死等 70 秒
  //    只会把一次假红拖成一次很慢的假红，所以那种情况直接退出循环、让调用方的断言说话。
  for (let i = 0; i < 14; i++) {
    await sleep(5000);
    const a = await loginAttempt(base, username);
    cookie = await verify(a.setCookie);
    if (cookie) return cookie;
    if (!a.limited) break;
  }
  return '';   // 真没登进去（调用方的断言会红，不是静默假绿）
}
function readCookie(resp) {
  const raw = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [resp.headers.get('set-cookie')].filter(Boolean);
  const pairs = raw.map((c) => String(c).split(';')[0]).filter(Boolean);
  return pairs.length ? pairs.join('; ') : '';
}

// ---------- python 侧的 A：真登录 + 真 socket（收 friend_invite / friend_request） ----------
const PY_HELPER = path.join(TMP, 'friends_check_peer.py');
const CMD_FILE = path.join(TMP, 'friends_check_cmd.json');
fs.writeFileSync(PY_HELPER, String.raw`
# -*- coding: utf-8 -*-
"""friends_check.mjs 用的 python 侧玩家：真登录 + 真 socket，等命令文件干活。

命令文件（JSON）：{"seq":1,"cmd":"request","to":"xxx"} / {"cmd":"respond","to":"xxx","accept":true}
  cmd=request → POST /api/friends/request 并发一条 socket 事件给浏览器那一侧（服务端转发的）
  cmd=respond → POST /api/friends/respond
  cmd=mkroom  → 用 socket 建一个自定义房，回执里带 room_id（"邀战的房间归 A"）
stdout：每行一个 JSON，node 侧逐行读。
"""
import json, os, sys, time
import requests
import socketio

base, username, password, cmd_file = sys.argv[1:5]
base = base.rstrip('/') + '/'

def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)

s = requests.Session()

def is_logged_in():
    """靠 /api/profile 反查，不靠响应正文里有没有「登录成功」那句话。

    ⚠️ 这是个真踩过的坑：/login 与 /register 成功后都是 redirect，跟随后拿到的是首页，
    而 flash 消息只在**紧接着的那一次**渲染里出现 —— 再打第二个请求就看不见了，
    于是「正文里有没有登录成功」会把**已经登录成功**误判成失败（本工具第一版就这样，
    A 侧一路 401，全链路那几条全红）。
    """
    try:
        r = s.get(base + 'api/profile', timeout=10)
        if r.status_code != 200:
            return False
        body = r.json()
        return bool(body.get('profile'))
    except Exception:
        return False

def do_login():
    return s.post(base + 'login', data={'username': username, 'password': password}, allow_redirects=True)

do_login()
if not is_logged_in():
    s.post(base + 'register', data={'username': username, 'password': password}, allow_redirects=True)
    do_login()

cookie = '; '.join('%s=%s' % (k, v) for k, v in s.cookies.get_dict().items())
out({'event': 'login', 'ok': is_logged_in(), 'user': username})

sio = socketio.Client(reconnection=False)

@sio.on('friend_invite')
def on_invite(data):
    out({'event': 'friend_invite', 'data': data})

@sio.on('friend_request')
def on_request(data):
    out({'event': 'friend_request', 'data': data})

@sio.on('friend_accepted')
def on_accepted(data):
    out({'event': 'friend_accepted', 'data': data})

@sio.on('recent_opponent')
def on_recent(data):
    out({'event': 'recent_opponent', 'data': data})

@sio.on('error')
def on_error(data):
    out({'event': 'socket_error', 'data': data})

sio.connect(base.rstrip('/'), headers={'Cookie': cookie}, wait_timeout=20)
out({'event': 'ready'})

last = 0
t0 = time.time()
while time.time() - t0 < 300:
    time.sleep(0.25)
    try:
        if not os.path.exists(cmd_file):
            continue
        st = os.stat(cmd_file).st_mtime
        if st == last:
            continue
        last = st
        with open(cmd_file, 'r', encoding='utf-8') as f:
            job = json.load(f)
    except Exception:
        continue
    cmd = job.get('cmd')
    seq = job.get('seq')
    if cmd == 'quit':
        out({'event': 'bye', 'seq': seq}); break
    try:
        if cmd == 'request':
            r2 = s.post(base + 'api/friends/request', json={'username': job.get('to', '')}, timeout=10)
            body = None
            try: body = r2.json()
            except Exception: body = {'raw': r2.text[:200]}
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': r2.status_code, 'body': body})
        elif cmd == 'mkroom':
            # 用 socket 建一个自定义房并**坐在里面**：这样"邀战的房间"归 A，
            # 浏览器那一侧入房时才是真的"第二个人进来"（浏览器自己建的房会把自己的座位占住，
            # join_room 直接回"房间已满" —— 这个坑实测踩过）。
            box = {}
            def _ack(resp):
                box['resp'] = resp
            sio.emit('create_room', {}, callback=_ack)
            t0 = time.time()
            while 'resp' not in box and time.time() - t0 < 10:
                time.sleep(0.2)
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': 200, 'body': box.get('resp') or {'error': 'no-ack'}})
        elif cmd == 'respond':
            r2 = s.post(base + 'api/friends/respond',
                        json={'username': job.get('to', ''), 'accept': bool(job.get('accept'))}, timeout=10)
            body = None
            try: body = r2.json()
            except Exception: body = {'raw': r2.text[:200]}
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': r2.status_code, 'body': body})
        elif cmd == 'invite':
            r2 = s.post(base + 'api/friends/invite', json={'username': job.get('to', '')}, timeout=10)
            body = None
            try: body = r2.json()
            except Exception: body = {'raw': r2.text[:200]}
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': r2.status_code, 'body': body})
        else:
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': 0, 'body': {'error': 'unknown cmd'}})
    except Exception as e:
        out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': 0, 'body': {'error': str(e)}})

try:
    sio.disconnect()
except Exception:
    pass
`, 'utf8');

let peer = null;
const peerEvents = [];
function startPeer() {
  try { fs.unlinkSync(CMD_FILE); } catch (e) { /* 没有就够 */ }
  const p = spawn('python', [PY_HELPER, APP, A, PW, CMD_FILE], {
    cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, stdio: ['ignore', 'pipe', 'pipe']
  });
  let buf = '';
  p.stdout.on('data', (d) => {
    buf += d.toString('utf8');
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line.startsWith('{')) continue;
      try { peerEvents.push(JSON.parse(line)); } catch (e) { /* 忽略非 JSON 行 */ }
    }
  });
  p.stderr.on('data', (d) => {
    const s = d.toString('utf8');
    if (/Traceback|Error/.test(s)) jsProblems.push('python 侧: ' + s.replace(/\s+/g, ' ').slice(0, 220));
  });
  return p;
}
let cmdSeq = 0;
function peerCmd(cmd, extra) {
  const seq = ++cmdSeq;
  const payload = Object.assign({ seq: seq, cmd: cmd }, extra || {});
  fs.writeFileSync(CMD_FILE, JSON.stringify(payload), 'utf8');
  return seq;
}
async function waitPeerCmd(seq, timeout) {
  return waitFor(() => peerEvents.find((e) => e.event === 'cmd_result' && e.seq === seq), timeout, 'python 侧命令回执 #' + seq);
}
async function waitPeerEvent(name, timeout, since) {
  const from = since === undefined ? 0 : since;
  return waitFor(() => {
    const idx = peerEvents.findIndex((e, i) => i >= from && e.event === name);
    return idx >= 0 ? peerEvents[idx] : null;
  }, timeout, 'python 侧收到 ' + name);
}

// ---------- CDP ----------
let browser = null, ws = null, seq = 0;
const pending = new Map();
let friendsRequestCount = 0;       // 打到 /api/friends 的次数（用来验"点之前不该有请求"）
let profileCardBodies = [];        // 抓到的 POST /api/profile/card 请求体（T9 用它数保存载荷字段）
let stubEnabled = false;           // 离线模式下伪造 GET /api/friends
let guestMode = false;             // 游客模式：登录接口一律 401（验"请先登录"那条）

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
  });
}
async function ev(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('页面异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result && r.result.value;
}
async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeout) {
    try { last = await fn(); if (last) return last; } catch (e) { last = 'err:' + e.message; }
    await sleep(120);
  }
  throw new Error('等待超时: ' + label + '  (最后 ' + JSON.stringify(last) + ')');
}
async function goto(url, waitHref) {
  await send('Page.navigate', { url });
  const want = (waitHref || url).replace(/\/$/, '');
  await waitFor(async () => {
    const st = await ev('({ href: location.href.replace(/\\/$/, ""), ready: document.readyState })');
    return st && st.ready === 'complete' && st.href === want;
  }, 30000, '页面加载 ' + url);
  await sleep(500);
}
async function setViewport(w, h, dsf, mobile) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dsf || 1, mobile: !!mobile });
  await sleep(350);
}
async function clickJs(selectorExpr) {
  const r = await ev('(function(){ var el = ' + selectorExpr + '; if (!el) return {ok:false,why:"not-found"};'
    + ' el.click(); return {ok:true}; })()');
  if (!r || !r.ok) throw new Error('点击失败 ' + selectorExpr + ' -> ' + JSON.stringify(r));
  return r;
}
async function setCookie(c) {
  const u = new URL(APP);
  const pairs = String(c).split(';').map((s) => s.trim()).filter(Boolean);
  for (const p of pairs) {
    const i = p.indexOf('=');
    if (i < 0) continue;
    await send('Network.setCookie', {
      name: p.slice(0, i), value: p.slice(i + 1),
      domain: u.hostname, path: '/', url: APP
    });
  }
}
async function clearCookies() {
  try { await send('Network.clearBrowserCookies'); } catch (e) { /* 没开 Network 域就够 */ }
}

// 遮挡探针：矩形内多点采样 elementFromPoint，看有没有别的东西压在上面
const PROBE = (sel) => '(function(){'
  + 'var el = document.querySelector(' + JSON.stringify(sel) + ');'
  + 'if (!el) return {present:false};'
  + 'var cs = getComputedStyle(el);'
  + 'if (cs.display === "none" || cs.visibility === "hidden") return {present:false, hidden:true};'
  + 'var r = el.getBoundingClientRect();'
  + 'if (r.width <= 0 || r.height <= 0) return {present:false, zero:true};'
  + 'var samples = 0, occluded = 0, worst = null;'
  + 'for (var i = 1; i <= 3; i++) for (var j = 1; j <= 3; j++) {'
  + '  var x = r.left + r.width * i / 4, y = r.top + r.height * j / 4;'
  + '  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;'
  + '  samples++;'
  + '  var t = document.elementFromPoint(x, y);'
  + '  if (!t) { occluded++; continue; }'
  + '  if (t === el || el.contains(t) || t.contains(el)) continue;'
  + '  occluded++; worst = (t.id || t.className || t.tagName) + "";'
  + '}'
  + 'return {present:true, samples:samples, occluded:occluded, worst:worst,'
  + '  rect:{x:Math.round(r.left),y:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)}};'
  + '})()';

// ---------- T6：390x844 窄屏检查（拆出来是因为两种模式都要在"最后"跑一次） ----------
//
// ⚠️ 顺序有讲究：必须在**面板里已经有行**的时候量。
//    第一版它在全链路之前跑，那时面板是空的 → 行溢出/行被压这类断言因为"没有行"而假绿，
//    遮挡探针则因为"没有行"而红。两头都不可信，所以现在统一放到各自的最后。
async function checkNarrowPanel() {
  await setViewport(390, 844, 3, true);
  // 面板若是关着的就点开（离线模式那一段结束时它是开着的，这里点开关两次也无害）
  const open = await ev('!document.getElementById("friends-modal").classList.contains("hidden")');
  if (!open) await clickJs('document.getElementById("friends-btn")');
  await sleep(1200);

  const narrow = await ev(`(function(){
    var m = document.getElementById('friends-modal');
    var c = m.querySelector('.modal-content');
    var de = document.documentElement;
    var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row, #friends-requests .friend-row, #friends-outgoing .friend-row'));
    var r = c.getBoundingClientRect();
    return {
      rows: rows.length,
      contentRect: { x: Math.round(r.left), w: Math.round(r.width), right: Math.round(r.right) },
      vw: innerWidth,
      docScrollW: de.scrollWidth,
      bodyScrollW: document.body.scrollWidth,
      rowOverflow: rows.filter(function(x){ return x.getBoundingClientRect().right > innerWidth + 1; }).length,
      rowZero: rows.filter(function(x){ var b=x.getBoundingClientRect(); return b.width <= 0 || b.height <= 0; }).length
    }; })()`);
  // 先确认"确实有行可量"：没有行的话后面几条全是空转
  check(narrow.rows > 0, '★ T6-0 390x844 下面板里真的有行可量（没行的话下面几条都是空转）', narrow.rows);
  check(narrow.docScrollW <= narrow.vw + 1 && narrow.bodyScrollW <= narrow.vw + 1,
    '★ T6a 390x844 下面板不产生横向溢出', narrow);
  check(narrow.rowOverflow === 0, '★ T6b 390x844 下没有一行伸出视口右边', narrow.rowOverflow);
  check(narrow.rowZero === 0, '★ T6c 390x844 下没有行被压成 0 尺寸', narrow.rowZero);

  // 遮挡探针：矩形内 3x3 采样 elementFromPoint，看有没有别的东西压在上面
  const probeRow = await ev(PROBE('#friends-list .friend-row'));
  check(probeRow && probeRow.present && probeRow.occluded === 0,
    '★ T6d 390x844 下好友行没有被别的东西压住（elementFromPoint 采样）', probeRow);
  const probeBtn = await ev(PROBE('#friends-list .friend-row [data-friend-action="invite"]'));
  check(probeBtn && probeBtn.present && probeBtn.occluded === 0,
    '★ T6e 390x844 下「邀战」按钮可点（没被压住）', probeBtn);

  await setViewport(1400, 900, 1, false);
}

// ---------- 主流程 ----------
async function main() {
  console.log('== 好友功能 UI 回归检查 ==');
  console.log('   APP  = ' + APP);
  console.log('   DB   = ' + DB);
  console.log('   B    = ' + B + '（浏览器）   A = ' + A + '（python socket 侧）');

  // ⚠️ 探测 /api/friends **必须先带一个真登录的 cookie**：契约里未登录就是 401，
  //    不带 cookie 去探会把"接口其实好着呢"判成"接口没上线"（我第一版就栽在这上面 ——
  //    离线模式悄悄跑了一遍，全链路那几条全被 SKIP 掉了，看着还挺绿）。
  //    所以：先登录一个探针账号，用它反查；仍不可用才是真的没上线。
  const cookieProbe = await nodeAuth(APP, A);
  const probe = await probeFriendsApi(cookieProbe);
  const offline = FORCE_STUB || !probe.usable;
  console.log('   /api/friends 探测（带登录 cookie）：HTTP ' + probe.status + '，可用=' + probe.usable
    + (offline ? '  → 走【离线 UI 模式】（网络类断言报 SKIP）' : '  → 走【全链路模式】'));
  console.log('');

  // ---------- 起浏览器 ----------
  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--no-proxy-server', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=1400,900', '--force-device-scale-factor=1',
    'about:blank'], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^(https?|about|file):/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还在启动 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });

  let msgSeq = 0;
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') {
      jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 220));
      const ex = m.params.exceptionDetails || {};
      const desc = (ex.exception && (ex.exception.description || ex.exception.value)) || ex.text;
      console.log('   [异常详情] ' + String(desc).slice(0, 700));
      if (ex.stackTrace && ex.stackTrace.callFrames) {
        console.log('   [调用栈] ' + ex.stackTrace.callFrames.slice(0, 6)
          .map((f) => (f.functionName || '?') + '@' + f.lineNumber).join(' <- '));
      }
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 180));
    }
    // ---- Network 域：抓 POST /api/profile/card 的**请求体**（T9 数保存载荷字段） ----
    // ⚠️ 用 Network.requestWillBeSent 而不是 Fetch：Fetch 那边被 `Fetch.requestPaused`
    //    占据着数 /api/friends 与伪造响应，而 `request.postData` 在这一条上就是原文 ——
    //    不需要再 getRequestPostData，也不会和 Fetch 的 continueRequest 抢 requestId。
    if (m.method === 'Network.requestWillBeSent') {
      const req = m.params.request || {};
      if (/\/api\/profile\/card$/.test(String(req.url || '')) && req.postData) {
        try { profileCardBodies.push(JSON.parse(req.postData)); }
        catch (e) { profileCardBodies.push({ __parseFail: String(req.postData).slice(0, 400) }); }
      }
    }
    // ---- Fetch 域：数 /api/friends 的请求 + 离线时伪造响应 ----
    if (m.method === 'Fetch.requestPaused') {
      const req = m.params.request || {};
      const url = String(req.url || '');
      const isFriends = /\/api\/friends(\?|$)/.test(url);
      const isLoginApi = /\/api\/(login|register)/.test(url);
      if (isFriends) friendsRequestCount += 1;
      if (guestMode && isLoginApi) {
        send('Fetch.fulfillRequest', {
          requestId: m.params.requestId, responseCode: 401,
          responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
          body: Buffer.from(JSON.stringify({ status: 'error', error: '请先登录' })).toString('base64')
        }).catch(() => {});
        return;
      }
      if (stubEnabled && isFriends && req.method === 'GET') {
        send('Fetch.fulfillRequest', {
          requestId: m.params.requestId, responseCode: 200,
          responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
          body: Buffer.from(JSON.stringify(STUB_FRIENDS)).toString('base64')
        }).catch(() => {});
        return;
      }
      // 游客那条断言：查看面要先把别人的名片渲染出来才能点到「加好友」，
      // 而 /user_stats 对游客是 401。这里只是把"关系"这一路喂成 'none'
      // （真实的 401 行为由 /api/friends 自己返回，不造假）。
      if (guestMode && isFriends && req.method === 'GET') {
        send('Fetch.fulfillRequest', {
          requestId: m.params.requestId, responseCode: 200,
          responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
          body: Buffer.from(JSON.stringify({ friends: [], incoming: [], outgoing: [] })).toString('base64')
        }).catch(() => {});
        return;
      }
      send('Fetch.continueRequest', { requestId: m.params.requestId }).catch(() => {});
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  // 两种模式都开 Fetch 域：全链路模式只为**数请求**，离线模式还要伪造响应。
  await send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
  await setViewport(1400, 900, 1, false);

  // 先把两个"陪跑"的真账号造出来（与 /api/friends 在不在无关）：
  //   TARGET_USER —— 游客那条断言要有一个真实存在的"被加的人"，否则 /user_stats 返回
  //                  stats:null，查看面渲染不出名片，也就点不到「加好友」。
  //   A           —— python 侧那个 socket 玩家（T2/T3 用）。
  const cookieTarget = await nodeAuth(APP, TARGET_USER);
  check(!!cookieTarget, 'T0a 真账号靶子已就绪（游客那条断言要它存在）', TARGET_USER);
  check(!!cookieProbe, 'T0b python 侧账号 A 已就绪（真登录，cookie 反查过 username）', A);

  // ---------- T1 游客态：入口存在、点之前零请求 ----------
  // ⚠️ 必须先清 cookie：浏览器用的是**持久 profile**，上一轮跑完会留着 B 的 session。
  //    不清的话"游客断言"其实是以已登录身份跑的 —— 那次点「加好友」真的发出去了，
  //    于是「请先登录」永远等不到，而那看起来像前端没提示（第 10 节第 15 条：
  //    工具假红先怀疑工具）。
  await clearCookies();
  await goto(APP);
  check(await ev('!!document.getElementById("friends-btn")'),
    '★ T1a 首页存在 #friends-btn（入口）');
  check(await ev('!!document.getElementById("friends-badge")'),
    '★ T1b 入口上存在 #friends-badge（红点）');
  const badgeHiddenAtStart = await ev('document.getElementById("friends-badge").classList.contains("hidden")');
  check(badgeHiddenAtStart === true, 'T1c 初始红点隐藏（没有待确认申请时不显示 0）', badgeHiddenAtStart);

  const requestsBeforeClick = friendsRequestCount;
  check(requestsBeforeClick === 0,
    '★ T1d 页加载时**没有**请求过 /api/friends（只在点开面板时才拉）', requestsBeforeClick);

  // 游客点开面板：面板必须可见（且要在 401 之后仍然可用）
  const guestModal = await ev(`(function(){
    document.getElementById('friends-btn').click();
    var m = document.getElementById('friends-modal');
    return { shown: !m.classList.contains('hidden'), display: getComputedStyle(m).display };
  })()`);
  check(guestModal.shown === true && guestModal.display !== 'none',
    '★ T1e 点 #friends-btn 后 #friends-modal 可见', guestModal);
  const requestsAfterClick = await waitFor(() => (friendsRequestCount > 0 ? friendsRequestCount : null), 8000, '点开面板后打到 /api/friends')
    .catch(() => friendsRequestCount);
  check(requestsAfterClick >= 1, '★ T1f 点开面板后**真的**请求了 GET /api/friends', requestsAfterClick);

  // 关闭按钮
  await clickJs('document.getElementById("friends-close")');
  const closed = await ev('document.getElementById("friends-modal").classList.contains("hidden")');
  check(closed === true, 'T1g 点 #friends-close 后面板收起', closed);

  // ---------- T5 游客点「加好友」→ 请先登录，且不刷屏 ----------
  // 契约：未登录一律 401。前端要把它变成「请先登录」，而且**不能**因为 401 反复重试。
  // ⚠️ 这里不伪造任何东西：查看面的「加好友」按钮要点得到，所以先造一个**真实存在**的
  //    另一个账号当靶子（游客点它 → /api/friends/request 真吃 401）。
  // ⚠️ guestMode 只在这一段打开（它会把 GET /api/friends 喂成"没有关系"，
  //    这样查看面才渲染得出「加好友」；真实的 401 由写接口自己返回，不造假）。
  guestMode = true;
  try {
  const guestApiCountBefore = friendsRequestCount;
  const guestClick = await ev(`(function(){
    // 直接走前端真正的那条路径：打开一个别人的查看面，再点 #add-friend-btn。
    // （游客在 UI 上没有正常入口打开查看面，这里调的就是 game.js 自己那个函数 ——
    //   它才是"点加好友"的宿主。）
    if (typeof window.showUserProfile !== 'function') return {noFn:true};
    window.showUserProfile(${JSON.stringify(TARGET_USER)});
    return {called:true};
  })()`);
  const guestBtn = await waitFor(async () => {
    const has = await ev('!!document.getElementById("add-friend-btn")');
    return has ? true : null;
  }, 15000, '游客态下 #add-friend-btn 渲染出来').catch(() => false);
  if (guestClick && guestClick.noFn) {
    skip('★ T5 未登录点「加好友」提示「请先登录」', 'showUserProfile 没暴露到 window');
  } else if (!guestBtn) {
    // 渲染不出来时把容器内容抓回来 —— 否则这条只会显示"点了但没按钮"，看不出卡在哪
    const dump = await ev(`(function(){
      var c = document.getElementById('opponent-stats-content');
      var m = document.getElementById('opponent-stats-modal');
      return { modalOpen: m ? !m.classList.contains('hidden') : null,
               contentLen: c ? (c.textContent || '').length : null,
               contentHead: c ? (c.textContent || '').slice(0, 160) : null }; })()`);
    check(false, '★ T5 未登录也能渲染出 #add-friend-btn（否则这条断言无从下手）', dump);
  } else {
    await clickJs('document.getElementById("add-friend-btn")');
    // 提示位有两处：查看面里的 #guestbook-msg（showMessage 走 #game-message-container）。
    // 断言"整页任意位置出现了请先登录这句话"，不挑容器（容器由既有实现决定）。
    const seen = await waitFor(async () => {
      const t = await ev('document.body.innerText || ""');
      return /请先登录/.test(t) ? true : null;
    }, 8000, '页面上出现「请先登录」').catch(() => null);
    check(!!seen, '★ T5a 未登录点「加好友」→ 页面提示「请先登录」');

    await sleep(1500);
    const guestApiCountAfter = friendsRequestCount;
    // "刷屏"的判据：点了**一次**按钮，打出去的 /api/friends 请求次数不该明显增长
    // （前端若在 401 之后自动重试，这里会看到一串）。
    check(guestApiCountAfter - guestApiCountBefore <= 2,
      '★ T5b 401 之后没有请求刷屏（点一次最多多 1~2 次取数，没有自动重试风暴）',
      { before: guestApiCountBefore, after: guestApiCountAfter });
    // 关掉查看面，别影响后面的登录流程
    await ev('(function(){ var b=document.getElementById("opponent-stats-modal-close"); if (b) b.click(); return true; })()');
  }
  } finally {
    guestMode = false;    // 这段的口子只属于这一段，别把后面的流程一起喂了假响应
  }

  // ---------- 离线模式：伪造 /api/friends 验渲染 ----------
  if (offline) {
    stubEnabled = true;
    await goto(APP + '?offline=1');
    await clickJs('document.getElementById("friends-btn")');
    const rendered = await waitFor(async () => {
      const o = await ev(`(function(){
        return { rows: document.querySelectorAll('#friends-list .friend-row').length,
                 reqs: document.querySelectorAll('#friends-requests .friend-row').length,
                 outs: document.querySelectorAll('#friends-outgoing .friend-row').length,
                 emptyHidden: document.getElementById('friends-empty').classList.contains('hidden'),
                 badge: document.getElementById('friends-badge').textContent,
                 badgeHidden: document.getElementById('friends-badge').classList.contains('hidden') }; })()`);
      return o && o.rows > 0 ? o : null;
    }, 10000, '离线模式下渲染出好友行').catch(() => null);
    check(!!rendered,
      '★ T1h（离线模式）伪造一份契约响应后，三个分区按数据渲染出行', rendered);
    if (rendered) {
      // 顺序照服务端给的原样渲染：在线 → 对局中 → 离线
      const order = await ev(`(function(){
        return [].map.call(document.querySelectorAll('#friends-list .friend-row'), function(r){
          return (r.querySelector('.friend-name')||{}).textContent + '|' + (r.className||'');
        }); })()`);
      check(JSON.stringify(order.slice(0, 3)) === JSON.stringify([
        'stub_online|friend-row friend-online',
        'stub_ingame|friend-row friend-ingame',
        'stub_offline|friend-row friend-offline']),
        '★ T1i（离线模式）好友行按服务端给的顺序渲染（在线→对局中→离线）且状态类正确', order);
      check(rendered.reqs === 1 && rendered.outs === 1,
        'T1j（离线模式）待确认 / 我发出的两个分区各渲染一条', rendered);
      check(rendered.emptyHidden === true, 'T1k 有数据时 #friends-empty 隐藏', rendered.emptyHidden);
      check(rendered.badgeHidden === false && rendered.badge === String(STUB_FRIENDS.counts.incoming),
        '★ T8 红点数字 == 接口 counts.incoming（取自接口，不是写死）',
        { badge: rendered.badge, incoming: STUB_FRIENDS.counts.incoming });

      // 离线时「邀战」按钮必须禁用并写明原因
      const offlineInvite = await ev(`(function(){
        var row = document.querySelector('#friends-list .friend-row.friend-offline');
        if (!row) return null;
        var b = row.querySelector('[data-friend-action="invite"]');
        return b ? { disabled: b.disabled, title: b.title } : null; })()`);
      check(!!offlineInvite && offlineInvite.disabled === true && /不在线/.test(offlineInvite.title || ''),
        '★ T1l 离线好友的「邀战」按钮禁用，且 title 写明原因', offlineInvite);

      // 真正请求到接口（stub 也算，因为 stub 是被 Fetch 域拦下来的真实请求）
      const cnt = friendsRequestCount;
      check(cnt >= 1, 'T1m 面板每次打开都真的打了一次 /api/friends', cnt);

      // 「先清空再填充」的反面教材：重新打开一次面板，行数必须还是 3
      // （渲染函数若是一把把容器清空、失败时又没填回来，这里会看到 0）
      await clickJs('document.getElementById("friends-close")');
      await clickJs('document.getElementById("friends-btn")');
      await sleep(1200);
      const again = await ev('document.querySelectorAll("#friends-list .friend-row").length');
      check(again === 3, 'T1n 重新打开面板不会把上一帧清空（先清空再填充的反面教材）', again);
    }
  }

  // ---------- T6 390x844 窄屏：面板不横向溢出、行不被压住 ----------
  // ⚠️ 这条断言必须"面板里有行"才量得出东西（见 checkNarrowPanel 的说明）：
  //    离线模式在假数据下量，全链路模式在 T3 之后（好友关系还在时）量 ——
  //    绝不能放在"好友已经删光"之后，那时 rows:0，几条断言全是空转。
  if (offline) {
    await checkNarrowPanel();
    // 假数据只服务于渲染/布局类断言，全链路那一段一律走真接口
    stubEnabled = false;
  }

  // ---------- 全链路模式 ----------
  if (!offline) {
    console.log('');
    console.log('-- 全链路：两个真账号 --');

    // 浏览器侧登录 B（Node 侧注册/登录拿 cookie，再交给浏览器 —— 照 ranked_check 的写法）
    const cookieB = await nodeAuth(APP, B);
    check(!!cookieB, '★ T2a 注册/登录浏览器侧账号 B 并拿到 cookie', cookieB ? cookieB.split('=')[0] + '=…' : cookieB);
    await clearCookies();
    await setCookie(cookieB);
    await goto(APP);
    const meB = await ev('window.__USERNAME || null');
    check(meB === B, '★ T2b 浏览器页面认得当前登录用户是 B', meB);

    // socket 真的连上了吗（连不上时页面**不报错**，只是所有 socket 断言全成假红）
    await ev('(function(){ if (typeof ensureSocket === "function") ensureSocket(); return true; })()');
    const sockOk = await waitFor(async () => {
      const o = await ev('(function(){ return { has: !!gameState.socket, connected: gameState.socket ? gameState.socket.connected : false }; })()');
      return o && o.connected ? o : null;
    }, 15000, 'B 的页面 socket 连上服务端').catch(() => null);
    check(!!sockOk, '★ T2c B 的 socket 真的连上了（连不上时后面全是静默假红：CORS_ORIGINS 要放行本端口）', sockOk);

    // python 侧 A 起 socket
    peer = startPeer();
    const peerReady = await waitFor(() => peerEvents.find((e) => e.event === 'ready'), 30000, 'python 侧 A 登录并连上 socket').catch(() => null);
    check(!!peerReady, '★ T2d python 侧账号 A 真登录并连上 socket', peerReady || peerEvents.slice(-3));

    // 打开 B 的查看面（排行榜/局内头像都走它）—— 直接调 window.showUserProfile 是它的正经入口
    await ev('(function(){ window.showUserProfile(' + JSON.stringify(B) + '); return true; })()');
    await waitFor(async () => (await ev('!!document.getElementById("add-friend-btn")') ? true : null), 12000, '#add-friend-btn 渲染')
      .catch(() => null);
    const selfBtn = await ev(`(function(){
      var b = document.getElementById('add-friend-btn');
      return b ? { rel: b.dataset.relation, text: b.textContent } : null; })()`);

    // 红点基线 = 页面现取接口的 counts.incoming（**不写死**）
    const countsBefore = await ev(`fetch('/api/friends', {headers:{'Accept':'application/json'}})
      .then(function(r){ return r.json(); }).then(function(d){ return d && d.counts ? d.counts.incoming : null; })
      .catch(function(){ return null; })`);
    check(typeof countsBefore === 'number', '★ T8a 能从接口读到 counts.incoming（红点的唯一来源）', countsBefore);

    // ---- A 给 B 发申请（python 侧真发；服务端会转发一条 friend_request 给 B） ----
    const peerIdxBefore = peerEvents.length;
    const sendSeq = peerCmd('request', { to: B });
    const sendAck = await waitPeerCmd(sendSeq, 20000).catch(() => null);
    check(!!sendAck && sendAck.http < 400,
      '★ T2e python 侧 A 真的发出了好友申请（HTTP < 400）', sendAck);

    const evtInB = await waitFor(async () => {
      // handler 有没有注册（契约事件名必须一字不差）
      const names = await ev('(function(){ try { return Object.keys(gameState.socket._callbacks || {}); } catch(e){ return []; } })()');
      return Array.isArray(names) && names.some((k) => k.indexOf('friend_request') >= 0) ? names : null;
    }, 10000, '页面上注册了 friend_request 处理器').catch(() => null);
    check(!!evtInB, '★ T2f 页面注册了 socket 事件 friend_request（事件名与契约一字不差）',
      evtInB ? evtInB.filter((k) => /friend/.test(k)) : evtInB);

    // 等 B 页面的红点变成 1（这条路走的是真实服务端广播 + 前端 handler）
    const badgeAfter = await waitFor(async () => {
      const o = await ev(`(function(){
        var b = document.getElementById('friends-badge');
        return { text: b.textContent, hidden: b.classList.contains('hidden') }; })()`);
      return (o && !o.hidden && Number(o.text) > 0) ? o : null;
    }, 20000, 'B 的红点变成 1（收到 friend_request）').catch(() => null);
    // ⚠️ 这条红的**根因通常不在前端**：它要求服务端在 HTTP 接口里把 friend_request
    //    **推**出去（presence 登记 + emit），而"申请被写进库、列表里看得到"并不等于
    //    "事件推出来了"。所以失败时把 A 侧收到了什么一并打出来，一眼能看出卡在哪一半。
    check(!!badgeAfter, '★ T2g B 的页面收到 friend_request → 红点显示出来了',
      badgeAfter || { pythonSide: peerEvents.slice(-3),
        hint: '红点没亮 = 页面没收到 socket 事件。先确认服务端 /api/friends/request 里有没有真的 emit（列表里有申请、但事件没推，就是这个形状）' });
    if (badgeAfter && typeof countsBefore === 'number') {
      check(Number(badgeAfter.text) === countsBefore + 1,
        '★ T8b 红点数字 == 接口 counts.incoming（收到 1 条申请后应为 基线+1）',
        { badge: badgeAfter.text, before: countsBefore, expect: countsBefore + 1 });
    }

    // ---- B 打开面板看到待确认 → 点接受 ----
    await ev('(function(){ var b=document.getElementById("opponent-stats-modal-close"); if(b) b.click(); return true; })()');
    await clickJs('document.getElementById("friends-btn")');
    const incomingRow = await waitFor(async () => {
      const o = await ev(`(function(){
        var rows = [].slice.call(document.querySelectorAll('#friends-requests .friend-row'));
        return rows.map(function(r){ return r.dataset.username; }); })()`);
      return (o && o.indexOf(A) >= 0) ? o : null;
    }, 15000, 'B 的待确认分区里出现 A').catch(() => null);
    check(!!incomingRow, '★ T2h B 打开面板，「待确认」分区里能看到 A 的申请', incomingRow);

    await ev(`(function(){
      var rows = [].slice.call(document.querySelectorAll('#friends-requests .friend-row'));
      var row = rows.filter(function(r){ return r.dataset.username === ${JSON.stringify(A)}; })[0];
      if (!row) return false;
      var b = row.querySelector('[data-friend-action="accept"]');
      if (!b) return false;
      b.click(); return true; })()`);
    const bothFriends = await waitFor(async () => {
      const o = await ev(`(function(){
        var names = [].slice.call(document.querySelectorAll('#friends-list .friend-row')).map(function(r){ return r.dataset.username; });
        var reqs = document.querySelectorAll('#friends-requests .friend-row').length;
        return { names: names, reqs: reqs }; })()`);
      return (o && o.names.indexOf(A) >= 0) ? o : null;
    }, 20000, 'B 的好友列表里出现 A').catch(() => null);
    check(!!bothFriends, '★ T2i B 点「接受」后，B 的好友列表里有 A', bothFriends);
    check(!!bothFriends && bothFriends.reqs === 0, '★ T2j 接受之后「待确认」分区清空', bothFriends);

    // A 侧：用 A 的 cookie（T0b 就拿到的那个）直读一次接口，确认两边都对上了
    const listA = await fetch(APP + 'api/friends', { headers: { 'Accept': 'application/json', 'Cookie': cookieProbe } })
      .then((r) => r.json()).catch(() => null);
    const aHasB = !!(listA && Array.isArray(listA.friends) && listA.friends.some((f) => f.username === B));
    check(aHasB, '★ T2k A 侧（以 A 的身份直读接口）的好友列表里也有 B', listA ? (listA.friends || []).map((f) => f.username) : listA);

    // ---- T2l：查看面那个按钮的关系态（async 补上来那条路） ----
    // ⚠️ 这一段是在钉「不许把名片渲染拖慢」那条实现的另一面：名片先按 'none' 画出来
    //    （按钮显示「加好友」），真实关系是渲染完成之后**异步**补上去的。
    //    所以断言里要允许"先看到加好友、再变成好友"，最终状态必须是「好友 + 邀战」。
    await clickJs('document.getElementById("friends-close")');
    await ev(`(function(){ window.showUserProfile(${JSON.stringify(A)}); return true; })()`);
    const relState = await waitFor(async () => {
      const o = await ev(`(function(){
        var b = document.getElementById('add-friend-btn');
        var inv = document.querySelector('.fri-invite-btn');
        return { present: !!b, text: b ? b.textContent : null, rel: b ? b.dataset.relation : null,
                 disabled: b ? b.disabled : null, invite: !!inv }; })()`);
      return (o && o.rel === 'friends') ? o : null;
    }, 15000, '查看面按钮的关系态补成 friends').catch(() => null);
    if (!relState) {
      // 失败时把"现场"打回来：按钮在不在、卡片是谁、接口说是什么关系
      const dump = await ev(`(function(){
        var b = document.getElementById('add-friend-btn');
        var c = document.getElementById('opponent-stats-content');
        return { btn: b ? { text: b.textContent, rel: b.dataset.relation, user: b.dataset.username } : null,
                 inviteBtn: !!document.querySelector('.fri-invite-btn'),
                 cardName: (c && c.querySelector('#profile-view-name')) ? c.querySelector('#profile-view-name').textContent.trim() : null,
                 viewed: window.__viewedProfileName || null,
                 head: c ? (c.textContent || '').slice(0, 90) : null }; })()`);
      const apiRel = await ev(`fetch('/api/friends', {headers:{'Accept':'application/json'}}).then(function(r){return r.json();})
        .then(function(d){ return { friends: (d.friends||[]).map(function(f){return f.username;}) }; }).catch(function(e){ return 'err'; })`);
      console.log('   [T2l 现场] ' + JSON.stringify(dump) + '  接口: ' + JSON.stringify(apiRel));
      await sleep(4000);   // 再给 4 秒，看是不是"慢"而不是"错"
      const second = await ev(`(function(){
        var b = document.getElementById('add-friend-btn');
        var c = document.getElementById('opponent-stats-content');
        return { btn: b ? { text: b.textContent, rel: b.dataset.relation } : null,
                 inviteBtn: !!document.querySelector('.fri-invite-btn'),
                 head: c ? (c.textContent || '').slice(0, 50) : null }; })()`);
      console.log('   [T2l 再等 4 秒] ' + JSON.stringify(second));
    }
    check(!!relState && relState.text === '好友' && relState.disabled === true && relState.invite === true,
      '★ T2l 已是好友时查看面显示「好友」（禁用）+ 旁边出现「邀战」按钮', relState);
    await ev('(function(){ var b=document.getElementById("opponent-stats-modal-close"); if(b) b.click(); return true; })()');

    // ---- T3 邀战真链路 ----
    // 先把查看面关掉，回到首页（邀战提示条是 fixed 的，任何屏都能弹）
    await clickJs('document.getElementById("friends-close")');
    // B 点 A 那一行的「邀战」
    await clickJs('document.getElementById("friends-btn")');
    await waitFor(async () => (await ev('document.querySelectorAll("#friends-list .friend-row").length > 0') ? true : null), 10000, 'B 的好友行').catch(() => null);
    const peerIdxBeforeInvite = peerEvents.length;
    const clicked = await ev(`(function(){
      var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row'));
      var row = rows.filter(function(r){ return r.dataset.username === ${JSON.stringify(A)}; })[0];
      if (!row) return {ok:false, why:'no-row'};
      var b = row.querySelector('[data-friend-action="invite"]');
      if (!b) return {ok:false, why:'no-invite-btn'};
      if (b.disabled) return {ok:false, why:'disabled', title:b.title};
      b.click();
      return {ok:true}; })()`);
    check(clicked && clicked.ok === true, '★ T3a B 在好友面板里点了 A 的「邀战」', clicked);

    console.log('   等 A 侧真的收到 friend_invite…');
    const inviteEvt = await waitPeerEvent('friend_invite', 25000, peerIdxBeforeInvite).catch(() => null);
    // ⚠️ 这一条验的是**服务端真的推得出来**（`POST /api/friends/invite` 要真的建出房 + emit 给目标）。
    //    它红了不代表前端有问题 —— 前端那半边由下面的 T3f-* 单独钉死（本地注入，不依赖后端）。
    //    **现状**：好友批的后端两半都已上线，本工具实测这条是绿的（以前它红过一阵，
    //    当时被误读成"前端弹不出提示条"；结论已更正，别再照着老结论排查）。
    check(!!inviteEvt && !!(inviteEvt.data && inviteEvt.data.room_id),
      '★ T3b [后端那半边] A 的 socket 真的收到了 friend_invite（事件名与 payload 对得上契约）',
      inviteEvt ? inviteEvt.data : { pythonSide: peerEvents.slice(-3),
        hint: '接口把房间建好了、但事件没推到对方 socket 上（只写库不 emit 就是这个形状）' });

    // ---- T3c/T3d/T3e/T3i：同一条真链路，方向反过来推到**浏览器**那一侧 ----
    //
    // ⚠️⚠️ 方向必须是「python 侧 A → 浏览器 B」。
    //    上面 T3a 是 **B 点「邀战」邀 A** —— 发起方是 B，**B 的页面本来就不该弹提示条**。
    //    这三条断言第一版就是在这里等 B 的页面弹条（`inviteEvt` 是 A 收到的），
    //    方向写反了：它会一直红，而且红得毫无意义（作者当时把它误读成"后端只写库不 emit"，
    //    于是在注释里留了一条错误的结论 —— 一并删掉）。
    //
    //    真链路真正缺的是这一半：**服务端能不能把 friend_invite 推到一个浏览器 socket 上**。
    //    下面 T3f-* 是**本地注入**（验"前端收到之后做得对不对"），两半缺一不可：
    //    只有注入那条绿，说明不了"服务端推得出来"；只有这条绿，说明不了"前端做对了"。
    const invSeq = peerCmd('invite', { to: B });
    const invRes = await waitPeerCmd(invSeq, 25000).catch(() => null);
    const realRoom = (invRes && invRes.body && invRes.body.room_id) ? String(invRes.body.room_id) : '';
    check(!!realRoom, '★ T3c-0 [后端那半边] python 侧 A 经真接口向浏览器 B 发出邀战并拿到房间号', invRes);

    const toast = await waitFor(async () => {
      const o = await ev(`(function(){
        var t = document.getElementById('friend-invite-toast');
        var txt = document.getElementById('friend-invite-text');
        var enter = document.getElementById('friend-invite-enter');
        return { hidden: t.classList.contains('hidden'), text: txt.textContent,
                 enterPresent: !!enter, enterDisabled: enter ? enter.disabled : null,
                 display: getComputedStyle(t).display, rect: (function(r){ return {w:Math.round(r.width),h:Math.round(r.height)}; })(t.getBoundingClientRect()) }; })()`);
      return (o && !o.hidden && o.rect.w > 0) ? o : null;
    }, 25000, 'B 的页面弹出 #friend-invite-toast').catch(() => null);
    check(!!toast, '★ T3c [后端那半边] 真链路下 B 的页面弹出 #friend-invite-toast（前端同上，见 T3f-b）', toast);
    if (toast && realRoom) {
      check(toast.text.indexOf(A) >= 0 && toast.text.indexOf(realRoom) >= 0,
        '★ T3d 提示文案含对方用户名与房间号', { text: toast.text, from: A, room: realRoom });
    }
    check(!!toast && toast.enterPresent === true && toast.enterDisabled === false,
      '★ T3e [后端那半边] 真链路下 #friend-invite-enter 存在且可点（前端同上，见 T3f-d）', toast);

    // 真链路收尾：点「进入房间」必须真的进到**服务端这次给的那个房**
    //（T3f-4/T3g 那条进的是本地注入的房 —— 房间号虽然也是服务端建的，但事件是本地造的）
    if (toast && realRoom) {
      await clickJs('document.getElementById("friend-invite-enter")');
      const joinedReal = await waitFor(async () => {
        const o = await ev(`(function(){
          return { room: (typeof gameState !== 'undefined' && gameState.roomId) || null,
                   href: location.search }; })()`);
        // ⚠️⚠️ 判据必须是"进的是**这一间**"，不能是"roomId 有值"。
        //    上面 T3a（B 点「邀战」）现在会让**发起方自己先进一间房**（`sendFriendInvite` 里
        //    的自动入房），所以点击之前 `gameState.roomId` **已经有值**了 ——
        //    旧判据在点击生效前就满足，取样拿到的是**上一间房**，于是
        //    T3i 会以 `{joined:{room:<上一间>}, expect:<本次那间>}` 的形状红。
        //    这与 T3f-4 那条是同一个形状（那边已经收紧过），本项目栽过第二次了：
        //    **`waitFor` 的条件要写成"期望的那个具体值"，不能是"值域里有东西"**。
        return (o && String(o.room) === String(realRoom)) ? o : null;
      }, 20000, '真链路点「进入房间」后真的进了那个房').catch(() => null);
      check(!!joinedReal && String(joinedReal.room) === realRoom
            && String(joinedReal.href).indexOf('room=' + realRoom) >= 0,
        '★ T3i 真链路点「进入房间」后页面进到服务端给的那个房间（地址栏也带上了）',
        { joined: joinedReal, expect: realRoom });
    }

    // ---- T3f/T3g/T3h：前端那半边（**本地注入**，不依赖后端能不能建邀战房） ----
    //
    // ⚠️ 为什么要拆出这一段：真实的邀战链路要过两个后端环节 ——
    //    ① 事件推得出去（`presence` 登记 + emit）② `POST /api/friends/invite` 能建成房。
    //    这两个环节在并行开发期随时可能只有一半就绪，而"一半就绪"时上面的 T3b/T3c 会红 ——
    //    那是**后端的红**，却会被误读成"前端弹不出提示条"。
    //    这里用一个**本地房间 + 本地事件注入**把前端那半边单独钉死：
    //    房间号是真的（B 自己经 socket 建的房），事件名与 payload 严格照冻结契约，
    //    断言"点 #friend-invite-enter 之后页面真的进了**这个**房间、地址栏也带上了它"。
    //    后端两环节都好了之后，上面那条真链路会一起变绿（两条都留着，各管一半）。
    {
      // 1) 让 **A 侧（python socket）** 真建一个自定义房并坐在里面 —— 房间号是服务端给的。
      //    ⚠️ 不能让浏览器自己建房：那样房间里的那个座位就是 B 自己，B 再入房会被
      //    服务端按"房间已满"拒掉（实测踩过，症状是"点了没反应、页面零提示"）。
      //    归 A 之后，B 入房才是真实的"第二个人进来"。
      const mkSeq = peerCmd('mkroom', {});
      const mkRoom = await waitPeerCmd(mkSeq, 20000).catch(() => null);
      const localRoom = (mkRoom && mkRoom.body && mkRoom.body.room_id) ? String(mkRoom.body.room_id) : '';
      check(!!localRoom, '★ T3f-0 A 侧经 socket 真建了一个自定义房（拿它当邀战房间号）', mkRoom);

      if (localRoom) {
        // 2) 把 B 从那个房里挪走：页面重新加载一次（房间留在服务端，B 此刻还没入座）。
        //    ⚠️ 这里**不**手工改 `gameState.playerName`：入房本来就要在"名字是真名"的
        //    真实情形下成立，手工补名字等于把要验的东西提前替产品代码做了
        //    （第一版就是这么干的，结果真机上"名字为空导致入房被拒"那个坑被我亲手盖住）。
        await goto(APP + '?reset=1');
        // ⚠️ 等**新文档真的生效**再往下走：`Page.navigate` 之后紧接着取到的可能还是
        //    **旧文档**（本项目踩过：`readyState` 还停在旧文档上）。而上面 T3i 刚让页面
        //    进过一个真邀战房（地址栏带 `?room=`），旧文档里 `gameState.roomId` 还留着
        //    那个房间号 —— 于是下面 T3f-4/T3g/T3h 会随取样时机**闪红**：
        //    实测抓到的形状正是 `T3g：page=<上一段的房> vs event=<本段的房>`、
        //    `href:"?reset=1"`（地址栏还没带上本段的房间），pass / fail / pass。
        //    判据就用"我此刻不在任何房间里" —— 它与下面要验的东西（入房）不冲突。
        await waitFor(async () => {
          const room = await ev('(typeof gameState !== "undefined" && gameState.roomId) || null');
          return room ? null : true;
        }, 15000, 'reset 之后页面回到"不在任何房间"（旧的 ?room= 状态已清）').catch(() => null);
        // 3) 本地注入一条**严格照契约**的 friend_invite
        const injected = await ev(`(function(){
          // 触发页面自己注册的那个处理器（**不重写一遍处理逻辑**，那样验的就不是产品代码了）。
          // socket.io 客户端 4.x 的 Socket 上有 onevent(packet)：packet.data = [事件名, payload]，
          // 它就是真实报文到达时走的那条路（见 static/socket.io.js 的 onevent/emitEvent）。
          // 唯一的差别是"报文从本地来"而不是从服务端来 —— 所以上面那条**真链路**（T3a~T3e）
          // 仍然要保留：一条管"服务端真的推得出来"，一条管"前端收到之后真的做得对"。
          var s = window.gameState && window.gameState.socket;
          if (!s || typeof s.onevent !== 'function') return 'no-onevent';
          s.onevent({ data: ['friend_invite',
            { room_id: ${JSON.stringify(localRoom)}, from_user_id: 'probe-user', from_username: ${JSON.stringify(A)} }] });
          return 'ok'; })()`);
        check(injected === 'ok', '★ T3f-a 页面 socket 上有 onevent（本地注入走的就是真实那条分发路径）', injected);
        const localToast = await waitFor(async () => {
          const o = await ev(`(function(){
            var t = document.getElementById('friend-invite-toast');
            var txt = document.getElementById('friend-invite-text');
            var e = document.getElementById('friend-invite-enter');
            return { hidden: t.classList.contains('hidden'), text: txt.textContent,
                     enterPresent: !!e, enterDisabled: e ? e.disabled : null,
                     w: Math.round(t.getBoundingClientRect().width) }; })()`);
          return (o && !o.hidden && o.w > 0) ? o : null;
        }, 12000, '本地注入 friend_invite 后弹出提示条').catch(() => null);
        check(!!localToast, '★ T3f-b 收到 friend_invite → #friend-invite-toast 弹出且可见', localToast);
        if (localToast) {
          check(localToast.text.indexOf(A) >= 0 && localToast.text.indexOf(localRoom) >= 0,
            '★ T3f-c 提示文案含对方用户名与房间号', { text: localToast.text, from: A, room: localRoom });
          check(localToast.enterPresent === true && localToast.enterDisabled === false,
            '★ T3f-d #friend-invite-enter 存在且可点', localToast);

          await clickJs('document.getElementById("friend-invite-enter")');
          // ⚠️⚠️ 判据必须是**这个房**（`=== localRoom`），不能是"roomId 有值"。
          //    上面 T3i 刚让页面进过**另一个**真邀战房，`?reset=1` 导航之后的
          //    `gameState.roomId` 在"上一次入房"那一刻就被写成那个房号了 ——
          //    所以 `(o && o.room)` 会在**点击真正生效之前**就满足，于是：
          //      · T3f-4 假绿（它测的其实还是上一段那个房号）
          //      · T3g / T3h 时红时绿（取样时地址栏还停在 `?reset=1`）
          //    实测形状正是 `T3f-4: {room:<上一段的房>, screen:false, href:"?reset=1"}`
          //    紧跟 `T3g: page=<上一段的房> vs event=<本段的房>`。判据收紧成"已经进了
          //    本段的房"之后，这一段的取样点才真的在"点击生效之后"。
          const joinedLocal = await waitFor(async () => {
            const o = await ev(`(function(){
              return { room: (typeof gameState !== 'undefined' && gameState.roomId) || null,
                       screen: document.getElementById('ship-placement-screen').classList.contains('active'),
                       href: location.search }; })()`);
            return (o && String(o.room) === String(localRoom)) ? o : null;
          }, 20000, '点「进入房间」后真的进了**本段那个**房').catch(() => null);
          check(!!joinedLocal, '★ T3f-4 点 #friend-invite-enter 后页面真的进了房间（gameState.roomId 有值）', joinedLocal);
          if (joinedLocal) {
            check(String(joinedLocal.room) === localRoom,
              '★ T3g 页面上的房间号 == 事件里那个 room_id（真进了同一个房间）',
              { page: joinedLocal.room, event: localRoom });
          }
          check(!!joinedLocal && String(joinedLocal.href).indexOf('room=' + localRoom) >= 0,
            'T3h 复用既有 ?room= 入房逻辑（地址栏带上了同一个房间号）', joinedLocal && joinedLocal.href);
        }
      }
    }

    // ---- T6 窄屏（放在 T4 之前：T4 会把好友删光，删光之后面板里没行可量） ----
    console.log('-- T6 390x844 窄屏面板 --');
    await goto(APP);
    await checkNarrowPanel();

    // ---- T4 删除好友，两边列表都空 ----
    // ⚠️ 页面重新加载后 `window.confirm` 的替身会被冲掉，所以每轮都重新装一次；
    //    同时用 CDP 的 Fetch 域把 /api/friends/remove 的回执抓下来 —— 删不掉时
    //    要能一眼分清"按钮没点到"还是"服务端说失败"。
    await goto(APP);
    await ev('(function(){ window.__confirmCalled = false; window.confirm = function(){ window.__confirmCalled = true; return true; }; return true; })()');
    await clickJs('document.getElementById("friends-btn")');
    await waitFor(async () => (await ev('document.querySelectorAll("#friends-list .friend-row").length > 0') ? true : null), 12000, 'B 的好友行').catch(() => null);
    const removeClicked = await ev(`(function(){
      var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row'));
      var row = rows.filter(function(r){ return r.dataset.username === ${JSON.stringify(A)}; })[0];
      if (!row) return {ok:false, why:'no-row', rows: rows.map(function(r){ return r.dataset.username; })};
      var b = row.querySelector('[data-friend-action="remove"]');
      if (!b) return {ok:false, why:'no-remove-btn'};
      b.click(); return {ok:true}; })()`);
    const confirmCalled = await ev('window.__confirmCalled === true');
    check(removeClicked && removeClicked.ok === true && confirmCalled === true,
      '★ T4a 删除好友前弹了二次确认（用 confirm 替身拦下来验的）',
      { clicked: removeClicked, confirmCalled: confirmCalled });
    const emptiedB = await waitFor(async () => {
      const n = await ev('document.querySelectorAll("#friends-list .friend-row").length');
      return n === 0 ? n : null;
    }, 20000, 'B 的好友列表清空').catch(() => null);
    const listNow = await ev(`(function(){
      return { friends: [].slice.call(document.querySelectorAll('#friends-list .friend-row')).map(function(r){ return r.dataset.username; }),
               requests: [].slice.call(document.querySelectorAll('#friends-requests .friend-row')).map(function(r){ return r.dataset.username; }),
               outgoing: [].slice.call(document.querySelectorAll('#friends-outgoing .friend-row')).map(function(r){ return r.dataset.username; }),
               msg: (document.getElementById('friends-msg') || {}).textContent || '' }; })()`);
    // ⚠️ 判据用**当前 DOM**，不用 waitFor 的返回值：`waitFor` 是轮询的，可能在
    //    某一次采样里读到"还没刷新完"的中间态（实测出现过 emptied=null 但 DOM 其实已经空了）。
    check(listNow.friends.length === 0,
      '★ T4b 删除后 B 的好友列表为空', { emptied: emptiedB, now: listNow });

    const listA2 = await fetch(APP + 'api/friends', { headers: { 'Accept': 'application/json', 'Cookie': cookieProbe } })
      .then((r) => r.json()).catch(() => null);
    const aHasB2 = !!(listA2 && Array.isArray(listA2.friends) && listA2.friends.some((f) => f.username === B));
    check(aHasB2 === false, '★ T4c 删除后 A 侧（直读接口）的好友列表也为空',
      listA2 ? (listA2.friends || []).map((f) => f.username) : listA2);
    const emptyShown = await ev('!document.getElementById("friends-empty").classList.contains("hidden")');
    check(emptyShown === true, '★ T4d 三个分区都空时显示 #friends-empty 空状态', emptyShown);

    // ---- T9「是否允许他人加我好友」开关（好友批决策④的后半句） ----
    //
    // ⚠️⚠️ 为什么要用真浏览器 + 真接口钉死它：这个开关的**两个失败形状都是静默的**。
    //    ① 初始化那条路：`renderProfileEditor` 走 `setProfileToggle(id, v)`，而它是
    //       `if (el) el.checked = ...` —— id 写错 / 元素没渲染出来**不报错**，症状是
    //       "用户明明关掉了，下次一打开又自己勾回来"。
    //    ② 保存那条路：`collectProfileEditorPayload` 里的 `checked(id, fallback)` 在元素
    //       缺失时**返回兜底值 1** —— 症状是"关掉之后一保存又被设置成开"，还会把服务端
    //       已经写好的 0 覆盖回 1。两条路都不抛异常、接口也回 200，只能靠断言钉。
    //    ③ 还有一条只能靠**两侧都断言**才抓得住：接口回了 403，但库里已经写进了一条申请
    //       （CLAUDE.md 坑 #12 同形状）→ 所以 A 侧看 HTTP，B 侧直读 /api/friends。
    //
    // 用 T4 之后的状态：B 与 A 此刻**已经不是好友**（T4 刚删完），正好可以真发申请。
    {
      // 走**真实 UI 路径**打开编辑面：页头「个人信息」→ 查看态名片 →「编辑资料」。
      // 具体的三步（打开 + 等静默）见下面的 openEditorSettled。
      // ⚠️ 两个等待都不能省：① 名片是异步渲染的，弹窗可见 ≠ 内容是名片（第 10 节第 15 条）；
      //    ② 「编辑资料」按钮长在查看面那张卡里（`#profile-edit-btn`），所以必须 scoped 到
      //    `#opponent-stats-content` 里找 —— 编辑面自己那张卡上也有同名入口。
      // ⚠️⚠️⚠️ 打开编辑面之后**必须再等它"安静下来"**（本工具 2026-09-19 第二次踩的坑，
      //    也是 T9b/T9c/T9d/T9e 时红时绿的真正原因）：
      //    上面那个判据（编辑面开着 + 复选框在）只说明**骨架**就绪了，而
      //    `openMyProfileEditor()` 的 `fetch('/api/profile')` 是异步的 —— 它回来之后才调
      //    `renderProfileEditor()`，把 6 个开关**按服务端值**重写一遍。
      //    于是"编辑面刚开出来就立刻取消勾选"会输给这趟仍在飞的初始化渲染：
      //      · 工具读到的 `checkedAfter:false` 是真的（点击那一下确实翻了）
      //      · 但 ~50ms 后它被渲染改回 `true`，接着 `collectProfileEditorPayload()` 读到的就是 1
      //      · 保存载荷 `friend_requests_open:1` → 服务端一切照旧 → T9b/T9c/T9c-2/T9d/T9e-2 连锁红
      //    实测（.tmp/t9b_probe8.mjs 的 A/B，每 40ms 采样一次）：
      //      A 立刻取消勾选 → 采样序列**从第 52ms 起就全是 1**，载荷 sent:1 / 服务端 1；
      //      B 等 1200ms 再取消 → 全程 0，载荷 sent:0 / 服务端 0。
      //    所以这里改成"等 DOM 连续 400ms 没有变动"才往下走 —— 不用固定 sleep 猜时间。
      const waitEditorSettled = `(async function () {
        var edit = document.getElementById('profile-edit');
        if (!edit) return 'no-edit';
        var last = performance.now();
        var mo = new MutationObserver(function () { last = performance.now(); });
        mo.observe(edit, { childList: true, subtree: true, attributes: true, characterData: true });
        var t0 = performance.now();
        while (performance.now() - t0 < 8000) {
          await new Promise(function (r) { setTimeout(r, 50); });
          if (performance.now() - last >= 400) { mo.disconnect(); return 'settled'; }
        }
        mo.disconnect();
        return 'timeout';
      })()`;
      // 打开编辑面（真实 UI 路径）+ 等它静默。**T9 的每一步都先走这个**。
      //
      // ⚠️⚠️ 两个等待缺一不可，而且**必须都留**：
      //   ① `waitEditorSettled`：等"连续 400ms 没有 DOM 变动"；
      //   ② 之后再硬等 1200ms（`guardMs`）。
      //   为什么有了 ① 还要 ②：① 只能等到"**当前这一阵**动静停了"，而
      //   `openMyProfileEditor()` 那趟 `fetch('/api/profile')` 有可能**刚好落在静默窗口里**
      //   （骨架已经铺好、渲染还没回来，那 400ms 内一次 DOM 变动都没有）→ ① 会误判成"已就绪"，
      //   于是后面的取消勾选又被那趟渲染改回去。实测就是这么翻的：
      //     只加 ①（400ms 静默）→ 连跑 3 次**全红**，`setToggle` 的 tries 是
      //       `[{now:false},{now:true},{now:false}]`（每点一次就被改回去一次）；
      //     ① + ②（再等 1200ms）→ A/B 探针（.tmp/t9b_probe8.mjs）里采样每 40ms 一次、
      //       连续 1.5 秒**全程 0**，保存载荷 sent:0 / 服务端 0。
      //   宁可多等 1.2 秒也别赌 —— 这个工具本来就是几分钟级的。
      const openEditorSettled = `(async function () {
        var head = document.getElementById('show-profile');
        var clicked = 'no-editor';
        for (var attempt = 0; attempt < 3 && clicked !== 'clicked'; attempt++) {
          if (head) head.click();
          for (var i = 0; i < 25; i++) {
            var m = document.getElementById('profile-modal');
            var modalOpen = m && !m.classList.contains('hidden');
            var b = document.querySelector('#opponent-stats-content #profile-edit-btn');
            if (b) b.click();
            if (modalOpen && document.getElementById('profile-friend-requests')) { clicked = 'clicked'; break; }
            await new Promise(function (r) { setTimeout(r, 150); });
          }
        }
        if (clicked !== 'clicked') return clicked;
        await (${waitEditorSettled});
        // ② 兜底静默期：防"那趟初始化渲染刚好落在静默窗口里"（见上面注释）
        await new Promise(function (r) { setTimeout(r, 1200); });
        // 再确认一次编辑面确实开着（等静默期间可能被别的浮层收掉）
        var mm = document.getElementById('profile-modal');
        if (!mm || mm.classList.contains('hidden')) return 'closed-again';
        return 'clicked';
      })()`;
      // 把开关切到 want **并当场点保存** —— 两步放在**同一个同步任务**里，不给任何
      // "异步渲染把值改回去"的窗口。（这是本工具 2026-09-19 第三次踩的同一个坑的不同变体：
      // 编辑面打开后头一两秒里，`checked` 会被那趟异步初始化渲染反复改写，实测
      // `setToggle` 的 tries 稳定给出 `[{false},{true},{false}]` —— 每点一次就被改回去一次。）
      // ⚠️ 所以这里：click 之后**不 await**，直接读回值、直接点保存。
      //    `collectProfileEditorPayload()` 是**同步**执行的（就藏在 `saveProfileCard` 第一行），
      //    所以它读到的必然是"点击刚落地的那个值"；这一条同时还是对"保存那条路真的取到了新值"的硬断言。
      const setToggleAndSave = (want) => `(function () {
        var want = ${want};
        var el = document.getElementById('profile-friend-requests');
        if (!el) return { ok: false, why: 'no-el' };
        if (el.checked !== (want === 1)) el.click();
        var atSave = el.checked;                     // 保存那一刻的真实值（同步读，boolean）
        var msg = document.getElementById('profile-save-msg');
        if (msg) msg.textContent = '';               // 清掉上一轮的「已保存」，好让下面等的是**本次**回执
        document.getElementById('profile-card-save').click();
        // 注意类型：DOM 的 .checked 是 boolean，别拿它跟 0/1 直接比（false === 0 为假）——
        // 这里统一归一到 0/1 再比，省得把"其实全对"的载荷判成红。
        return { ok: (atSave ? 1 : 0) === want, want: want, atSave: atSave };
      })()`;
      // 现场一次性取全：元素在不在、勾没勾、这一排到底有几个开关（含 JS 注入的留言板那个）
      const toggleState = `(function(){
        var el = document.getElementById('profile-friend-requests');
        var box = document.querySelector('#profile-edit .pf-pane[data-pane="card"] .pf-toggles');
        var msg = document.getElementById('profile-save-msg');
        return { exists: !!el, checked: el ? el.checked : null,
          toggles: box ? [].slice.call(box.querySelectorAll('input[type=checkbox]')).map(function(i){ return i.id; }) : null,
          editorOpen: (function(){ var m = document.getElementById('profile-modal'); return m ? !m.classList.contains('hidden') : null; })(),
          msg: msg ? msg.textContent : null }; })()`;
      const mark = () => profileCardBodies.length;
      // 等"本次保存"的请求体到齐，并把最后一条捞出来（每次都用 mark() 起一个窗口）
      async function waitPostedBody(from, timeout) {
        const got = await waitFor(() => (profileCardBodies.length > from ? profileCardBodies.length : null),
          timeout || 15000, '本次保存的 POST /api/profile/card').catch(() => null);
        if (!got) return null;
        return profileCardBodies[profileCardBodies.length - 1];
      }

      // ---- T9a：默认开 ----
      const opened9 = await ev(openEditorSettled);
      const st1 = await ev(toggleState);
      check(opened9 === 'clicked' && st1.editorOpen === true,
        '★ T9a-0 走真实 UI（页头个人信息 → 编辑资料）打开编辑面，并等它初始化渲染落地',
        { opened: opened9, editorOpen: st1.editorOpen });
      // 顺带把这一排的开关清单打出来：漏了哪个一眼能看到（留言板那个是 JS 注入的）
      check(st1.exists === true && st1.checked === true,
        '★ T9a 编辑面里有 #profile-friend-requests，且默认是勾上的（默认开）',
        { exists: st1.exists, checked: st1.checked, toggles: st1.toggles });

      // ---- T9b：取消勾选 → 保存 → 载荷里必须是 0，且是 11 个字段 ----
      const before9 = mark();
      const unchecked = await ev(setToggleAndSave(0));
      // ⚠️ `atSave` 是"点保存那一刻读到的真实值"：它必须已经是 0。
      //    这一条与下面的 T9b-2 各管一半 —— 一个管"点掉了没"，一个管"载荷真的带上它了没"。
      check(unchecked && unchecked.ok === true && unchecked.atSave === false,
        '★ T9b-0 把「允许他人加我为好友」取消勾选，并在点保存那一刻确实是没勾的（走真实 click）', unchecked);
      const last9 = (await waitPostedBody(before9)) || {};
      const keys9 = Object.keys(last9);
      // ⚠️ 判据用**抓到的请求体**（比读 #profile-save-msg 硬）：文案对了但字段没发出去，
      //    服务端会整次 400 而前端那行字照样可能停在上一帧的「已保存」上。
      check(!!last9 && !last9.__parseFail && keys9.length > 0,
        '★ T9b 保存时真的发出了 POST /api/profile/card（请求体抓到了）', { body: last9 });
      check(keys9.length === 11 && keys9.indexOf('friend_requests_open') >= 0,
        '★ T9b-1 保存载荷仍是 **11** 个字段，且含 friend_requests_open',
        { n: keys9.length, keys: keys9 });
      check(last9.friend_requests_open === 0,
        '★ T9b-2 取消勾选后载荷里 friend_requests_open === 0（没被 checked() 的兜底 1 盖掉，也没被初始化渲染改回去）',
        { sent: last9.friend_requests_open, msg: await ev('document.getElementById("profile-save-msg").textContent') });

      // ---- T9c：两侧都断言（接口回 403 **且**库里没写） ----
      const rqSeq = peerCmd('request', { to: B });
      const rqAck = await waitPeerCmd(rqSeq, 20000).catch(() => null);
      const rqBody9 = (rqAck && rqAck.body) || {};
      check(!!rqAck && rqAck.http === 403 && /不接受好友申请/.test(String(rqBody9.error || '')),
        '★ T9c 关掉开关后，A 侧发申请被 **403** 拒绝（原因含「不接受好友申请」）', rqAck);
      const listB9 = await fetch(APP + 'api/friends', { headers: { 'Accept': 'application/json', 'Cookie': cookieB } })
        .then((r) => r.json()).catch(() => null);
      const incoming9 = (listB9 && Array.isArray(listB9.incoming)) ? listB9.incoming.map((f) => f.username) : null;
      // 这一半是 CLAUDE.md 坑 #12：只看接口容易假绿/假红 —— "回 403 但库里写了"同样是坏的
      check(Array.isArray(incoming9) && incoming9.indexOf(A) < 0,
        '★ T9c-2 B 侧直读 /api/friends：incoming 里**没有** A（拒绝是真的，不是只回个 403）',
        { incoming: incoming9, friends: listB9 ? (listB9.friends || []).map((f) => f.username) : null });

      // ---- T9d：刷新页面后重新打开编辑面，必须**仍然是没勾的** ----
      // 这条抓的是"初始化没生效 / 被兜底 1 覆盖"那种静默故障，也是 D 票最典型的一类。
      // ⚠️ 刷新后**同样要等编辑面静默**：这一条恰恰是"服务端值 → 初始化渲染"那条路，
      //    不等它落地就读 `.checked` 的话，读到的是 HTML 里写死的 `checked`（假绿）。
      await goto(APP);
      const opened9b = await ev(openEditorSettled);
      const st2 = await ev(toggleState);
      check(opened9b === 'clicked', '★ T9d-0 刷新页面后再次打开编辑面并等它静默', opened9b);
      check(st2.exists === true && st2.checked === false,
        '★ T9d 刷新后复选框**仍然是没勾的**（关掉的状态真的落库、初始化也读回来了）',
        { exists: st2.exists, checked: st2.checked, editorOpen: st2.editorOpen });

      // ---- T9e：勾回来 → 保存 → 这次必须放行（**必须恢复成开**） ----
      const before9e = mark();
      const rechecked = await ev(setToggleAndSave(1));
      check(rechecked && rechecked.ok === true && rechecked.atSave === true,
        '★ T9e-0 把开关勾回来，并在点保存那一刻确实是勾上的', rechecked);
      const last9e = (await waitPostedBody(before9e)) || {};
      check(last9e.friend_requests_open === 1,
        '★ T9e 勾回来再保存，载荷里 friend_requests_open === 1（开关真的被恢复成开）',
        { sent: last9e.friend_requests_open });
      const rqSeq2 = peerCmd('request', { to: B });
      const rqAck2 = await waitPeerCmd(rqSeq2, 20000).catch(() => null);
      const rqBody9e = (rqAck2 && rqAck2.body) || {};
      check(!!rqAck2 && rqAck2.http === 200 && rqBody9e.status === 'sent',
        '★ T9e-2 开关恢复后，A 侧再发一次申请 → 200 / status=sent', rqAck2);
      const listB9e = await fetch(APP + 'api/friends', { headers: { 'Accept': 'application/json', 'Cookie': cookieB } })
        .then((r) => r.json()).catch(() => null);
      const incoming9e = (listB9e && Array.isArray(listB9e.incoming)) ? listB9e.incoming.map((f) => f.username) : [];
      check(incoming9e.indexOf(A) >= 0,
        '★ T9e-3 B 侧直读：incoming 里出现了 A（恢复之后申请真的写进去了）', incoming9e);
      // ⚠️ 收尾必须把开关留在"开"：T4 之后还有 T6 窄屏、T7 零异常这些检查，而编辑面的
      //    这个开关是**持久化的用户设置**，留在"关"会把后面任何一次申请类断言带红。
      const finalState = await ev(toggleState);
      check(finalState.exists === true && finalState.checked === true,
        '★ T9f 收尾：开关停在"勾上"（不给后面的检查留后遗症）',
        { checked: finalState.checked, toggles: finalState.toggles });
      // 关掉编辑面，别让它压着后面的窄屏检查
      await ev('(function(){ var m = document.getElementById("profile-modal"); if (m) m.classList.add("hidden"); return true; })()');
    }
  } else {
    skip('★ T2 两个真账号的好友申请 / 接受全链路', '/api/friends 未上线（HTTP ' + probe.status + '）');
    skip('★ T3 邀战真链路（friend_invite → 进入房间）', '/api/friends 未上线（HTTP ' + probe.status + '）');
    skip('★ T4 删除好友后两边列表都空', '/api/friends 未上线（HTTP ' + probe.status + '）');
    skip('★ T9「允许他人加我好友」开关（默认开 / 关掉后 403 / 刷新不掉）',
      '/api/friends 未上线（HTTP ' + probe.status + '）—— 它要真发申请真读列表');
  }

  // ---------- T7 零 JS 异常 / 零 console.error ----------
  check(jsProblems.length === 0, '★ T7 全程零 JS 异常 / 零 console.error（含页面内与 python 侧）', jsProblems.slice(0, 8));

  // ---------- 截图（可选） ----------
  if (SHOT) {
    try {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
      console.log('   截图已存 ' + SHOT);
    } catch (e) { console.log('   截图失败: ' + e.message); }
  }
}

// ---------- 收尾 ----------
async function cleanup() {
  try { if (peer && !peer.killed) peer.kill(); } catch (e) { /* 已退 */ }
  try { ws && ws.close(); } catch (e) { /* 已关 */ }
  try { browser && !browser.killed && browser.kill(); } catch (e) { /* 已退 */ }
}

main().catch((err) => {
  console.error('工具自身异常：' + (err && err.stack || err));
  failures.push('工具自身异常: ' + (err && err.message));
}).then(async () => {
  await cleanup();
  const total = passes.length + failures.length;
  console.log('');
  console.log('==================== 结果 ====================');
  console.log('通过 ' + passes.length + ' / 失败 ' + failures.length + ' / 跳过 ' + skips.length +
    '（断言总数 ' + total + '）');
  if (skips.length) {
    console.log('跳过（后端未上线，跑全链路前需先起 /api/friends）：');
    skips.forEach((s) => console.log('   · ' + s));
  }
  if (failures.length) {
    console.log('失败项：');
    failures.forEach((f) => console.log('   · ' + f));
    process.exit(1);
  }
  console.log(failures.length === 0 ? '✓ 好友 UI 检查通过' + (skips.length ? '（含跳过项，见上）' : '') : '');
  process.exit(0);
});
