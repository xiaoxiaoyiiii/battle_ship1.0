#!/usr/bin/env node
/**
 * 「最近对手一键加好友」端到端回归检查（2026-09-19，好友批的收尾证据）。
 *
 * 为什么要有这个工具：单元测试（tests/test_friends_realtime.py）只直调 `_finalize_match`，
 * **证明不了**这条产品链真的通：
 *   真打完一局 → 服务端真给双方推 `recent_opponent` → 浏览器真的收到 → 结算屏真的
 *   长出「加好友」按钮 → 点了真的发出 `POST /api/friends/request` → 申请真的落库。
 * 本工具把这条链**拆成两半分别验**（这是本仓库的既有做法，见 friends_check.mjs 的 T3f 段）：
 *
 *   ① 服务端那半边（纯 python，**不需要浏览器**）：两个真账号、真 HTTP 登录、真 socket，
 *      真建房 / 真摆船 / 真猜拳 → 真开打 → 投降 → 走 `_finalize_match`。
 *      断言"双方各收一条 `recent_opponent`、字段齐全、方向不写反、relation 跟着关系变"。
 *      ⚠️ 必须**真开打**（进 attacking）之后再结算：`_match_really_started` 只看显式打点的
 *         `match_started_at`，没打点的房（摆船阶段就投降）结算路径不同。
 *      ⚠️ 也**不用** `test_*` 调试事件：`test_win_game` 只设 state/winner、**不调
 *         `_finalize_match`**，用它验"打完一局"会"成功但毫无反应"。
 *
 *   ② 前端那半边（无头 Edge + CDP）：浏览器真登录 B，**真跟 python 侧 A 打完一局**
 *      （不是伪造事件！），然后断言结算屏里真的出现「最近对手 + 加好友」，
 *      点它时用 CDP 的 Fetch 域把 `POST /api/friends/request` 的**请求体**抓下来比对。
 *      另有一段**本地注入**（`socket.onevent({data:[...]})`，走 socket.io 客户端真实的
 *      报文分发路径、**不重写处理逻辑**）单独钉死"前端收到之后做得对不对"的 relation 分支。
 *
 * 为什么要拆两半：注入那半绿了只说明"前端做对了"，真链路那半绿了只说明"服务端推得出来"；
 * 只有两半都绿才是这条产品链真的通（friends_check.mjs T3f 那段注释里写明了同一个道理）。
 *
 * 断言编号（报告里按这个分组读）：
 *   PH* —— 服务端那半边（纯 python）。票面主线。
 *   BG* —— 前端那半边（无头浏览器）。票面主线。
 *   PG（PG1）与 PB（PB1~PB3）—— **边角**发现，不属于票面主线，但同属这条链上的真实缺陷
 *             （游客对局会下发指向游客 sid 的 `recent_opponent`；拉黑关系的 relation
 *              前端不认识 → 渲染成可点的「加好友」）。它们红了不影响上面两条主线的结论，
 *              结尾那行会明确区分。
 *
 * 用法：
 *   node tools/recent_opponent_check.mjs --url http://127.0.0.1:5104/
 *                                      [--db .tmp/recent_opp.db] [--shot out.png] [--no-browser]
 *   `--no-browser` = 只跑服务端那半边（#1 的断言全在，前端那半明确 SKIP，不假红）。
 *
 * ⚠️ 服务端必须带 CORS_ORIGINS=http://127.0.0.1:<端口>，否则 socket.io **静默连不上**
 *    （页面零报错，后面全是假红）。起法见 CLAUDE.md 第 1 节。
 * ⚠️ 只对**隔离库**的本地服务跑：它会注册 `recentchk_*` 账号并真的写好友关系。
 * ⚠️ 本工具**不写产品代码**：新建的只有 tools/recent_opponent_check.mjs，
 *    python helper 与 profile 都落在 .tmp/（已 gitignore）。
 * ⚠️ CDP 端口固定 9362（friends_check.mjs 写死了 9361，两个工具要能同时跑）；
 *    persistent profile 放 .tmp/recent_opponent_profile，开头按 profile 路径预清理残留进程
 *    —— 残留的无头进程会让新浏览器"静默起不来"，连上的是上一轮的旧实例（假红第一大来源）。
 */

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

// ---------- 参数 ----------
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5104/').replace(/\/?$/, '/');
const SHOT = argOf('--shot', '');
const NO_BROWSER = argv.includes('--no-browser');

let HERE;
try { HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')); }
catch (e) { HERE = process.cwd(); }
const ROOT = path.resolve(HERE, '..');
const TMP = path.join(ROOT, '.tmp');
const DB = argOf('--db', path.join(TMP, 'recent_opp.db'));
const PORT = 9362;                        // ⚠️ 不能与 friends_check.mjs 的 9361 撞
const PROFILE_DIR = path.join(TMP, 'recent_opponent_profile');
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

fs.mkdirSync(TMP, { recursive: true });

// ---------- 预清理：残留的无头进程会占着调试端口 + 锁住 profile ----------
try {
  spawnSync('powershell', ['-NoProfile', '-Command',
    'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
    'Where-Object { $_.CommandLine -like \'*recent_opponent_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'],
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没有残留就够 */ }

// ---------- 断言账本 ----------
const passes = [];
const failures = [];
const skips = [];
const jsProblems = [];
let infoLines = 0;
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label +
    (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (ok) passes.push(label); else failures.push(label);
}
function skip(label, why) {
  console.log('SKIP  ' + label + '  ->  ' + why);
  skips.push(label + ' (' + why + ')');
}
// 只记录事实、不参与判定（例：事件到达顺序 —— 前端两种顺序都兜了，翻转不该算红）
function note(label, detail) {
  infoLines += 1;
  console.log('INFO  ' + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
}

// game.js 正被另一个智能体改：把跑的时候那一份的指纹记下来，避免"跑着跑着代码变了"。
function fileFingerprint(p) {
  try {
    const buf = fs.readFileSync(p);
    return { sha256: crypto.createHash('sha256').update(buf).digest('hex').slice(0, 16),
      bytes: buf.length, mtime: fs.statSync(p).mtime.toISOString() };
  } catch (e) { return { error: String(e && e.message) }; }
}

// ---------- 账号 ----------
const SUFFIX = String(Date.now()).slice(-6);
const PW = 'recentchk123456';
const B = 'recentchk_b' + SUFFIX;          // 浏览器里的那个人

// ---------- Node 侧账号辅助（注册 + 登录 + cookie 反查 username） ----------
//
// ⚠️ 登录失败**也会种 session cookie**（响应里带的是错误 flash），所以"拿到了 cookie"
//    根本不等于"登录成功了" —— 必须拿它去 /api/profile 反查 username 才算数。
async function nodeAuth(base, username) {
  const post = (p) => fetch(base + p, {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: username, password: PW }).toString()
  });
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
  let cookie = await verify(readCookie(await post('login')));
  if (cookie) return cookie;
  await post('register');
  cookie = await verify(readCookie(await post('login')));
  return cookie;
}
function readCookie(resp) {
  const raw = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [resp.headers.get('set-cookie')].filter(Boolean);
  const pairs = raw.map((c) => String(c).split(';')[0]).filter(Boolean);
  return pairs.length ? pairs.join('; ') : '';
}
async function profileOf(cookie) {
  try {
    const r = await fetch(APP + 'api/profile', { headers: { Accept: 'application/json', Cookie: cookie } });
    if (!r.ok) return null;
    const body = await r.json();
    return body && body.profile ? body.profile : null;
  } catch (e) { return null; }
}
async function friendsOf(cookie) {
  try {
    const r = await fetch(APP + 'api/friends', { headers: { Accept: 'application/json', Cookie: cookie } });
    const text = await r.text();
    try { return { status: r.status, body: JSON.parse(text) }; } catch (e) { return { status: r.status, body: null }; }
  } catch (e) { return { status: 0, body: null, error: String(e && e.message) }; }
}

// ===========================================================================
// python 侧（**内嵌**，与 friends_check.mjs 同一个做法）
// ---------------------------------------------------------------------------
// 两个用途：
//   half1 —— 纯服务端那半边：两个真账号真打完一局，把双方收到的东西原样吐出来。
//   peer  —— 浏览器那半边的陪练：真登录 + 真 socket + 真建房坐在里面，按命令文件干活。
// 不这样拆的话，"服务端到底发了没发"就只能靠浏览器里的现象反推 —— 而浏览器那边
// 前端还有一层 game_over 的兜底渲染（`recentOpponentState.name || gameState.opponentName`），
// 光看 DOM 分不清"事件真的到了"还是"靠对手名兜底画出来的"。
// ===========================================================================
const PY_HELPER = path.join(TMP, 'recent_opponent_peer.py');
fs.writeFileSync(PY_HELPER, String.raw`
# -*- coding: utf-8 -*-
"""recent_opponent_check.mjs 用的 python 侧（每行 stdout 一个 JSON 对象）。

mode=half1 <base>
    纯服务端那半边：A/B 两个真账号 → 真登录 → 真 socket → 建自定义房 → 双方摆船 →
    猜拳 → 真开打（attacking）→ 投降（走 _finalize_match）。
    第 2 局先让 A 给 B 发一条好友申请，用来看 relation 的**方向**对不对。
    第 3 局是**边角**：登录用户 vs 游客（游客没登录，Player.user_id 其实是入座 sid）。

mode=peer <base> <user> <pwd> <cmd_file>
    浏览器那半边的陪练 A：建房 → 摆船 → 猜拳 → 投降；命令文件驱动。
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import socketio

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PW = 'recentchk123456'
# 形状必须与前端 gameState.ships 一致（{'positions':[{'x','y'}],'hits':[]}）：
# 少 hits 时服务端 PlayerShip(**x) 会 TypeError —— 表现是**不回 ack、船没放上**，
# 而后面照样能进攻击阶段 → "打完一局"那条断言会假绿得非常彻底（rank_e2e.py 踩过）。
SHIPS = [{'positions': [{'x': i, 'y': 0}], 'hits': []} for i in range(6)]


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


class Client(object):
    """一个"浏览器"：带 cookie 罐的 HTTP 客户端 + 复用同一罐的 socket。"""

    def __init__(self, name, base, guest=False):
        self.name = name
        self.base = base
        self.guest = guest
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.sio = socketio.Client(reconnection=False)
        self.events = []
        self.uid = None
        self.room = None
        self.pid = None

        @self.sio.on('*')
        def _all(event, data=None):
            self.events.append((event, data))

    # ---- HTTP ----
    def post_form(self, path, data):
        req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode())
        try:
            with self.http.open(req, timeout=20) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def post_json(self, path, payload):
        req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        try:
            with self.http.open(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode('utf-8', 'replace'))
            except Exception:
                return e.code, None
        except Exception as e:
            return 0, str(e)

    def login(self):
        """真注册 + 真登录，再用 /api/profile 反查（拿 cookie 不等于登录成功）。"""
        self.post_form('/register', {'username': self.name, 'password': PW})
        self.post_form('/login', {'username': self.name, 'password': PW})
        try:
            with self.http.open(self.base + '/api/profile', timeout=20) as r:
                profile = json.loads(r.read().decode('utf-8', 'replace')).get('profile') or {}
            if str(profile.get('username')) != self.name:
                return False
            self.uid = str(profile.get('id'))
            return True
        except Exception:
            return False

    def connect(self):
        headers = {}
        if not self.guest:
            headers['Cookie'] = '; '.join('%s=%s' % (c.name, c.value) for c in self.jar)
        self.sio.connect(self.base, headers=headers, transports=['polling'])

    # ---- socket ----
    def emit(self, event, data, timeout=8.0):
        box = {}

        def cb(resp):
            box['resp'] = resp

        self.sio.emit(event, data, callback=cb)
        end = time.time() + timeout
        while 'resp' not in box and time.time() < end:
            time.sleep(0.02)
        return box.get('resp')

    def all_of(self, event):
        return [d for n, d in self.events if n == event]

    def names(self):
        return [n for n, _ in self.events]

    def state(self):
        """最新 state：猜拳阶段服务端只推 rps_result（**不推 game_state**），两边都要看。"""
        for ev in ('game_state', 'rps_result'):
            for n, d in reversed(self.events):
                if n == ev and isinstance(d, dict) and d.get('state'):
                    return d['state']
        try:
            for n, d in reversed(self.events):
                if n == 'game_over':
                    return 'game_over'
        except Exception:
            pass
        return None

    def snapshot(self):
        return {
            'uid': self.uid,
            'username': self.name,
            'events': self.names(),
            'recent': self.all_of('recent_opponent'),
            'game_over': self.all_of('game_over'),
            'friend_request': self.all_of('friend_request'),
        }


def place_both(room, a, b):
    pa = a.emit('place_ships', {'room_id': room, 'player_id': a.pid, 'ships': SHIPS})
    pb = b.emit('place_ships', {'room_id': room, 'player_id': b.pid, 'ships': SHIPS})
    return [pa, pb]


def drive_to_attacking(room, a, b, tries=14):
    """推到 attacking。

    ⚠️ 为什么一定要走到 attacking：_match_really_started(room) 只看
    room.match_started_at（唯一打点是 handle_rps_choice 里猜拳结束那一刻），
    没打点的房**不会真结算**，也就不会有 recent_opponent。摆船阶段就投降 = 白验。
    ⚠️ 两边必须出**不同**的手：都出 rock 会永远平局（rank_e2e.py 第一版踩过）。
    """
    for _ in range(tries):
        if a.state() == 'attacking':
            return True
        a.emit('rps_choice', {'room_id': room, 'player_id': a.pid, 'choice': 'rock'})
        b.emit('rps_choice', {'room_id': room, 'player_id': b.pid, 'choice': 'scissors'})
        time.sleep(0.7)
    return a.state() == 'attacking'


def run_half1(base):
    sfx = uuid.uuid4().hex[:6]
    a = Client('recentchk_a' + sfx, base)
    b = Client('recentchk_b' + sfx, base)
    ok_a, ok_b = a.login(), b.login()
    out(event='login', ok=[ok_a, ok_b], a={'uid': a.uid, 'username': a.name},
        b={'uid': b.uid, 'username': b.name})
    if not (ok_a and ok_b):
        out(event='abort', why='账号没登进去')
        return 1
    a.connect()
    b.connect()
    a.pid, b.pid = a.uid, b.uid
    out(event='connected', ok=[a.sio.connected, b.sio.connected])
    if not (a.sio.connected and b.sio.connected):
        out(event='abort', why='socket 没连上（CORS_ORIGINS 放行本端口了吗）')
        return 1

    # ---- 第 1 局：干净的两个账号，relation 应当两边都是 'none' ----
    ack = a.emit('create_room', {'player_name': a.name})
    room = (ack or {}).get('room_id')
    a.room = b.room = room
    jack = b.emit('join_room', {'room_id': room, 'player_name': b.name})
    b.pid = (jack or {}).get('player_id') or b.uid
    acks = place_both(room, a, b)
    started = drive_to_attacking(room, a, b)
    state_before = [a.state(), b.state()]
    sur = b.emit('surrender', {'room_id': room, 'player_id': b.pid})
    time.sleep(3.0)
    out(event='round', round=1, room=room, create_ack=ack, join_ack=jack,
        place_acks=acks, started=started, state_before=state_before,
        surrender_ack=sur, a=a.snapshot(), b=b.snapshot())

    # ---- 第 2 局：先让 A 给 B 发申请，再看 relation 的**方向**对不对 ----
    rh, rbody = a.post_json('/api/friends/request', {'username': b.name})
    out(event='friend_request_made', http=rh, body=rbody)
    a.events = []
    b.events = []
    ack2 = a.emit('create_room', {'player_name': a.name})
    room2 = (ack2 or {}).get('room_id')
    a.room = b.room = room2
    jack2 = b.emit('join_room', {'room_id': room2, 'player_name': b.name})
    b.pid = (jack2 or {}).get('player_id') or b.uid
    acks2 = place_both(room2, a, b)
    started2 = drive_to_attacking(room2, a, b)
    sur2 = b.emit('surrender', {'room_id': room2, 'player_id': b.pid})
    time.sleep(3.0)
    out(event='round', round=2, room=room2, place_acks=acks2, started=started2,
        state_before=[a.state(), b.state()], surrender_ack=sur2,
        a=a.snapshot(), b=b.snapshot())

    # ---- 第 3 局（边角）：登录用户 vs **游客**，自定义房的游客 user_id 其实是 sid ----
    guest = Client('guest', base, guest=True)
    guest.connect()
    a.events = []
    ack3 = a.emit('create_room', {'player_name': a.name})
    room3 = (ack3 or {}).get('room_id')
    jack3 = guest.emit('join_room', {'room_id': room3, 'player_name': '路边游客'})
    # ⚠️ 必须用 ack 里回的 player_id：polling 下客户端自己的 sio.sid 与 request.sid **不同**
    guest.pid = (jack3 or {}).get('player_id')
    pa = a.emit('place_ships', {'room_id': room3, 'player_id': a.pid, 'ships': SHIPS})
    pg = guest.emit('place_ships', {'room_id': room3, 'player_id': guest.pid, 'ships': SHIPS})
    for _ in range(14):
        if a.state() == 'attacking':
            break
        a.emit('rps_choice', {'room_id': room3, 'player_id': a.pid, 'choice': 'rock'})
        guest.emit('rps_choice', {'room_id': room3, 'player_id': guest.pid, 'choice': 'scissors'})
        time.sleep(0.7)
    sur3 = guest.emit('surrender', {'room_id': room3, 'player_id': guest.pid})
    time.sleep(3.0)
    # 这条 recent_opponent 指向的是游客 → 前端会照着渲染一个「加好友」按钮。
    # 拿它去真的打一次申请接口，看看会怎么样（证据而不是推测）。
    probe = None
    recents = a.all_of('recent_opponent')
    if recents:
        probe = a.post_json('/api/friends/request', {'username': recents[0].get('username')})
    out(event='guest_round', room=room3, join_ack=jack3, place_acks=[pa, pg],
        state_before=[a.state(), guest.state()], surrender_ack=sur3,
        guest_pid=guest.pid, a_recent=recents, guest_recent=guest.all_of('recent_opponent'),
        add_friend_probe=probe)

    # ---- 第 4 局（边角）：**拉黑**之后，relation 会下发 blocked_by_me / blocked_me ----
    # 动机：server.py 的 FRIEND_RELATIONS 含这两个取值，而 static/game.js 的
    # FRIEND_RELATIONS 里没有 —— 前端对未知取值一律降级成 'none'，
    # 也就是会把"拉黑关系"渲染成一个**可点的「加好友」**。这里把原始事实钉下来。
    block_ack = a.post_json('/api/friends/block', {'username': b.name})
    a.events = []
    b.events = []
    ack4 = a.emit('create_room', {'player_name': a.name})
    room4 = (ack4 or {}).get('room_id')
    a.room = b.room = room4
    b.emit('join_room', {'room_id': room4, 'player_name': b.name})
    place_both(room4, a, b)
    drive_to_attacking(room4, a, b)
    b.emit('surrender', {'room_id': room4, 'player_id': b.pid})
    time.sleep(3.0)
    # 被拉黑方照着前端那个按钮点一下，看看服务端回什么（不透出"是谁拉黑的"是有意的）
    blocked_request = b.post_json('/api/friends/request', {'username': a.name})
    out(event='blocked_round', room=room4, block_ack=block_ack,
        a_recent=a.all_of('recent_opponent'), b_recent=b.all_of('recent_opponent'),
        blocked_request=blocked_request)

    try:
        a.sio.disconnect()
    except Exception:
        pass
    try:
        b.sio.disconnect()
    except Exception:
        pass
    try:
        guest.sio.disconnect()
    except Exception:
        pass
    out(event='done')
    return 0


def run_peer(base, username, cmd_file):
    """浏览器那半边的陪练：建房 → 等命令（place / rps / surrender / report / quit）。"""
    c = Client(username, base)
    if not c.login():
        out(event='fatal', why='登录失败')
        return 1
    c.connect()
    if not c.sio.connected:
        out(event='fatal', why='socket 没连上')
        return 1
    c.pid = c.uid
    ack = c.emit('create_room', {'player_name': username})
    c.room = (ack or {}).get('room_id')
    out(event='room', room_id=c.room, user_id=c.uid, username=username,
        connected=c.sio.connected)

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
        cmd, seq = job.get('cmd'), job.get('seq')
        if cmd == 'quit':
            out(event='cmd_result', seq=seq, cmd=cmd, ok=True)
            break
        try:
            if cmd == 'place':
                resp = c.emit('place_ships', {'room_id': c.room, 'player_id': c.pid, 'ships': SHIPS})
                out(event='cmd_result', seq=seq, cmd=cmd, ok=True, resp=resp, state=c.state())
            elif cmd == 'rps':
                # 一直出 rock，直到服务端进 attacking（浏览器那侧出 scissors，不会平局）
                got = False
                for _ in range(16):
                    if c.state() == 'attacking':
                        got = True
                        break
                    c.emit('rps_choice', {'room_id': c.room, 'player_id': c.pid, 'choice': 'rock'})
                    time.sleep(0.7)
                if c.state() == 'attacking':
                    got = True
                out(event='cmd_result', seq=seq, cmd=cmd, ok=got, state=c.state())
            elif cmd == 'surrender':
                resp = c.emit('surrender', {'room_id': c.room, 'player_id': c.pid})
                out(event='cmd_result', seq=seq, cmd=cmd, ok=True, resp=resp)
            elif cmd == 'report':
                out(event='cmd_result', seq=seq, cmd=cmd, ok=True, report=c.snapshot())
            else:
                out(event='cmd_result', seq=seq, cmd=cmd, ok=False, why='unknown cmd')
        except Exception as e:
            out(event='cmd_result', seq=seq, cmd=cmd, ok=False, why=str(e))

    # 退出前把最终观测单独吐一份，免得收尾那一下丢事件
    out(event='final_report', report=c.snapshot())
    try:
        c.sio.disconnect()
    except Exception:
        pass
    return 0


def main():
    if len(sys.argv) < 3:
        out(event='fatal', why='参数不足')
        return 2
    base = sys.argv[1].rstrip('/')
    mode = sys.argv[2]
    if mode == 'half1':
        return run_half1(base)
    if mode == 'peer':
        # argv: [脚本, base, mode, 用户名, 密码, 命令文件]
        return run_peer(base, sys.argv[3], sys.argv[5])
    out(event='fatal', why='unknown mode ' + mode)
    return 2


if __name__ == '__main__':
    sys.exit(main())
`, 'utf8');

const CMD_FILE = path.join(TMP, 'recent_opponent_cmd.json');

// 逐行读 python helper 的 stdout（每行一个 JSON）
function makeLineReader(onLine) {
  let buf = '';
  return (chunk) => {
    buf += chunk.toString('utf8');
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line.startsWith('{')) continue;
      try { onLine(JSON.parse(line)); } catch (e) { /* 非 JSON 行忽略 */ }
    }
  };
}

// ===========================================================================
// ① 服务端那半边：纯 python（不需要浏览器）
// ===========================================================================
function pyLines(lines, event) { return lines.filter((l) => l.event === event); }
function roundOf(lines, n) { return lines.find((l) => l.event === 'round' && l.round === n); }

const RELATIONS = ['none', 'self', 'friends', 'pending_out', 'pending_in', 'blocked_by_me', 'blocked_me'];

async function runServerHalf() {
  console.log('');
  console.log('-- ① 服务端那半边（python：真账号 / 真 socket / 真打完一局）--');
  if (!fs.existsSync(PY_HELPER)) { skip('① 服务端那半边', 'python helper 没写出来'); return; }
  const lines = [];
  let stderr = '';
  const p = spawn('python', [PY_HELPER, APP, 'half1'], {
    cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, stdio: ['ignore', 'pipe', 'pipe']
  });
  p.stdout.on('data', makeLineReader((o) => lines.push(o)));
  p.stderr.on('data', (d) => { stderr += d.toString('utf8'); });
  const exitCode = await new Promise((res) => {
    const t = setTimeout(() => { try { p.kill(); } catch (e) { /* 已退 */ } res('timeout'); }, 180000);
    p.on('exit', (code) => { clearTimeout(t); res(code); });
  });

  if (/ModuleNotFoundError|No module named/.test(stderr)) {
    skip('① 服务端那半边（全部）', 'python 缺依赖（requests / python-socketio）：' +
      stderr.split('\n').filter((l) => /ModuleNotFoundError/.test(l)).slice(0, 2).join(' '));
    return;
  }
  const fatal = lines.find((l) => l.event === 'fatal' || l.event === 'abort');
  if (exitCode !== 0 || fatal) {
    check(false, '★ PH0 python helper 正常跑完（exit=0 且没有 fatal/abort）',
      { exit: exitCode, fatal: fatal || null, stderrTail: stderr.replace(/\s+/g, ' ').slice(-400) });
    if (!lines.length) return;
  } else {
    check(true, '★ PH0 python helper 正常跑完（exit=0，无 fatal/abort）', { exit: exitCode, lines: lines.length });
  }

  const login = pyLines(lines, 'login')[0];
  const conn = pyLines(lines, 'connected')[0];
  check(!!login && Array.isArray(login.ok) && login.ok[0] === true && login.ok[1] === true
        && !!login.a.uid && !!login.b.uid,
    '★ PH1 两个真账号注册 + 登录成功（uid 是 /api/profile 反查出来的，不是猜的）',
    login ? { ok: login.ok, a: login.a, b: login.b } : lines.slice(0, 3));
  check(!!conn && conn.ok[0] === true && conn.ok[1] === true,
    '★ PH2 两个 socket 都连上了（带 cookie；连不上后面全是静默假红）', conn || lines.slice(0, 3));
  if (!login || !conn) return;

  const r1 = roundOf(lines, 1);
  const r2 = roundOf(lines, 2);
  check(!!r1, '★ PH3 第 1 局跑起来了（建房 / 入房 / 摆船 / 猜拳 / 投降都拿到了回执）',
    r1 || lines.slice(-3));
  if (!r1) return;
  check(r1.create_ack && r1.create_ack.status === 'success' && !!r1.room
        && r1.join_ack && r1.join_ack.status === 'success',
    '★ PH3b 自定义房建起来了、第二个人真入座了', { create: r1.create_ack, join: r1.join_ack });
  check(Array.isArray(r1.place_acks) && r1.place_acks.every((x) => x && x.status === 'success'),
    '★ PH3c 双方摆船 ack 都是 success（少 hits 字段会静默失败，所以必须断言 ack）', r1.place_acks);
  // 门禁：没真开打的房**不会真结算** —— 先钉死"这一局确实开打了"，否则后面全是空转
  check(r1.started === true && r1.state_before[0] === 'attacking' && r1.state_before[1] === 'attacking',
    '★ PH4 第 1 局**真的开打**了（state=attacking，match_started_at 已打点）', r1.state_before);
  check(r1.surrender_ack && r1.surrender_ack.status === 'success',
    '★ PH5 开打之后投降被受理（走的是 _finalize_match，不是调试桩）', r1.surrender_ack);

  const ra = r1.a.recent || [];
  const rb = r1.b.recent || [];
  check(ra.length === 1, '★ PH6 胜者 A 收到**恰好 1 条** recent_opponent', ra);
  check(rb.length === 1, '★ PH7 败者 B 收到**恰好 1 条** recent_opponent', rb);
  if (ra.length === 1) {
    const p0 = ra[0];
    const fields = ['user_id', 'username', 'avatar', 'relation'];
    check(fields.every((k) => k in p0), '★ PH8a A 那条的字段齐全（' + fields.join('/') + '）', p0);
    check(String(p0.user_id) === String(r1.b.uid) && String(p0.username) === String(r1.b.username),
      '★ PH8b A 那条指向 B（user_id 与 username 都对得上）',
      { got: [p0.user_id, p0.username], expect: [r1.b.uid, r1.b.username] });
    check(typeof p0.avatar === 'string' && RELATIONS.indexOf(p0.relation) >= 0 && p0.relation === 'none',
      '★ PH8c avatar 是字符串、relation 是冻结取值里的 none（两个陌生账号）', p0);
  }
  if (rb.length === 1) {
    const p1 = rb[0];
    check(String(p1.user_id) === String(r1.a.uid) && String(p1.username) === String(r1.a.username),
      '★ PH9 B 那条指向 A（**方向不许写反** —— 一人一条、各算各的 relation）',
      { got: [p1.user_id, p1.username], expect: [r1.a.uid, r1.a.username] });
  }
  check(r1.a.game_over.length === 1 && r1.b.game_over.length === 1
        && r1.a.game_over[0].winner === r1.a.uid && r1.a.game_over[0].reason === 'surrender',
    '★ PH10 双方都收到 game_over（reason=surrender、winner=胜者 uid）',
    { a: r1.a.game_over, b: r1.b.game_over });
  const ia = r1.a.events.indexOf('recent_opponent');
  const iga = r1.a.events.indexOf('game_over');
  note('PH11 事件顺序（事实，不是需求：前端两种顺序都兜了）',
    { recent_opponent: ia, game_over: iga, 先到: ia >= 0 && iga >= 0 && ia < iga ? 'recent_opponent' : 'game_over' });

  // 第 2 局：relation 的方向
  const made = pyLines(lines, 'friend_request_made')[0];
  check(!!made && made.http === 200 && made.body && made.body.status === 'sent',
    '★ PH12 第 2 局前 A 给 B 发好友申请成功（走真接口，status=sent）', made);
  if (r2) {
    const ra2 = (r2.a.recent || [])[0];
    const rb2 = (r2.b.recent || [])[0];
    check(r2.started === true && r2.surrender_ack && r2.surrender_ack.status === 'success',
      '★ PH13a 第 2 局也真开打并结算了', { started: r2.started, sur: r2.surrender_ack });
    check(!!ra2 && ra2.relation === 'pending_out' && !!rb2 && rb2.relation === 'pending_in',
      '★ PH13b relation 是"我→对手"且**两边各算各的**：A=pending_out / B=pending_in',
      { a: ra2 && ra2.relation, b: rb2 && rb2.relation, aPayload: ra2, bPayload: rb2 });
  } else {
    check(false, '★ PH13b relation 方向（第 2 局没跑出来）', lines.slice(-3));
  }

  // ---- 边角：登录用户 vs 游客 ----
  const g = pyLines(lines, 'guest_round')[0];
  console.log('   边角：登录用户 vs 游客');
  if (!g) {
    check(false, '★ PG1 边角用例（登录用户 vs 游客）跑出来了', lines.slice(-3));
  } else {
    const guestUid = String(g.guest_pid || '');
    const bogus = (g.a_recent || []).filter((p) => String(p.user_id) === guestUid);
    check(bogus.length === 0,
      '★ PG1 [边角] 登录用户 vs 游客结算时，**不该**收到指向游客的 recent_opponent（游客不是账号）',
      { a_recent: g.a_recent, guest_player_id: guestUid,
        add_friend_probe: g.add_friend_probe,
        why: '游客的 Player.user_id 在自定义房里是**入座 sid**（非空），'
           + '_recent_opponent_payloads 那句"双方都得有 uid 才发、游客局自然被跳过"因此不成立' });
  }
  // ---- 边角：拉黑之后下发的 relation ----
  const blk = pyLines(lines, 'blocked_round')[0];
  console.log('   边角：拉黑之后');
  if (!blk) {
    check(false, '★ PB1 边角用例（拉黑之后）跑出来了', lines.slice(-3));
  } else {
    const pa = (blk.a_recent || [])[0];
    const pb = (blk.b_recent || [])[0];
    check(!!pa && pa.relation === 'blocked_by_me' && !!pb && pb.relation === 'blocked_me',
      '★ PB1 [边角] 拉黑之后下发的 relation 是 blocked_by_me(A 侧) / blocked_me(B 侧)'
      + '—— 这两个取值前端必须认识，否则会被降级成 none',
      { a: pa && pa.relation, b: pb && pb.relation, block_ack: blk.block_ack });
    const br = blk.blocked_request || [0, null];
    const bodyKeys = br[1] && typeof br[1] === 'object' ? Object.keys(br[1]) : [];
    const hasReason = bodyKeys.indexOf('error') >= 0 || bodyKeys.indexOf('message') >= 0;
    // ⚠️ 这条**原来照缺陷形状写的**（断言 "body 里没有 error" —— 那样绿只说明"缺陷还在"）。
    //    服务端补上中文原因之后它必然翻红，而红的含义刚好相反：**缺陷已修**。
    //    所以判据翻成正向：`status=blocked` 且**必须**带 error/message。
    check(br[0] === 200 && !!(br[1] && br[1].status === 'blocked') && hasReason,
      '★ PB2 [边角] 被拉黑方再申请：服务端回 `status=blocked` **并带一句中文原因**'
      + '（前端 apiReason 只认 error/message，否则只能弹一句通用文案）',
      { http: br[0], body: br[1], keys: bodyKeys });
  }

  note('② 服务端那半边用到的连接都已断开', null);
}

// ===========================================================================
// ② 前端那半边（无头浏览器 + CDP）
// ===========================================================================
let browser = null, ws = null, seq = 0;
const pending = new Map();
let peer = null;
const peerEvents = [];
let cmdSeq = 0;
let friendsRequestPosts = [];       // 抓到的 POST /api/friends/request（method/url/body）
const wsFrames = [];                // socket.io 走 websocket 时的下行报文
const pollBodies = [];              // socket.io 走 polling 时的下行响应体（没升级到 ws 时的兜底）

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
  await sleep(400);
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
    await send('Network.setCookie', { name: p.slice(0, i), value: p.slice(i + 1), domain: u.hostname, path: '/', url: APP });
  }
}
async function clearCookies() {
  try { await send('Network.clearBrowserCookies'); } catch (e) { /* 没开 Network 域就够 */ }
}

// 遮挡探针：矩形内 3x3 采样 elementFromPoint。
// 用来区分「**没渲染**」与「渲染了但被别的东西压住了」—— 只断言"元素存在"是弱断言。
const PROBE = (sel) => '(function(){'
  + 'var el = document.querySelector(' + JSON.stringify(sel) + ');'
  + 'if (!el) return {present:false};'
  + 'var cs = getComputedStyle(el);'
  + 'if (cs.display === "none" || cs.visibility === "hidden") return {present:false, hidden:true, display:cs.display, visibility:cs.visibility};'
  + 'var r = el.getBoundingClientRect();'
  + 'if (r.width <= 0 || r.height <= 0) return {present:false, zero:true, rect:{w:r.width,h:r.height}};'
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
  + 'return {present:true, samples:samples, occluded:occluded, worst:worst, inViewport:(samples>0),'
  + '  rect:{x:Math.round(r.left),y:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)}};'
  + '})()';

function startPeer() {
  try { fs.unlinkSync(CMD_FILE); } catch (e) { /* 没有就够 */ }
  const p = spawn('python', [PY_HELPER, APP, 'peer', A_USER, PW, CMD_FILE], {
    cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, stdio: ['ignore', 'pipe', 'pipe']
  });
  p.stdout.on('data', makeLineReader((o) => peerEvents.push(o)));
  p.stderr.on('data', (d) => {
    const s = d.toString('utf8');
    if (/Traceback|Error/.test(s)) jsProblems.push('python 侧: ' + s.replace(/\s+/g, ' ').slice(0, 220));
  });
  return p;
}
let A_USER = '';
function peerCmd(cmd, extra) {
  const s = ++cmdSeq;
  fs.writeFileSync(CMD_FILE, JSON.stringify(Object.assign({ seq: s, cmd: cmd }, extra || {})), 'utf8');
  return s;
}
function waitPeerCmd(s, timeout) {
  return waitFor(() => peerEvents.find((e) => e.event === 'cmd_result' && e.seq === s), timeout, 'python 侧命令回执 #' + s);
}

async function runBrowserHalf() {
  console.log('');
  console.log('-- ② 前端那半边（无头 Edge：真打完一局 → 结算屏 → 点「加好友」）--');

  if (!BROWSER) {
    skip('② 前端那半边（全部）', '找不到 Edge/Chrome');
    return;
  }

  const cookieB = await nodeAuth(APP, B);
  check(!!cookieB, '★ BG0a 浏览器侧账号 B 注册/登录成功并拿到 cookie', cookieB ? cookieB.split('=')[0] + '=…' : cookieB);
  const profB = cookieB ? await profileOf(cookieB) : null;
  const bUid = profB ? String(profB.id) : '';
  check(!!bUid, '★ BG0b 能读到 B 的 user_id（后面要拿它比对事件 payload）', bUid || profB);
  if (!cookieB || !bUid) return;

  // ---------- 起无头浏览器 ----------
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
  if (!target) throw new Error('无法连接无头浏览器调试端口 ' + PORT + '（残留进程占着？）');
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
      console.log('   [异常详情] ' + String(desc).slice(0, 600));
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 180));
    }
    // ---- socket 线路证据：WS 帧 + polling 响应体，两路都收 ----
    // 光看 DOM 分不清"事件真的到了"还是"前端靠 gameState.opponentName 兜底画出来的"，
    // 所以这里直接把**到达浏览器的报文**抓下来（既不看 DOM 也不看内存状态）。
    if (m.method === 'Network.webSocketFrameReceived') {
      const pd = (m.params.response || {}).payloadData || '';
      if (pd) wsFrames.push(pd);
    }
    if (m.method === 'Network.responseReceived' && /\/socket\.io\//.test((m.params.response || {}).url || '')) {
      const rid = m.params.requestId;
      send('Network.getResponseBody', { requestId: rid }).then((r) => {
        if (r && r.body && /recent_opponent/.test(r.body)) pollBodies.push(r.body);
      }).catch(() => {});
    }
    // ---- Fetch 域：把 POST /api/friends/request 的请求体抓下来，然后放行 ----
    if (m.method === 'Fetch.requestPaused') {
      const req = m.params.request || {};
      if (/\/api\/friends\/request(\?|$)/.test(String(req.url || ''))) {
        friendsRequestPosts.push({ method: req.method, url: req.url, body: req.postData || '' });
      }
      send('Fetch.continueRequest', { requestId: m.params.requestId }).catch(() => {});
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
  await send('Emulation.setDeviceMetricsOverride', { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });
  await sleep(300);

  // ---------- 陪练 A（python）：建房并坐在里面 ----------
  A_USER = 'recentchk_a' + SUFFIX;
  peer = startPeer();
  const peerReady = await (async () => {
    try {
      return await waitFor(() => peerEvents.find((e) => e.event === 'room'), 40000, 'python 侧 A 建房');
    } catch (e) { return null; }
  })();
  if (!peerReady || !peerReady.room_id) {
    check(false, '★ BG1 python 侧陪练 A 登录 + 建房成功（后面整条真链路都靠它）',
      peerReady || peerEvents.slice(-3));
    return;
  }
  const roomId = String(peerReady.room_id);
  const aUid = String(peerReady.user_id || '');
  const aName = String(peerReady.username || A_USER);
  check(!!aUid, '★ BG1 python 侧陪练 A 登录 + 建房成功（房间号与 uid 都拿到了）',
    { room_id: roomId, user_id: aUid, username: aName });

  // ---------- 浏览器以 B 的身份进同一个房（走 `?room=` 那条既有自动入房逻辑） ----------
  await clearCookies();
  await setCookie(cookieB);
  await goto(APP + '?room=' + roomId, APP + '?room=' + roomId);
  const meB = await ev('window.__USERNAME || null');
  check(meB === B, '★ BG2 浏览器页面认得当前登录用户是 B', { page: meB, expect: B });

  const sockOk = await waitFor(async () => {
    const o = await ev('(function(){ return { has: !!window.gameState.socket, connected: window.gameState.socket ? window.gameState.socket.connected : false }; })()');
    return o && o.connected ? o : null;
  }, 20000, 'B 的页面 socket 连上服务端').catch(() => null);
  check(!!sockOk, '★ BG3 B 的 socket 真的连上了（连不上后面全是静默假红：CORS_ORIGINS 必须放行 ' + APP + '）', sockOk);

  const joined = await waitFor(async () => {
    const o = await ev(`(function(){
      var g = window.gameState || {};
      var sp = document.getElementById('ship-placement-screen');
      return { room: g.roomId || null, playerId: g.playerId || null, opponentName: g.opponentName || null,
               placementActive: sp ? sp.classList.contains('active') : null,
               cells: document.querySelectorAll('#player-board .cell').length }; })()`);
    return (o && o.room === roomId) ? o : null;
  }, 20000, '浏览器真的进了服务端给的那个房').catch(() => null);
  check(!!joined, '★ BG4 经 `?room=` 自动入房成功：gameState.roomId == 服务端给的房间号 且摆船屏 active',
    { joined: joined, expect: roomId });
  if (!joined) return;
  // ⚠️ 这里必须**等**棋盘格子出来：`joinRoomById` 的 ack 一到就把摆船屏切上来，
  //    而棋盘格子是服务端那条 `game_state(state=placing_ships)` 到达之后
  //    `initBoard(playerBoard, true)` 才建的 —— 两个事件不同时到，
  //    立刻取样会读到 0 个格子（工具自己的假红；实测踩过一次）。
  const boardReady = await waitFor(async () => {
    const n = await ev('document.querySelectorAll("#player-board .cell").length');
    return n === 36 ? n : null;
  }, 15000, '#player-board 渲染出 36 个格子').catch(() => null);
  check(boardReady === 36, '★ BG5 摆船屏真的有 36 个格子可点（否则"摆船成功"无从谈起）', boardReady);

  // ---------- 双方摆船：A 先摆（python 侧），B 点 6 格 + 确认 ----------
  const pseq = peerCmd('place');
  const pres = await waitPeerCmd(pseq, 30000).catch(() => null);
  check(!!pres && pres.ok === true, '★ BG6 python 侧 A 摆船回执 success', pres);

  const placed = await ev(`(function(){
    var cells = [].slice.call(document.querySelectorAll('#player-board .cell'));
    var byKey = {};
    cells.forEach(function(c){ byKey[c.dataset.x + ',' + c.dataset.y] = c; });
    var clicked = [];
    for (var i = 0; i < 6; i++) { var c = byKey[i + ',0']; if (c) { c.click(); clicked.push(i + ',0'); } }
    var btn = document.getElementById('confirm-ships');
    return { clicked: clicked, ships: (window.gameState.ships || []).length,
             btnHidden: btn.classList.contains('hidden'),
             shipsLabel: (document.getElementById('ships-placed') || {}).textContent };
  })()`);
  check(placed.ships === 6 && placed.btnHidden === false,
    '★ BG7 点满 6 格后 gameState.ships 有 6 艘且 #confirm-ships 从 hidden 变可见',
    placed);

  await clickJs('document.getElementById("confirm-ships")');
  const rpsShown = await waitFor(async () => {
    const o = await ev(`(function(){
      var r = document.getElementById('rps-screen');
      return { active: r ? r.classList.contains('active') : null,
               text: (document.getElementById('rps-result') || {}).textContent }; })()`);
    return (o && o.active === true) ? o : null;
  }, 20000, '点确认后切到猜拳屏（= 服务端确认双方都摆好了）').catch(() => null);
  check(!!rpsShown, '★ BG8 点 #confirm-ships 后服务端确认双方都摆好了 → 切到 #rps-screen',
    rpsShown);

  // ---------- 猜拳：A 出 rock，B 点 scissors（不会平局） ----------
  const rseq = peerCmd('rps');
  await clickJs('document.querySelector("#rps-screen [data-choice=\\"scissors\\"]")');
  const fighting = await waitFor(async () => {
    const o = await ev(`(function(){
      var g = document.getElementById('game-screen');
      return { active: g ? g.classList.contains('active') : null }; })()`);
    return (o && o.active === true) ? o : null;
  }, 30000, '对局真的开打（切到 #game-screen）').catch(() => null);
  const rres = await waitPeerCmd(rseq, 40000).catch(() => null);
  check(!!fighting, '★ BG9 对局真的开打（浏览器切到 #game-screen）—— 没开打就不会真结算', fighting);
  check(!!rres && rres.state === 'attacking',
    '★ BG9b 陪练侧也确认服务端已经进 attacking（match_started_at 已打点）', rres);

  // ---------- A 投降 → B 获胜 → 结算 ----------
  const sseq = peerCmd('surrender');
  const sres = await waitPeerCmd(sseq, 30000).catch(() => null);
  check(!!sres && sres.ok === true && sres.resp && sres.resp.status === 'success',
    '★ BG10 投降被服务端受理（这条会走 _finalize_match，recent_opponent 就挂在那里）', sres);

  const settled = await waitFor(async () => {
    const o = await ev(`(function(){
      var go = document.getElementById('game-over-screen');
      var btn = document.getElementById('recent-opponent-add');
      return { gameOverActive: go ? go.classList.contains('active') : null,
               goDisplay: go ? getComputedStyle(go).display : null,
               resultText: (document.getElementById('game-result') || {}).textContent,
               btnPresent: !!btn }; })()`);
    return (o && o.gameOverActive === true && o.btnPresent === true) ? o : null;
  }, 30000, '结算屏出现且长出 #recent-opponent-add').catch(() => null);
  if (!settled) {
    const dump = await ev(`(function(){
      return { href: location.href,
               screens: [].slice.call(document.querySelectorAll('.screen.active')).map(function(s){ return s.id; }),
               result: (document.getElementById('game-result')||{}).textContent,
               btn: !!document.getElementById('recent-opponent-add'),
               recent: (typeof recentOpponentState !== 'undefined') ? recentOpponentState : 'no-scope',
               oppName: (window.gameState||{}).opponentName }; })()`).catch(() => null);
    console.log('   [排查转储] ' + JSON.stringify(dump));
  }
  check(!!settled, '★ BG11 结算屏 #game-over-screen 真的 active，且 #recent-opponent-add 出现',
    settled || '见上面的排查转储');

  // 页面自己注册的那个 handler 有没有处理这条事件。
  // ⚠️ 这条是**区分**"事件真的到了"与"按钮只是靠 gameState.opponentName 兜底画出来的"的关键：
  //    game_over 那一段有一句 `recentOpponentState.name || gameState.opponentName`，
  //    只看 DOM 存在与否分不清两者（那会是一条假绿的弱断言）。
  const rosState = await ev(`(function(){
    if (typeof recentOpponentState === 'undefined') return { scope: 'unreachable' };
    return { scope: 'ok', name: recentOpponentState.name, relation: recentOpponentState.relation,
             userId: recentOpponentState.userId }; })()`).catch((e) => ({ scope: 'error', why: String(e.message) }));
  check(rosState.scope === 'ok' && String(rosState.name) === aName
        && String(rosState.userId) === aUid && rosState.relation === 'none',
    '★ BG12 页面自己注册的 handler 处理了 recent_opponent（recentOpponentState = 事件 payload）',
    { got: rosState, expect: { name: aName, userId: aUid, relation: 'none' } });

  // socket 线路证据：到达浏览器的报文里真的出现过 recent_opponent
  const wireSeen = wsFrames.some((t) => t.indexOf('recent_opponent') >= 0) || pollBodies.length > 0;
  check(wireSeen, '★ BG13 socket **线路上**真的收到了 recent_opponent 报文（CDP 抓 WS 帧 / polling 响应体）',
    { wsFrames: wsFrames.filter((t) => t.indexOf('recent_opponent') >= 0).slice(0, 2),
      wsFrameCount: wsFrames.length, pollBodies: pollBodies.length });

  // 按钮的挂载位置与内容
  const btn = await ev(`(function(){
    var b = document.getElementById('recent-opponent-add');
    if (!b) return { present: false };
    var host = b.parentElement;
    return { present: true, tag: b.tagName, text: b.textContent, disabled: b.disabled,
             username: b.dataset.username, relation: b.dataset.relation, title: b.title,
             hostClass: host ? host.className : null,
             hostId: host ? host.id : null,
             isFirstChild: host ? host.firstElementChild === b : null,
             insideGameOver: !!(host && host.closest('#game-over-screen')) }; })()`);
  check(btn.present === true && btn.hostClass === 'game-over-buttons' && btn.insideGameOver === true,
    '★ BG14 #recent-opponent-add 挂在 #game-over-screen 的 .game-over-buttons 里（结算屏的按钮行）', btn);
  check(btn.isFirstChild === true, '★ BG14b 它插在按钮行**最前面**（不许顶掉「再来一局/返回主菜单」）',
    { isFirstChild: btn.isFirstChild, host: btn.hostClass });
  check(btn.text === '加好友' && btn.disabled === false && String(btn.username) === aName
        && btn.relation === 'none' && String(btn.title).indexOf(aName) >= 0,
    '★ BG15 按钮内容正确：文案「加好友」、可点、dataset.username == 对手名、relation == none、title 点明是谁',
    btn);

  const probe = await ev(PROBE('#recent-opponent-add'));
  check(probe && probe.present === true && probe.inViewport === true && probe.occluded === 0,
    '★ BG16 按钮**真的可见且没被别的东西压住**（3x3 elementFromPoint 采样；区分"没渲染"与"渲染了被挡住"）',
    probe);

  // ---------- 点它：CDP 抓 POST /api/friends/request ----------
  //
  // ⚠️ 按钮不在时**不要**直接抛（抛出去会让后面那一整段本地注入的断言全没跑，
  //    报告里只剩一个"工具自身异常"，看不出还坏在哪）—— 这里显式 SKIP 掉这一段。
  const clickable = btn.present === true && btn.insideGameOver === true;
  if (!clickable) {
    skip('★ BG17~BG25 点击与本地注入那一段', '按钮没渲染出来（BG14/BG15 已经红了），点不了就没有点击可言');
  } else {
    const before = friendsRequestPosts.length;
    await clickJs('document.getElementById("recent-opponent-add")');
    const caught = await waitFor(() => (friendsRequestPosts.length > before ? friendsRequestPosts[before] : null),
      15000, 'POST /api/friends/request 真的发出去').catch(() => null);
    let caughtBody = null;
    try { caughtBody = caught ? JSON.parse(caught.body || '{}') : null; } catch (e) { caughtBody = { raw: caught && caught.body }; }
    check(!!caught && caught.method === 'POST' && /\/api\/friends\/request(\?|$)/.test(caught.url),
      '★ BG17 点「加好友」真的发出了 POST /api/friends/request（CDP Fetch 域抓的，不是"看着像"）',
      caught ? { method: caught.method, url: caught.url, body: caught.body } : friendsRequestPosts.slice(-2));
    check(!!caughtBody && String(caughtBody.username) === aName,
      '★ BG18 请求体里的 username **就是 recent_opponent 事件里那个人**（不是页面上别的名字）',
      { body: caughtBody, expect: aName });
    check(friendsRequestPosts.length - before === 1,
      '★ BG19 点一次只发一次（没有重复提交 / 连环重试）',
      { posts: friendsRequestPosts.length - before });

    const afterResp = await waitFor(async () => {
      const o = await ev(`(function(){
        var b = document.getElementById('recent-opponent-add');
        if (!b) return null;
        return { text: b.textContent, disabled: b.disabled }; })()`);
      return (o && o.text === '已申请') ? o : null;
    }, 15000, '回执回来后按钮变「已申请」').catch(() => null);
    check(!!afterResp && afterResp.disabled === true,
      '★ BG20 回执 status=sent → 按钮变「已申请」且禁用（前端真的处理了响应，不是只发不管）',
      afterResp);

    // ---------- 后端那一侧也钉一下：申请真的落库 + A 真的收到 friend_request ----------
    const aCookie = await nodeAuth(APP, aName);
    const aList = aCookie ? await friendsOf(aCookie) : { status: 0, body: null };
    const incomingNames = (aList.body && Array.isArray(aList.body.incoming))
      ? aList.body.incoming.map((u) => String(u.username)) : [];
    check(aList.status === 200 && incomingNames.indexOf(B) >= 0,
      '★ BG21 申请真的落库：用 A 的 cookie 直读 GET /api/friends，incoming 里有 B（B 是发起方）',
      { http: aList.status, incoming: incomingNames, expect: B });

    const rseq2 = peerCmd('report');
    const rrep = await waitPeerCmd(rseq2, 20000).catch(() => null);
    const fr = (rrep && rrep.report && rrep.report.friend_request) || [];
    check(fr.length >= 1 && String(fr[fr.length - 1].from_username) === B,
      '★ BG22 A 的 socket 真的收到了 friend_request（from_username === B）—— 这次点击在后端真的产生了推送',
      fr.slice(-1));
  }

  // ---------- 前端 handler 的 relation 分支：**本地注入**（不重写处理逻辑） ----------
  //
  // ⚠️ 为什么这么注入：socket.io 客户端 4.x 的 Socket 上有 onevent(packet)，
  //    packet.data = [事件名, payload]，它就是真实报文到达时走的那条分发路径
  //    （见 static/socket.io.js 的 onevent/emitEvent）。唯一的差别是"报文从本地来"
  //    而不是从服务端来 —— 上面的真链路（BG1~BG22）管"服务端真的推得出来"，
  //    这一段只管"前端收到之后真的做得对"，两半缺一不可（friends_check.mjs T3f 同一道理）。
  const inject = (name, relation) => ev(`(function(){
    var s = window.gameState && window.gameState.socket;
    if (!s || typeof s.onevent !== 'function') return 'no-onevent';
    s.onevent({ data: ['recent_opponent', { user_id: 'injected-uid', username: ${JSON.stringify(name)},
      avatar: '', relation: ${JSON.stringify(relation)} }] });
    return 'ok'; })()`);

  const inj1 = await inject(aName, 'pending_in');
  const afterInj1 = await waitFor(async () => {
    const o = await ev(`(function(){ var b = document.getElementById('recent-opponent-add');
      return b ? { text: b.textContent, disabled: b.disabled, relation: b.dataset.relation } : null; })()`);
    return (o && o.text === '已申请') ? o : null;
  }, 8000, '注入 relation=pending_in 后按钮变「已申请」').catch(() => null);
  check(inj1 === 'ok' && !!afterInj1 && afterInj1.disabled === true && afterInj1.relation === 'pending_in',
    '★ BG23 [本地注入] relation=pending_in → 按钮「已申请」且禁用（走页面真实分发路径）',
    { injected: inj1, after: afterInj1 });

  const inj2 = await inject(aName, 'friends');
  const afterInj2 = await waitFor(async () => {
    const o = await ev(`(function(){ var b = document.getElementById('recent-opponent-add');
      return b ? { text: b.textContent, disabled: b.disabled } : null; })()`);
    return (o && o.text === '已是好友') ? o : null;
  }, 8000, '注入 relation=friends 后按钮变「已是好友」').catch(() => null);
  check(inj2 === 'ok' && !!afterInj2 && afterInj2.disabled === true,
    '★ BG24 [本地注入] relation=friends → 按钮「已是好友」且禁用（不会让已经是好友的人再申请）',
    { injected: inj2, after: afterInj2 });

  const otherName = '不是账号的名字' + SUFFIX;
  const inj3 = await inject(otherName, 'none');
  const afterInj3 = await waitFor(async () => {
    const o = await ev(`(function(){ var b = document.getElementById('recent-opponent-add');
      return b ? { text: b.textContent, disabled: b.disabled, username: b.dataset.username, title: b.title } : null; })()`);
    return (o && o.username === otherName) ? o : null;
  }, 8000, '注入另一个名字后 dataset.username 跟着换').catch(() => null);
  check(inj3 === 'ok' && !!afterInj3 && afterInj3.text === '加好友' && afterInj3.disabled === false
        && String(afterInj3.title).indexOf(otherName) >= 0,
    '★ BG25 [本地注入] 渲染用的是**事件里的名字**（换个人名，dataset.username/title 一起换、按钮恢复可点）',
    { injected: inj3, after: afterInj3 });

  // 拉黑：服务端会下发 blocked_by_me / blocked_me（见 PB1/PB2），前端认不认？
  // 前端 FRIEND_RELATIONS 里没有这两个取值 → 会被降级成 'none' → 渲染出一个**可点的
  // 「加好友」**。正确行为：要么禁用、要么文案明确说不能加（断言"不许是能点的加好友"）。
  // ⚠️ 编号用 PB3（边角组）：它与 PG1/PB1/PB2 同属"不在票面两条主线上"的发现，
  //    这样结尾那句"失败项全在边角组"才说得准。
  const inj4 = await inject(aName, 'blocked_me');
  await sleep(600);
  const afterInj4 = await ev(`(function(){ var b = document.getElementById('recent-opponent-add');
    return b ? { text: b.textContent, disabled: b.disabled, relation: b.dataset.relation } : null; })()`);
  check(inj4 === 'ok' && !!afterInj4 && !(afterInj4.text === '加好友' && afterInj4.disabled === false),
    '★ PB3 [本地注入] 被拉黑的对手不该渲染成**可点的「加好友」**（服务端会下发 blocked_me）',
    { injected: inj4, after: afterInj4 });

  if (SHOT) {
    try {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
      console.log('   截图已存 ' + SHOT);
    } catch (e) { console.log('   截图失败: ' + e.message); }
  }

  check(jsProblems.length === 0, '★ BG26 全程零 JS 异常 / 零 console.error（含页面内与 python 侧）',
    jsProblems.slice(0, 8));
}

// ---------- 收尾 ----------
async function cleanup() {
  try { peerCmd('quit'); } catch (e) { /* 没有就够 */ }
  await sleep(400);
  try { if (peer && !peer.killed) peer.kill(); } catch (e) { /* 已退 */ }
  try { ws && ws.close(); } catch (e) { /* 已关 */ }
  try { browser && !browser.killed && browser.kill(); } catch (e) { /* 已退 */ }
  // ⚠️ `browser.kill()` 只干掉主进程：msedge 会派生一堆子进程，只按 pid 杀**杀不干净**，
  //    下一次跑就会有一批残留占着 9362 + 锁着 profile（症状是新浏览器"静默起不来"，
  //    连上的是上一轮的旧实例 → 查不出所以然的假红）。所以这里再按 profile 路径扫一遍。
  try {
    spawnSync('powershell', ['-NoProfile', '-Command',
      'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
      'Where-Object { $_.CommandLine -like \'*recent_opponent_profile*\' } | ' +
      'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'],
      { stdio: 'ignore', timeout: 20000 });
  } catch (e) { /* 没有残留就够 */ }
}

// ---------- 主流程 ----------
async function main() {
  console.log('== 最近对手一键加好友 · 端到端回归检查 ==');
  console.log('   APP = ' + APP);
  console.log('   DB  = ' + DB + '（仅显示；真正的库由服务端的 BATTLESHIP_DB_PATH 决定）');
  console.log('   B   = ' + B + '（浏览器）   A = recentchk_a' + SUFFIX + '（python 侧陪练）');
  console.log('   game.js = ' + JSON.stringify(fileFingerprint(path.join(ROOT, 'static', 'game.js')))
    + '  ⚠️ 该文件可能正被另一个智能体修改');
  console.log('');

  // 服务端在不在
  let up = false, status = 0;
  try {
    const r = await fetch(APP);
    status = r.status;
    up = r.ok;
  } catch (e) { status = 0; }
  if (!up) {
    console.log('服务端没起来（HTTP ' + status + '）：' + APP);
    console.log('起法：PORT=5104 CORS_ORIGINS=... BATTLESHIP_DB_PATH=.tmp/recent_opp.db python server.py');
    process.exit(2);
  }
  console.log('   服务端在线（HTTP ' + status + '）');

  await runServerHalf();

  if (NO_BROWSER) {
    skip('② 前端那半边（全部）', '--no-browser：本次只跑服务端那半边');
  } else {
    await runBrowserHalf();
  }

  const after = fileFingerprint(path.join(ROOT, 'static', 'game.js'));
  console.log('');
  console.log('   game.js 跑完后 = ' + JSON.stringify(after));
}

main().catch((err) => {
  console.error('工具自身异常：' + (err && err.stack || err));
  failures.push('工具自身异常: ' + (err && err.message));
}).then(async () => {
  await cleanup();
  const total = passes.length + failures.length;
  console.log('');
  console.log('==================== 结果 ====================');
  console.log('通过 ' + passes.length + ' / 失败 ' + failures.length + ' / 跳过 ' + skips.length
    + '（断言总数 ' + total + '，另有 ' + infoLines + ' 条 INFO）');
  if (skips.length) {
    console.log('跳过：');
    skips.forEach((s) => console.log('   · ' + s));
  }
  if (failures.length) {
    console.log('失败项：');
    failures.forEach((f) => console.log('   · ' + f));
    const onlyEdge = failures.every((f) => /★ (PG|PB)\d/.test(f));
    if (onlyEdge) {
      console.log('   ↑ 全部失败项都落在 **PG*/PB*（边角用例：游客 / 拉黑）**，'
        + '票面两条主线（服务端那半边 PH*、前端那半边 BG*）都是绿的。');
    }
    process.exit(1);
  }
  console.log('✓ 最近对手一键加好友：两半都通过' + (skips.length ? '（含跳过项，见上）' : ''));
  process.exit(0);
});
