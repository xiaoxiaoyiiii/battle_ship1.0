#!/usr/bin/env node
/**
 * 好友私聊（DM）UI 回归检查（无头 Edge + CDP + 一个 python 侧真账号，全部断言真实 DOM/真实接口）。
 *
 * 契约：docs/FRIEND_DM_2026_09_19.md §3（纯规则）/ §4（接口，冻结）/ §5（DOM，冻结 id）。
 *
 * 为什么必须有这个工具（而不是只跑 pytest）：
 *   pytest 测的是 api.py 那半边；DOM 契约、气泡左右分、滚动锚定、"未读归零"这一整类
 *   问题**只存在于浏览器里**，而且它们的失败形状全是静默的 ——
 *   `getElementById` 拿到 null 被 `if (el)` 兜掉、`hidden` 属性被作者样式的 display 压过去、
 *   prepend 之后 scrollTop 不补 → 玩家眼里只是"点了没反应 / 画面跳了一屏"。
 *
 * 覆盖（每条都对应票面要求）：
 *   D1  好友面板每行有「私聊」按钮（data-friend-action="dm"）
 *   D2  点它 → 会话视图出现（#dm-panel 可见 / #friends-body 收起）、#dm-title == 对方用户名
 *   D3  python 侧经**真接口**发一条 → 页面**实时**收到并渲染（data-mine="0"），stamp 非空且形如 MM-DD HH:MM
 *   D4  页面里发一条 → 列表出现 data-mine="1" 的那条，且 **python 侧真的收到了**（它自己的 socket
 *      收到 friend_message + 直读 GET /api/friends/messages 断言内容）
 *   D5  未读：对方发的消息**不在当前会话**时 → 好友行 .friend-unread 显示服务端给的数；
 *      打开会话后 → 页面显示 0/隐藏 **且** 以 python 身份直读 GET /api/friends 的 unread == 0（两侧都断言）
 *   D6  空会话占位 #dm-empty 出现；发出第一条后消失
 *   D7  has_more 为真 → #dm-load-more 可见；点它把更早的消息插到顶部，
 *      并且**已存在的那条消息的 getBoundingClientRect().top 偏差 ≤ 2px**（可证伪的判据）；
 *      取完最后一页后 #dm-load-more 隐藏
 *   D8  超 300 字被服务端拒绝 → 页面显示服务端那句中文原因（含「最多 300 字」）
 *   D9  全程零 JS 异常 / 零 console.error
 *
 * 用法：
 *   node tools/friend_dm_check.mjs --url http://127.0.0.1:5114/ [--db .tmp/xxx.db] [--shot <png>]
 *
 * ⚠️ 服务端必须带 `CORS_ORIGINS=http://127.0.0.1:<端口>`，否则 socket.io **静默连不上**
 *    （页面无报错，只是 D3/D4/D5 全成假红）。
 * ⚠️ 只在**隔离库**上跑：它会注册 dmchk_* 账号、写好友关系与聊天记录。
 *    默认库 .tmp/friend_dm_ui.db，**必须与服务端 BATTLESHIP_DB_PATH 指向同一份**
 *    （python 侧要按同一份库造"更早的消息"，造到别的库里就会看到"翻了半天没有更早的"）。
 * ⚠️ 本机没装 websocket-client → python 侧 socket 显式走 polling（见 PY_HELPER 里的说明）。
 * ⚠️ CDP 端口 9381、profile 在 .tmp/ 下自己的目录：别与既有工具（9361/9362/9371/9372）抢。
 */

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

// ---------- 参数 ----------
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5114/').replace(/\/?$/, '/');
const SHOT = argOf('--shot', '');

let HERE;
try { HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')); }
catch (e) { HERE = process.cwd(); }
const ROOT = path.resolve(HERE, '..');
const TMP = path.join(ROOT, '.tmp');
const DB = path.resolve(ROOT, argOf('--db', path.join('.tmp', 'friend_dm_ui.db')));
const PORT = 9381;
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(TMP, 'friend_dm_check_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳好友私聊检查'); process.exit(0); }
fs.mkdirSync(TMP, { recursive: true });

// ---------- 预清理：残留的无头进程会占着调试端口 + 锁住 profile ----------
// （不清的话新浏览器**静默起不来**，连上的是上一轮的旧实例 → 查不出所以然的假红）
try {
  spawnSync('powershell', ['-NoProfile', '-Command',
    'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
    'Where-Object { $_.CommandLine -like \'*friend_dm_check_profile*\' } | ' +
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

// ---------- 账号 ----------
const SUFFIX = String(Date.now()).slice(-6);
const PW = 'check123456';
const A = 'dmchk_a' + SUFFIX;      // python 侧（真 socket + 真接口）
const B = 'dmchk_b' + SUFFIX;      // 浏览器里那个人
const C = 'dmchk_c' + SUFFIX;      // "还没聊过"的空会话对象（D6 用）

// ---------- Node 侧账号辅助（注册 + 登录 + 拿 cookie） ----------
// ⚠️ 登录失败也会种 session cookie，所以"拿到 cookie"不等于"登录成功" ——
//    必须拿它去 /api/profile 反查一次 username（friends_check 里记过这个坑）。
//
// ⚠️⚠️ 还有一个坑（本批实测，排查花了很久）：`api.py` 对 `/login` 有**同 IP 限流**
//    （`_rate_limited('login')`：60 秒窗口内 10 次）。超限后 `/login` 回 302 到 `/login`
//    并 flash「操作过于频繁，请稍后再试」—— 拿到的 cookie 里**没有 user_id**，
//    于是 /api/profile 一律 401。本工具一次要登录 3 个账号（A/B/C），再加上别的工具
//    共用 127.0.0.1 这一个 remote_addr，很容易撞上；而症状是"账号没登进去"，
//    看着像 cookie 传递坏了，跟限流一点关系都没有。所以这里认得出限流并等窗口过去。
const LOGIN_BUSY_RE = /操作过于频繁/;

async function loginAttempt(username) {
  const r = await fetch(APP + 'login', {
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
  // ⚠️ 顺序：**先注册**（只注册一次）。/register 成功时 api.py 会**直接种好 session**，
  //    正常路径下一次 /login 都不用发 —— 省配额，也避免"先试登录（账号还不存在，白扣一次）"。
  //    第二次拿同一账号再去 /register 会回「用户名已存在」且**不种 session**，
  //    所以之后一律走登录重试（第一版写成"注册 4 次"，就是那样白等 20 秒的）。
  const reg = await register();
  let cookie = await verify(readCookie(reg));
  if (cookie) return cookie;
  for (let i = 0; i < 14; i++) {
    await sleep(5000);                         // 窗口 60 秒：被限流就等它滑过去
    const a = await loginAttempt(username);
    cookie = await verify(a.setCookie);
    if (cookie) return cookie;
    // ⚠️ 只有"限流"才值得等：登录成功但 cookie 没用（或账号真有问题）时死等 70 秒
    //    只会把一次假红拖成一次很慢的假红 —— 那类情况直接交回给调用方的断言。
    if (!a.limited) break;
  }
  return '';
}
function readCookie(resp) {
  const raw = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [resp.headers.get('set-cookie')].filter(Boolean);
  const pairs = raw.map((c) => String(c).split(';')[0]).filter(Boolean);
  return pairs.length ? pairs.join('; ') : '';
}
async function apiGet(p, cookie) {
  const r = await fetch(APP + p, { headers: { Accept: 'application/json', Cookie: cookie || '' } });
  const text = await r.text();
  try { return { status: r.status, body: text ? JSON.parse(text) : null }; }
  catch (e) { return { status: r.status, body: null, raw: text.slice(0, 200) }; }
}
async function apiPost(p, payload, cookie) {
  const r = await fetch(APP + p, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', Cookie: cookie || '' },
    body: JSON.stringify(payload || {})
  });
  const text = await r.text();
  try { return { status: r.status, body: text ? JSON.parse(text) : null }; }
  catch (e) { return { status: r.status, body: null, raw: text.slice(0, 200) }; }
}

// ---------- python 侧的 A：真登录 + 真 socket + 真接口 ----------
const PY_HELPER = path.join(TMP, 'friend_dm_peer.py');
const CMD_FILE = path.join(TMP, 'friend_dm_cmd.json');
fs.writeFileSync(PY_HELPER, String.raw`
# -*- coding: utf-8 -*-
"""friend_dm_check.mjs 用的 python 侧玩家：真登录 + 真 socket + 真接口。

命令文件（JSON）之一，stdout 每行一个 JSON：
  {"cmd":"send","to":"xxx","body":"..."}      经 POST /api/friends/messages 发一条
  {"cmd":"list","to":"xxx","limit":50}        直读 GET /api/friends/messages
  {"cmd":"seed","to":"xxx","count":60}        往库里**直接**塞更早的历史消息（D7 的夹具）
  {"cmd":"read","to":"xxx"}                   POST /api/friends/messages/read
  {"cmd":"friends"}                           直读 GET /api/friends（未读数两侧都断言要用）
  {"cmd":"quit"}

⚠️ transports=['polling']：本机没装 websocket-client，websocket 传输会连不上
   （python-socketio 只打印一句警告，然后报 namespace 连接失败）。推送走的是同一条
   engine.io 会话，polling 一样能证明"事件真的到了这个人"（后端批的端到端也这么干的）。
"""
import json, os, sys, time
import requests
import socketio

base, username, password, cmd_file, db_path = sys.argv[1:6]
base = base.rstrip('/') + '/'
# ⚠️ 本脚本是从 .tmp/ 里跑的，sys.path[0] 是 .tmp —— 不把**仓库根**塞进去就 import 不到 db
#    （症状：seed 命令回一句 "No module named 'db'"，夹具静默造不出历史消息，
#     于是"往上翻"那几条断言全红，而红的原因看着像前端没插进去）。
sys.path.insert(0, os.environ.get('DM_REPO_ROOT', os.getcwd()))
# 让 db 模块指向**服务端那一份**库（seed 要在同一个文件里造历史消息）
os.environ['BATTLESHIP_DB_PATH'] = db_path

def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)

s = requests.Session()

def is_logged_in():
    try:
        r = s.get(base + 'api/profile', timeout=10)
        if r.status_code != 200:
            return False
        return bool(r.json().get('profile'))
    except Exception:
        return False

def do_login():
    return s.post(base + 'login', data={'username': username, 'password': password}, allow_redirects=True)

def login_ok():
    """登录一次并**确认真的登进去了**（返回 True/False）。

    ⚠️ api.py 的 /login 有**同 IP 限流**（60 秒 10 次，见 _rate_limited）：超限时它回 302
    到 /login 并 flash「操作过于频繁，请稍后再试」，而那次响应**照样会种 session cookie**
    （里面没有 user_id）。所以"发了登录请求"完全不等于"登进去了" —— 必须靠 /api/profile 反查，
    否则后面所有接口都是 401，症状看着像前后端坏了，其实是限流。
    """
    do_login()
    return is_logged_in()

def login_with_retry(tries=14):
    """先注册（成功即已登录），不行再登录重试 —— 见 login_ok 的说明。

    ⚠️ **只注册一次**：同一账号第二次 /register 会回「用户名已存在」并且不种 session，
    拿它重试是白等（本工具第一版就是这么白等了 20 秒）。
    """
    s.post(base + 'register', data={'username': username, 'password': password}, allow_redirects=True)
    if is_logged_in():
        return True
    for _ in range(tries):
        time.sleep(5)          # 等限流那个 60 秒窗口滑过去
        do_login()
        if is_logged_in():
            return True
    return False

login_with_retry()

cookie = '; '.join('%s=%s' % (k, v) for k, v in s.cookies.get_dict().items())
out({'event': 'login', 'ok': is_logged_in(), 'user': username})

sio = socketio.Client(reconnection=False)

@sio.on('friend_message')
def on_message(data):
    # D4 的判据之一：**python 侧的 socket 真的收到了**页面发出去的那条
    out({'event': 'friend_message', 'data': data})

@sio.on('error')
def on_error(data):
    out({'event': 'socket_error', 'data': data})

sio.connect(base.rstrip('/'), headers={'Cookie': cookie}, wait_timeout=20, transports=['polling'])
out({'event': 'ready'})

def seed_history(to_username, count):
    """往库里直接塞更早的历史消息（D7 的夹具）。

    ⚠️ 为什么不走接口造这 60 条：会撞 20 条/分钟的限流（dm.PER_MINUTE），
    而**限流本身也是被测行为**，不能为了让夹具过而放宽它。夹具只负责"库里有一段更早的历史"，
    被测的那条路径（GET /api/friends/messages 分页 + 前端插到顶部）仍然走真接口。

    ⚠️ 用 db.get_user(username=...) 取 uid（db 模块没有 get_user_by_username；
    第一版照着别处的印象写了那个名字，回执是 "module 'db' has no attribute ..."）。
    """
    import db
    me = db.get_user(username=username)
    other = db.get_user(username=to_username)
    if not me or not other:
        return {'error': 'user-not-found', 'me': bool(me), 'other': bool(other)}
    my_uid = me['id']
    other_uid = other['id']
    made = 0
    for i in range(int(count)):
        # 历史消息是**对方发给我的**（这样它们出现在会话里，且时间更早）
        row = db.add_friend_message(other_uid, my_uid, 'history-%02d' % i)
        if row:
            made += 1
    return {'made': made, 'from': to_username}

last = 0
t0 = time.time()
while time.time() - t0 < 600:
    time.sleep(0.2)
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
    cmd = job.get('cmd'); seq = job.get('seq'); to = job.get('to', '')
    if cmd == 'quit':
        out({'event': 'bye', 'seq': seq}); break
    try:
        if cmd == 'send':
            r2 = s.post(base + 'api/friends/messages', json={'username': to, 'body': job.get('body', '')}, timeout=10)
            try: body = r2.json()
            except Exception: body = {'raw': r2.text[:200]}
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': r2.status_code, 'body': body})
        elif cmd == 'list':
            r2 = s.get(base + 'api/friends/messages', params={'username': to, 'limit': job.get('limit', 50)}, timeout=10)
            try: body = r2.json()
            except Exception: body = {'raw': r2.text[:200]}
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': r2.status_code, 'body': body})
        elif cmd == 'read':
            r2 = s.post(base + 'api/friends/messages/read', json={'username': to}, timeout=10)
            try: body = r2.json()
            except Exception: body = {'raw': r2.text[:200]}
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': r2.status_code, 'body': body})
        elif cmd == 'friends':
            r2 = s.get(base + 'api/friends', timeout=10)
            try: body = r2.json()
            except Exception: body = {'raw': r2.text[:200]}
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': r2.status_code, 'body': body})
        elif cmd == 'respond':
            r2 = s.post(base + 'api/friends/respond',
                        json={'username': to, 'accept': bool(job.get('accept', True))}, timeout=10)
            try: body = r2.json()
            except Exception: body = {'raw': r2.text[:200]}
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': r2.status_code, 'body': body})
        elif cmd == 'seed':
            out({'event': 'cmd_result', 'seq': seq, 'cmd': cmd, 'http': 200, 'body': seed_history(to, job.get('count', 60))})
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
  const p = spawn('python', [PY_HELPER, APP, A, PW, CMD_FILE, DB], {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', DM_REPO_ROOT: ROOT },
    stdio: ['ignore', 'pipe', 'pipe']
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
    const t = d.toString('utf8');
    if (/Traceback|Error/.test(t)) jsProblems.push('python 侧: ' + t.replace(/\s+/g, ' ').slice(0, 220));
  });
  return p;
}
let cmdSeq = 0;
function peerCmd(cmd, extra) {
  const seq = ++cmdSeq;
  fs.writeFileSync(CMD_FILE, JSON.stringify(Object.assign({ seq: seq, cmd: cmd }, extra || {})), 'utf8');
  return seq;
}
async function waitPeerCmd(seq, timeout) {
  return waitFor(() => peerEvents.find((e) => e.event === 'cmd_result' && e.seq === seq),
    timeout || 25000, 'python 侧命令回执 #' + seq);
}
async function waitPeerEvent(name, timeout, since) {
  const from = since === undefined ? 0 : since;
  return waitFor(() => {
    const idx = peerEvents.findIndex((e, i) => i >= from && e.event === name);
    return idx >= 0 ? peerEvents[idx] : null;
  }, timeout || 20000, 'python 侧收到 ' + name);
}
// 一次调用把命令 + 回执收齐（绝大多数断言只关心回执）
async function peerDo(cmd, extra, timeout) {
  const seq = peerCmd(cmd, extra);
  return waitPeerCmd(seq, timeout).catch(() => null);
}

// ---------- CDP ----------
let browser = null, ws = null, seq = 0;
const pending = new Map();

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
async function goto(url) {
  await send('Page.navigate', { url });
  const want = url.replace(/\/$/, '');
  await waitFor(async () => {
    const st = await ev('({ href: location.href.replace(/\\/$/, ""), ready: document.readyState })');
    return st && st.ready === 'complete' && st.href === want;
  }, 30000, '页面加载 ' + url);
  await sleep(500);
}
async function clickJs(selectorExpr) {
  const r = await ev('(function(){ var el = ' + selectorExpr + '; if (!el) return {ok:false,why:"not-found"};'
    + ' el.click(); return {ok:true}; })()');
  if (!r || !r.ok) throw new Error('点击失败 ' + selectorExpr + ' -> ' + JSON.stringify(r));
  return r;
}
async function setCookie(c) {
  const u = new URL(APP);
  for (const p of String(c).split(';').map((s) => s.trim()).filter(Boolean)) {
    const i = p.indexOf('=');
    if (i < 0) continue;
    await send('Network.setCookie', {
      name: p.slice(0, i), value: p.slice(i + 1), domain: u.hostname, path: '/', url: APP
    });
  }
}

// ---------- 页面探针 ----------
// 会话视图此刻的样子（一次取全，避免多次取样之间的中间态把断言判红）
const DM_STATE = `(function(){
  var panel = document.getElementById('dm-panel');
  var body = document.getElementById('friends-body');
  var list = document.getElementById('dm-list');
  var empty = document.getElementById('dm-empty');
  var more = document.getElementById('dm-load-more');
  var input = document.getElementById('dm-input');
  var send = document.getElementById('dm-send');
  var title = document.getElementById('dm-title');
  var rows = [].slice.call(list ? list.querySelectorAll('.dm-row') : []);
  return {
    panelHidden: panel ? panel.hidden : null,
    panelDisplay: panel ? getComputedStyle(panel).display : null,
    bodyHidden: body ? body.hidden : null,
    title: title ? title.textContent : null,
    emptyHidden: empty ? empty.hidden : null,
    moreHidden: more ? more.hidden : null,
    inputMax: input ? input.getAttribute('maxlength') : null,
    inputValue: input ? input.value : null,
    sendDisabled: send ? send.disabled : null,
    count: rows.length,
    mine: rows.map(function(r){ return r.getAttribute('data-mine'); }),
    bodies: rows.map(function(r){ return (r.querySelector('.dm-body')||{}).textContent; }),
    stamps: rows.map(function(r){ return (r.querySelector('.dm-stamp')||{}).textContent; }),
    ids: rows.map(function(r){ return r.getAttribute('data-id'); })
  }; })()`;

// 某一条消息此刻在屏幕上的位置（滚动锚定断言用）
const rowTop = (id) => `(function(){
  var el = document.querySelector('#dm-list .dm-row[data-id="' + ${JSON.stringify(String(id))} + '"]');
  if (!el) return null;
  var r = el.getBoundingClientRect();
  return { top: r.top, bottom: r.bottom, text: (el.querySelector('.dm-body')||{}).textContent };
})()`;

const STAMP_RE = /^\d{2}-\d{2} \d{2}:\d{2}$/;   // dm.py 的 stamp 口径（MM-DD HH:MM）

// ---------- 主流程 ----------
async function main() {
  console.log('== 好友私聊 UI 回归检查 ==');
  console.log('   APP = ' + APP);
  console.log('   DB  = ' + DB);
  console.log('   B   = ' + B + '（浏览器）   A = ' + A + '（python socket/接口侧）   C = ' + C + '（空会话对象）');
  console.log('');

  // 服务端探测：接口在不在（不在就是后端那半边的事，别把整份工具判成前端红）
  const probe = await fetch(APP + 'api/friends', { headers: { Accept: 'application/json' } })
    .then((r) => ({ status: r.status })).catch((e) => ({ status: 0, error: String(e.message) }));
  if (probe.status === 0) {
    throw new Error('服务端连不上（' + APP + '）—— 先起服务再跑本工具');
  }

  // ---------- 造 3 个真账号 + 真好友关系（两侧都断言） ----------
  const cookieB = await nodeAuth(APP, B);
  const cookieC = await nodeAuth(APP, C);
  check(!!cookieB, '★ D0a 浏览器侧账号 B 已就绪（真登录，cookie 反查过 username）', cookieB ? cookieB.split('=')[0] + '=…' : cookieB);
  check(!!cookieC, '★ D0b 空会话对象 C 已就绪', !!cookieC);
  // ⚠️ 三个账号没齐就**立刻停**：不然下面 40 多条断言会一起红，把"登录被限流了"这件事
  //    淹没在几十条假红里（实测一次跑出 39 条失败，全是这一个根因）。
  if (!cookieB || !cookieC) {
    throw new Error('账号没登进去（多半是 /login 的 IP 限流：60 秒内 10 次，见 tools/ 里的注释）'
      + ' —— 等一分钟再跑，或先确认没有别的工具在同 IP 上刷登录');
  }

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

  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') {
      const ex = m.params.exceptionDetails || {};
      const desc = (ex.exception && (ex.exception.description || ex.exception.value)) || ex.text;
      jsProblems.push('JS 异常: ' + String(desc).slice(0, 220));
      console.log('   [异常详情] ' + String(desc).slice(0, 700));
      if (ex.stackTrace && ex.stackTrace.callFrames) {
        console.log('   [调用栈] ' + ex.stackTrace.callFrames.slice(0, 6)
          .map((f) => (f.functionName || '?') + '@' + f.lineNumber).join(' <- '));
      }
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 180));
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  // ⚠️ 无条件把页面提到最前：isDmConversationVisible 里那条 `document.hasFocus()` 判据
  //    在后台标签页上会是 false，未读就不会归零 —— 那种红是工具的错，不是产品的错。
  try { await send('Page.bringToFront'); } catch (e) { /* 无头下不支持就算了 */ }

  // B 登录（Node 侧注册/登录拿 cookie，再种进浏览器 —— 照 friends_check 的写法）
  await send('Network.clearBrowserCookies').catch(() => {});
  await setCookie(cookieB);
  await goto(APP);
  const meB = await ev('window.__USERNAME || null');
  check(meB === B, '★ D0c 浏览器页面认得当前登录用户是 B', meB);

  // socket 真的连上了吗（连不上时页面**不报错**，D3/D4/D5 会全成假红）
  await ev('(function(){ if (typeof ensureSocket === "function") ensureSocket(); return true; })()');
  const sockOk = await waitFor(async () => {
    const o = await ev('(function(){ return { has: !!gameState.socket, connected: gameState.socket ? gameState.socket.connected : false }; })()');
    return o && o.connected ? o : null;
  }, 15000, 'B 的页面 socket 连上服务端').catch(() => null);
  check(!!sockOk, '★ D0d B 的 socket 真的连上了（连不上时后面全是静默假红：CORS_ORIGINS 要放行本端口）', sockOk);

  // ---------- python 侧 A 起来（真登录 + 真 socket） ----------
  peer = startPeer();
  const peerReady = await waitFor(() => peerEvents.find((e) => e.event === 'ready'), 40000, 'python 侧 A 登录并连上 socket').catch(() => null);
  check(!!peerReady, '★ D0e python 侧账号 A 真登录并连上 socket（polling 传输）', peerReady || peerEvents.slice(-3));
  if (!peerReady) throw new Error('python 侧没起来，后面没法验实时链路');

  // ---------- 真好友关系：B → A（B 发申请、**A 收**），以及 B → C（D6 的空会话） ----------
  // ⚠️ 用真接口建立关系（不走库），而且必须用**收件人自己那一边的会话**去接受：
  //    `POST /api/friends/respond` 认的是"登录的那个人"，拿 B 的 cookie 去接受 B 自己发出的申请
  //    只会被服务端按"没有这条申请"拒掉（返回 200 但 status 不是 accepted —— 静默假绿那种）。
  //    所以 A 那一边走 python 侧（它才是收件人），C 那一边用 C 的 cookie。
  const relA = await apiPost('api/friends/request', { username: A }, cookieB);
  const relC = await apiPost('api/friends/request', { username: C }, cookieB);
  const peerCIncoming = await apiGet('api/friends', cookieC);
  const cHasB = !!(peerCIncoming.body && Array.isArray(peerCIncoming.body.incoming)
    && peerCIncoming.body.incoming.some((f) => f.username === B));
  check(relA.body && relA.body.status === 'sent' && relC.body && relC.body.status === 'sent',
    '★ D0f B→A / B→C 的两条好友申请真的发出去了（status=sent）', { toA: relA.body, toC: relC.body });
  check(cHasB, '★ D0g C 侧直读 /api/friends：incoming 里有 B（两侧都断言，别只看发送方）',
    peerCIncoming.body && peerCIncoming.body.incoming);
  const accByC = await apiPost('api/friends/respond', { username: B, accept: true }, cookieC);
  const accByA = await peerDo('respond', { to: B, accept: true }, 20000);
  // ⚠️ 判据看的是**响应体**的 status（业务结果），HTTP 码在 `status` 这个字段里（不叫 http）。
  //    第一版写成了 `accByC.http`（undefined）→ 变成一条恒假的假红；反过来把 `accByC.status`
  //    当成握手结果来断言就是一条恒真的假绿。两个字段名在这里必须分清。
  check(accByC && accByC.status === 200 && accByC.body && accByC.body.status === 'accepted',
    '★ D0h C 接受了 B 的申请（走 C 自己的会话）', accByC);
  check(accByA && accByA.http === 200 && accByA.body && accByA.body.status === 'accepted',
    '★ D0i A 接受了 B 的申请（走 python 侧真接口）', accByA && accByA.body);
  const bFriends = await apiGet('api/friends', cookieB);
  const bFriendNames = (bFriends.body && Array.isArray(bFriends.body.friends))
    ? bFriends.body.friends.map((f) => f.username) : [];
  check(bFriendNames.indexOf(A) >= 0 && bFriendNames.indexOf(C) >= 0,
    '★ D0j B 侧直读 /api/friends：A 与 C 都在好友列表里（关系真的成了）', bFriendNames);

  // ---------- D1：好友面板里每行都有「私聊」 ----------
  await clickJs('document.getElementById("friends-btn")');
  const rowsReady = await waitFor(async () => {
    const n = await ev('document.querySelectorAll("#friends-list .friend-row").length');
    return n > 0 ? n : null;
  }, 15000, 'B 的好友列表有行').catch(() => 0);
  check(rowsReady > 0, '★ D1a 好友面板里有好友行可点', rowsReady);
  const dmBtns = await ev(`(function(){
    var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row'));
    return rows.map(function(r){
      var b = r.querySelector('[data-friend-action="dm"]');
      return { user: r.dataset.username, has: !!b, text: b ? b.textContent : null };
    }); })()`);
  check(dmBtns.length > 0 && dmBtns.every((x) => x.has === true),
    '★ D1 每一行好友都有「私聊」按钮（data-friend-action="dm"，§5 冻结的属性）', dmBtns);

  // ---------- D5（前半）：对方发的消息**不在当前会话**时 → 好友行显示未读数 ----------
  const sendA1 = await peerDo('send', { to: B, body: 'D5 未读用的第一条' }, 25000);
  check(sendA1 && sendA1.http === 200 && sendA1.body && sendA1.body.status === 'ok',
    '★ D5a[后端那半边] A 经真接口给 B 发了一条', sendA1);
  const unreadShown = await waitFor(async () => {
    const o = await ev(`(function(){
      var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row'));
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].dataset.username !== ${JSON.stringify(A)}) continue;
        var b = rows[i].querySelector('.friend-unread');
        return { has: !!b, hidden: b ? b.hidden : null, text: b ? b.textContent : null };
      }
      return null; })()`);
    return (o && o.has && o.hidden === false && Number(o.text) > 0) ? o : null;
  }, 25000, `B 的好友行出现未读数（${A}）`).catch(() => null);
  // ⚠️ 这一条同时是对"未读来自服务端"的间接证据：页面**没有**在前端 +1，
  //    它只是"面板开着时重拉了一次 GET /api/friends"，数字是服务端算好的。
  check(!!unreadShown, '★ D5b 面板开着时收到私聊 → 该好友行显示服务端给的未读数（.friend-unread 可见）',
    unreadShown || { hint: '未读数没出现：先确认页面有没有在面板开着时重拉 /api/friends，以及 friend.unread 字段在不在响应里' });
  const peerUnread = await peerDo('friends', {}, 20000);
  const peerSelfUnread = (peerUnread && peerUnread.body && Array.isArray(peerUnread.body.friends))
    ? (peerUnread.body.friends.find((f) => f.username === B) || {}).unread : null;
  check(peerSelfUnread === 0 || peerSelfUnread === undefined || peerSelfUnread === null,
    'D5c 对照组：A 自己那边对 B 的 unread 不该被这条消息影响（发出去的是"我发的"）',
    { unread: peerSelfUnread });

  // ---------- D2：点「私聊」→ 会话视图 ----------
  const clicked = await ev(`(function(){
    var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row'));
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].dataset.username !== ${JSON.stringify(A)}) continue;
      var b = rows[i].querySelector('[data-friend-action="dm"]');
      if (!b) return {ok:false, why:'no-btn'};
      b.click(); return {ok:true};
    }
    return {ok:false, why:'no-row'}; })()`);
  check(clicked && clicked.ok === true, '★ D2a 点 A 那一行的「私聊」按钮', clicked);
  const opened = await waitFor(async () => {
    const o = await ev(DM_STATE);
    return (o && o.panelHidden === false && o.bodyHidden === true) ? o : null;
  }, 12000, '会话视图出现（#dm-panel 可见 / #friends-body 收起）').catch(() => null);
  check(!!opened, '★ D2b 会话视图出现：#dm-panel 可见、#friends-body 收起（同一个弹窗内切换）', opened);
  check(!!opened && opened.title === A, '★ D2c #dm-title 就是对方用户名', opened && { title: opened.title, expect: A });
  check(!!opened && opened.inputMax === '300', '★ D2d #dm-input 的 maxlength == 300（与服务端 dm.MAX_BODY_LEN 同一口径）',
    opened && opened.inputMax);
  const stillOneModal = await ev('document.querySelectorAll(".modal-overlay:not(.hidden)").length');
  check(stillOneModal === 1, '★ D2e 会话视图**没有**新开弹窗（可见的 .modal-overlay 仍只有 1 个）', stillOneModal);

  // ---------- D3：A 通过真接口发一条 → 页面实时收到并渲染 ----------
  const liveBody = 'D3 实时消息 ' + SUFFIX;
  const sendA2 = await peerDo('send', { to: B, body: liveBody }, 25000);
  check(sendA2 && sendA2.http === 200, '★ D3a[后端那半边] A 经真接口又发了一条（内容可核对）', sendA2);
  const liveRow = await waitFor(async () => {
    const o = await ev(DM_STATE);
    if (!o) return null;
    const i = o.bodies.indexOf(liveBody);
    return i >= 0 ? { i: i, mine: o.mine[i], stamp: o.stamps[i], id: o.ids[i], count: o.count } : null;
  }, 25000, '页面实时渲染出 A 刚发的那条').catch(() => null);
  check(!!liveRow, '★ D3b 页面**实时**收到 friend_message 并渲染出来了（这条断言同时是"socket 推送真的到了"的证明）',
    liveRow || { pythonSide: peerEvents.slice(-3),
      hint: '没渲染出来：先确认页面注册了 friend_message（事件名一字不差），再确认 isDmConversationVisible 那条判据没把消息当成"不是当前会话"' });
  check(!!liveRow && liveRow.mine === '0',
    '★ D3c 对方发来的那条 data-mine="0"（= 不是我发的）', liveRow);
  check(!!liveRow && STAMP_RE.test(String(liveRow.stamp || '')),
    '★ D3d 每条消息渲染的是服务端给的 stamp，且形如 MM-DD HH:MM', liveRow && liveRow.stamp);
  const liveState = await ev(DM_STATE);
  check(liveState.stamps.every((s) => STAMP_RE.test(String(s || ''))) && liveState.stamps.every((s) => !!s),
    'D3e 会话里**每一条**都有服务端 stamp（没有一条是空的）', liveState.stamps);
  check(!!liveRow && liveState.mine.indexOf('0') >= 0,
    'D3f 两端可区分：会话里既有 data-mine="0" 的行（此时还没有 "1" 的行）', liveState.mine);

  // ---------- D5（后半）：打开会话后未读归零 —— 页面 + python 直读两侧都断言 ----------
  const unreadCleared = await waitFor(async () => {
    const o = await ev(`(function(){
      var el = document.getElementById('dm-msg');
      var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row'));
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].dataset.username !== ${JSON.stringify(A)}) continue;
        var b = rows[i].querySelector('.friend-unread');
        return { has: !!b, hidden: b ? b.hidden : null, text: b ? b.textContent : null, msg: el ? el.textContent : null };
      }
      return null; })()`);
    return (o && o.has && o.hidden === true) ? o : null;
  }, 20000, '页面里该好友行的未读数归零（.friend-unread 隐藏）').catch(() => null);
  check(!!unreadCleared, '★ D5d 打开会话后该好友行的未读数归零（页面这一侧）',
    unreadCleared || { hint: '先确认打开会话时真的调了 POST /api/friends/messages/read，以及成功后有没有把那行的 .friend-unread 归零' });
  const peerUnreadAfter = await peerDo('friends', {}, 20000);
  const bRowUnread = (peerUnreadAfter && peerUnreadAfter.body && Array.isArray(peerUnreadAfter.body.friends))
    ? (peerUnreadAfter.body.friends.find((f) => f.username === B) || {}).unread : null;
  // ⚠️ 以 **A 的身份**直读接口：B 那边"页面上是 0"可能只是前端把数字藏起来了，
  //    只有服务端的未读真的被清掉才算数（CLAUDE.md 第 10 节第 12 条：两侧都要断言）。
  check(bRowUnread === 0, '★ D5e 以 python 侧 A 的身份直读 GET /api/friends：B 那行 unread == 0（服务端真的清掉了）',
    { unread: bRowUnread, counts: peerUnreadAfter && peerUnreadAfter.body && peerUnreadAfter.body.counts });

  // ---------- D4：页面里发一条 → python 侧真的收到 ----------
  const sendBody = 'D4 页面发的一条 ' + SUFFIX;
  // ⚠️ 窗口起点**必须在点击之前**取：点下去之后 page→A 的推送可能比这行 JS 先落地，
  //    起点取晚了就会把"刚到的推送"划到窗口外 → 断言变成"没收到"（假红）。
  const peerIdxBefore2 = peerEvents.length;
  await ev(`(function(){
    var i = document.getElementById('dm-input');
    var s = document.getElementById('dm-send');
    i.value = ${JSON.stringify(sendBody)};
    s.click();
    return true; })()`);
  const sentRow = await waitFor(async () => {
    const o = await ev(DM_STATE);
    if (!o) return null;
    const i = o.bodies.indexOf(sendBody);
    return i >= 0 ? { i: i, mine: o.mine[i], stamp: o.stamps[i], count: o.count } : null;
  }, 15000, '页面发出后列表里出现那条（data-mine="1"）').catch(() => null);
  check(!!sentRow && sentRow.mine === '1', '★ D4a 自己发的那条 data-mine="1"（与对方的 "0" 视觉可分）', sentRow);
  check(!!sentRow && STAMP_RE.test(String(sentRow.stamp || '')), '★ D4b 自己那条的 stamp 也来自服务端响应（不是前端造的）',
    sentRow && sentRow.stamp);
  const afterSend = await ev(DM_STATE);
  check(afterSend.inputValue === '', '★ D4c 发送成功后输入框被清空', afterSend.inputValue);
  const atBottom = await ev(`(function(){
    var box = document.getElementById('dm-list');
    return { fromBottom: Math.round(box.scrollHeight - box.scrollTop - box.clientHeight), scrollTop: Math.round(box.scrollTop) }; })()`);
  check(atBottom.fromBottom <= 40, '★ D4d 发送后滚动到底部（距底部 ≤ 40px）', atBottom);
  // python 侧两个独立证据：socket 真的收到 + 直读接口里真的有这一条
  const gotEvt = await waitFor(() => {
    const hit = peerEvents.slice(peerIdxBefore2).find((e) => e.event === 'friend_message'
      && e.data && String(e.data.body || '').indexOf('D4 页面发的一条') >= 0);
    return hit || null;
  }, 20000, 'A 的 socket 收到页面发出的那条 friend_message').catch(() => null);
  check(!!gotEvt, '★ D4e python 侧 A 的 socket **真的收到了**页面发出的那条（from_username 也要对得上）',
    gotEvt ? gotEvt.data : { sinceIdx: peerIdxBefore2, pythonSide: peerEvents.slice(peerIdxBefore2).slice(-3) });
  check(!!gotEvt && String(gotEvt.data.from_username || '') === B && gotEvt.data.mine === undefined,
    'D4f 推送 payload 里 from_username == B，且**不含**发送方视角字段 mine（§4 的推送形状）',
    gotEvt && gotEvt.data);
  const peerList = await peerDo('list', { to: B, limit: 50 }, 20000);
  const peerSeesIt = !!(peerList && peerList.body && Array.isArray(peerList.body.messages)
    && peerList.body.messages.some((m) => String(m.body || '') === sendBody));
  check(peerSeesIt, '★ D4g A 直读 GET /api/friends/messages 里也有这一条（消息真的落库了，不只是页面上画了一下）',
    peerList && peerList.body && { n: (peerList.body.messages || []).length, last: (peerList.body.messages || []).slice(-1) });

  // ---------- D6：空会话占位 ----------
  await clickJs('document.getElementById("dm-back")');
  const backToList = await waitFor(async () => {
    const o = await ev(`(function(){
      var panel = document.getElementById('dm-panel');
      var body = document.getElementById('friends-body');
      return { panelHidden: panel.hidden, bodyHidden: body.hidden }; })()`);
    return (o && o.panelHidden === true && o.bodyHidden === false) ? o : null;
  }, 10000, '点 #dm-back 回到列表视图').catch(() => null);
  check(!!backToList, '★ D6a 点 #dm-back 回到好友列表视图（#dm-panel 收起 / #friends-body 展开）', backToList);
  const cClicked = await ev(`(function(){
    var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row'));
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].dataset.username !== ${JSON.stringify(C)}) continue;
      var b = rows[i].querySelector('[data-friend-action="dm"]');
      if (!b) return {ok:false, why:'no-btn'};
      b.click(); return {ok:true};
    }
    return {ok:false, why:'no-row'}; })()`);
  const emptyState = await waitFor(async () => {
    const o = await ev(DM_STATE);
    return (o && o.panelHidden === false && o.count === 0 && o.emptyHidden === false) ? o : null;
  }, 12000, '与 C 的空会话显示 #dm-empty').catch(() => null);
  check(cClicked && cClicked.ok === true && !!emptyState,
    '★ D6b 还没聊过时显示空会话占位 #dm-empty（「还没有聊过，打个招呼吧」）', emptyState);
  check(!!emptyState && emptyState.moreHidden === true,
    '★ D6c 空会话里 #dm-load-more 隐藏（has_more 为假）', emptyState && emptyState.moreHidden);
  const emptyText = await ev('document.getElementById("dm-empty").textContent');
  check(/打个招呼/.test(String(emptyText || '')), '★ D6d 空会话占位的文案是「还没有聊过，打个招呼吧」', emptyText);

  // ---------- D8：超 300 字被服务端拒绝 → 页面显示中文原因 ----------
  // ⚠️ 输进输入框的是 301 个字：`maxlength=300` 只管**用户手动输入**，程序化赋值绕得过去，
  //    所以这一条真能打到服务端（判据取服务端那句中文，而不是前端自己拦的文案）。
  const tooLong = 'x'.repeat(301);
  await ev(`(function(){
    var i = document.getElementById('dm-input');
    i.value = ${JSON.stringify(tooLong)};
    document.getElementById('dm-send').click();
    return true; })()`);
  const rejected = await waitFor(async () => {
    const o = await ev(`(function(){
      var el = document.getElementById('dm-msg');
      return { text: el ? el.textContent : null, isError: el ? el.classList.contains('is-error') : null }; })()`);
    return (o && /最多\s*300\s*字/.test(String(o.text || ''))) ? o : null;
  }, 15000, '超长消息被拒绝后页面显示服务端的中文原因').catch(() => null);
  check(!!rejected && rejected.isError === true,
    '★ D8 超 300 字被服务端拒绝时，页面显示服务端那句中文原因（含「最多 300 字」）',
    rejected || { hint: '先确认 POST /api/friends/messages 真的回了 400 与中文 error，再看前端有没有把 res.reason 写进提示位' });
  const noBubble = await ev(DM_STATE);
  check(noBubble.count === 0, '★ D8b 被拒绝的那条**没有**被画进会话（失败不假装成功）', noBubble.count);

  // ---------- D7：has_more → 「加载更早」插到顶部且不跳位置 ----------
  // 夹具：A 往库里塞 60 条历史消息（走库直写，见 python 侧 seed_history 的注释：
  // 走接口会撞 20 条/分钟的限流，而限流本身也是被测行为，不能为了让夹具过而放宽它）。
  const seed = await peerDo('seed', { to: B, count: 60 }, 30000);
  check(seed && seed.body && Number(seed.body.made) === 60, '★ D7a[夹具] 库里已造好 60 条更早的历史消息', seed && seed.body);
  // 重新进这个会话（拉到最新一页，50 条，has_more 应为真）
  await clickJs('document.getElementById("dm-back")');
  const reenter = await ev(`(function(){
    var rows = [].slice.call(document.querySelectorAll('#friends-list .friend-row'));
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].dataset.username !== ${JSON.stringify(A)}) continue;
      var b = rows[i].querySelector('[data-friend-action="dm"]');
      if (b) { b.click(); return true; }
    }
    return false; })()`);
  const page1 = await waitFor(async () => {
    const o = await ev(DM_STATE);
    return (o && reenter && o.panelHidden === false && o.count > 0) ? o : null;
  }, 15000, '重新进入 A 的会话并拉到最新一页').catch(() => null);
  // ⚠️ 判据是"取满了一页"（limit 默认 50），不是"总共有多少条"：
  //    本工具会反复在同一个隔离库里跑，历史消息是**累积**的 —— 写死总数会让第二次跑就红。
  const PAGE_LIMIT = 50;
  check(!!page1 && page1.count === PAGE_LIMIT, '★ D7b 拉到最新一页（limit 默认 50，取满）', page1 && { count: page1.count });
  check(!!page1 && page1.moreHidden === false,
    '★ D7c has_more 为真 → #dm-load-more 可见（服务端用 EXISTS 问库，前端不推算）', page1 && { moreHidden: page1.moreHidden });

  // 锚点：记下"当前最上面那条"的位置 —— 插更早的消息**不许**把它挪走
  const anchorId = page1 ? page1.ids[0] : null;
  // 诊断用的一次性现场（列表高度 / 滚动位置 / 首行几何）：滚动锚定这条断言一旦红了，
  // 光看"偏差 17px"看不出是"没补 scrollTop"还是"补了但内容高度算错"，必须把原始数字打出来。
  const geom = `(function(){
    var box = document.getElementById('dm-list');
    var rows = [].slice.call(box.querySelectorAll('.dm-row'));
    var f = rows[0] ? rows[0].getBoundingClientRect() : null;
    var l = rows.length ? rows[rows.length-1].getBoundingClientRect() : null;
    var host = document.querySelector('#friends-modal .modal-content');
    var overlay = document.getElementById('friends-modal');
    var panel = document.getElementById('dm-panel');
    var more = document.getElementById('dm-load-more');
    return { n: rows.length, scrollTop: box.scrollTop, scrollHeight: box.scrollHeight,
             clientHeight: box.clientHeight, firstTop: f ? f.top : null, firstH: f ? f.height : null,
             lastTop: l ? l.top : null, maxScroll: box.scrollHeight - box.clientHeight,
             // ⚠️ 下面这几个是"**列表本身在屏幕上动没动**"的探针：如果 prepend 的同时
             //    容器/弹窗自己上滚了（例如弹窗内容变高→外层滚动、或上面的按钮换行），
             //    那么"同一条消息的屏幕位置"会变，而 list 内部的滚动锚定其实是正确的。
             listRectTop: Math.round(box.getBoundingClientRect().top * 100) / 100,
             hostScrollTop: host ? host.scrollTop : null,
             hostScrollHeight: host ? host.scrollHeight : null,
             hostClientHeight: host ? host.clientHeight : null,
             overlayScrollTop: overlay ? overlay.scrollTop : null,
             panelTop: panel ? Math.round(panel.getBoundingClientRect().top * 100) / 100 : null,
             moreTop: more ? Math.round(more.getBoundingClientRect().top * 100) / 100 : null,
             moreH: more ? Math.round(more.getBoundingClientRect().height * 100) / 100 : null }; })()`;
  const geomBefore = await ev(geom);
  const anchorBefore = anchorId ? await ev(rowTop(anchorId)) : null;
  check(!!anchorBefore, '★ D7d 取到了一个锚点（当前最上面那条消息）用来量滚动位置', { id: anchorId, top: anchorBefore && anchorBefore.top });
  await clickJs('document.getElementById("dm-load-more")');
  const page2 = await waitFor(async () => {
    const o = await ev(DM_STATE);
    return (o && o.count > 50) ? o : null;
  }, 20000, '点「加载更早的消息」后列表变长').catch(() => null);
  const geomAfter = await ev(geom);
  const addedRows = geomBefore && geomAfter ? geomAfter.n - geomBefore.n : null;
  const grew = geomBefore && geomAfter ? geomAfter.scrollHeight - geomBefore.scrollHeight : null;
  // ⚠️ 判据是"**这一页真的插进去了**"（行数增加、且新增的都是更早的 id），
  //    不是"总数 == 某个写死的数"：本工具会在同一个隔离库里反复跑，历史消息是累积的，
  //    更早那一页剩下几条取决于之前跑过几次（写死 10 会第二次跑就红）。
  check(!!page2 && addedRows > 0,
    '★ D7e 点 #dm-load-more 把更早的消息**插到了列表顶部**（本页新增若干条）',
    { addedRows: addedRows, grew: grew, before: geomBefore, after: geomAfter, head: page2 && page2.bodies[0] });
  const anchorAfter = anchorId ? await ev(rowTop(anchorId)) : null;
  // ⚠️⚠️ 这是本工具**最要紧的一条**：判据是可证伪的像素偏差，不是"看着没跳"。
  //     prepend 之后若不补 scrollTop（或补少了 —— 实测踩过：同步读 scrollHeight 会读到
  //     过期值、少补 17.66px），偏差会是十几到几百像素。
  const drift = (anchorBefore && anchorAfter) ? Math.abs(anchorAfter.top - anchorBefore.top) : null;
  check(drift !== null && drift <= 2,
    '★ D7f 插到顶部后**不跳滚动位置**：同一条消息的 getBoundingClientRect().top 偏差 ≤ 2px',
    { id: anchorId, before: anchorBefore && anchorBefore.top, after: anchorAfter && anchorAfter.top, drift: drift });
  // 产品代码**自己**也量了一遍（`window.dmAnchorDrift`，见 game.js 里那段注释）。
  // 两边口径相同 → 两个数对不上就说明"页面上的补法"与"工具的量法"不是一回事。
  const selfDrift = await ev('(typeof dmAnchorDrift === "function") ? dmAnchorDrift() : "no-fn"');
  check(typeof selfDrift === 'number' && selfDrift <= 2,
    '★ D7f-2 产品代码自证的滚动偏差也 ≤ 2px（window.dmAnchorDrift 由 game.js 自己写入）',
    { selfDrift: selfDrift, toolDrift: drift });
  // D7g：插到顶部的确实是**更早**的（判据用 id 顺序，不认文案 ——
  // 本工具会在同一个隔离库里反复跑，历史消息是累积的，"第一条长什么样"不可靠）。
  const idsNum = (page2 ? page2.ids : []).map((x) => Number(x)).filter((x) => !isNaN(x));
  const headIds = idsNum.slice(0, Math.max(0, addedRows || 0));
  const restIds = idsNum.slice(Math.max(0, addedRows || 0));
  check(headIds.length > 0 && restIds.length > 0 && Math.max.apply(null, headIds) < Math.min.apply(null, restIds),
    '★ D7g 插到顶部的确实是**更早**的消息（新增那一段的 id 全部小于原有那一段）',
    { head: headIds, originalFirst: restIds[0], originalLast: restIds[restIds.length - 1] });
  const noDup = page2 ? (new Set(page2.ids.filter(Boolean)).size === page2.ids.filter(Boolean).length) : false;
  check(noDup, '★ D7h 插入后没有重复的消息行（id 唯一）', page2 && page2.ids.length);
  const moreAfterAll = await ev('document.getElementById("dm-load-more").hidden');
  const hasMoreNow = await ev(`(function(){
    var el = document.getElementById('dm-load-more');
    return { hidden: el.hidden, disabled: el.disabled }; })()`);
  check(hasMoreNow && hasMoreNow.hidden === true, '★ D7i 取完最后一页后 #dm-load-more 隐藏（has_more 为假）', hasMoreNow);
  void moreAfterAll;

  // ---------- 收尾：会话视图的按钮在窄屏下也不溢出 ----------
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
  await sleep(400);
  const narrow = await ev(`(function(){
    var de = document.documentElement;
    var list = document.getElementById('dm-list');
    var input = document.getElementById('dm-input');
    var send = document.getElementById('dm-send');
    var r = list.getBoundingClientRect();
    return { vw: innerWidth, docScrollW: de.scrollWidth, bodyScrollW: document.body.scrollWidth,
             listRight: Math.round(r.right), inputRight: Math.round(input.getBoundingClientRect().right),
             sendRight: Math.round(send.getBoundingClientRect().right),
             rowOverflow: [].slice.call(document.querySelectorAll('#dm-list .dm-row'))
               .filter(function(x){ return x.getBoundingClientRect().right > innerWidth + 1; }).length }; })()`);
  check(narrow.docScrollW <= narrow.vw + 1 && narrow.bodyScrollW <= narrow.vw + 1 && narrow.rowOverflow === 0,
    '★ D9 390x844 下会话视图不横向溢出（气泡与输入行都不伸出视口）', narrow);
  await send('Emulation.setDeviceMetricsOverride', { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });

  // ---------- D10：零 JS 异常 / 零 console.error ----------
  check(jsProblems.length === 0, '★ D10 全程零 JS 异常 / 零 console.error（含页面内与 python 侧）', jsProblems.slice(0, 8));

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
  try { if (peer && !peer.killed) { peerCmd('quit', {}); await sleep(300); peer.kill(); } } catch (e) { /* 已退 */ }
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
  if (failures.length) {
    console.log('失败项：');
    failures.forEach((f) => console.log('   · ' + f));
    process.exit(1);
  }
  console.log('✓ 好友私聊 UI 检查通过');
  process.exit(0);
});
