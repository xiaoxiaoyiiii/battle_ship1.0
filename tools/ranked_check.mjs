#!/usr/bin/env node
/**
 * 段位 / 排位 UI 回归检查（无头 Edge + CDP，全部断言真实 DOM）
 *
 * 依据：`docs/RANKED_2026_09_17.md`（设计稿 + 冻结契约 §6 DOM / §5 接口）。
 *
 * 覆盖五块界面：
 *   1. `#leaderboard-tabs` 页签 + `#ranked-table` 段位榜（真实 `/api/ranked_leaderboard`），
 *      含「高段位的行**真的**更重」——用 getComputedStyle 对比两行，**不只断言 class 存在**
 *      （本项目吃过"加了 class 被通用规则盖掉"的假绿）；
 *   2. 个人信息查看面的 `#profile-view-rank`（文案必须等于接口下发的 `rank_info.label`）；
 *   3. 编辑面第 5 个开关 `#profile-show-rank` + 保存载荷**真的**是 10 个字段，
 *      关掉之后回读为 0（防"开关是假控件"）；
 *   4. 排位入口 `#ranked-match`：游客被拒后**能恢复按钮**（不卡在"正在寻找"）；
 *   5. `#rank-gain-panel`：**三局真链路** —— 两个真账号真的配成排位、真的摆船、真的猜拳、
 *      真的投降结算，等 `rank_changed` 真的到达（不是手动调渲染函数）。
 *
 * ⚠️ 为什么最后一条要花这么大力气：本项目出过一次「工具手动调渲染函数全绿、真机链路全坏」
 *    （`showRenwangChoice`）。段位面板是"结算回调里开面板"的同一形状，所以必须真打。
 *    ⚠️ 另外**不能拿 `test_win_game` 当"打完一局"**：那个调试桩只设 `room.state/winner`
 *    再 emit `game_over`，**根本不调 `_finalize_match`** —— 一分不加、一条 `rank_changed` 都不发。
 *    真正会走结算的是「炮击击沉 / 投降 / 掉线判胜」，这里用**投降**。
 *
 * 三局各自的用途（对 `rank_changed` 的四种 delta 场景里覆盖三种）：
 *   · 局 1：A 90 分 → 赢 +20 → 跨小段位（进度条走满重置 + 升段提示）
 *   · 局 2：A 0 分 → 输 → **clamped 且 delta = 0** → 面板必须写「已到 0 分下限，本局未扣分」
 *           （不许出现「±0」，也不许把进度条播成掉分）
 *   · 局 3：A 5 分 → 输 → clamped 且 delta = -5 → 显示实际扣的 5 分 + 「已触及 0 分下限」
 *
 * 用法：
 *   node tools/ranked_check.mjs --url http://127.0.0.1:5023/ [--db <隔离库路径>] [--shot out.png]
 *
 * ⚠️ 只在**隔离库**的本地服务上用：会注册 `rankcheck_*` 一次性账号并真的写段位分。
 *    默认库路径 `<repo>/.tmp/rank_ui.db`（要与服务端 `BATTLESHIP_DB_PATH` 指向同一份）。
 * ⚠️ 服务端必须带 `CORS_ORIGINS` 放行本端口，否则 socket.io 连不上（本项目实测：
 *    连不上时页面**不报错**，只是所有排队/匹配静默失效 —— 所以下面 A6 专门钉一条"socket 真连上了"）。
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5023/').replace(/\/?$/, '/');
const SHOT = argOf('--shot', '');
const PORT = 9350;
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const ROOT = path.resolve(HERE, '..');
const DB = argOf('--db', path.join(ROOT, '.tmp', 'rank_ui.db'));
const TMP = path.join(ROOT, '.tmp');
const BROWSER = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
const PROFILE_DIR = path.join(TMP, 'ranked_check_profile');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过段位检查'); process.exit(0); }
fs.mkdirSync(TMP, { recursive: true });

// ---------- 预清理：残留的无头 Edge 会占着调试端口 + 锁住 profile ----------
// （不清理的话新浏览器**静默起不来**，工具连上的是上一轮的旧实例 → 查不出所以然的假红。）
try {
  spawnSync('powershell', ['-NoProfile', '-Command',
    'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | ' +
    'Where-Object { $_.CommandLine -like \'*ranked_check_profile*\' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'],
    { stdio: 'ignore', timeout: 20000 });
} catch (e) { /* 没有残留就够了 */ }

const SUFFIX = String(Date.now()).slice(-6);
const PW = 'check123456';
const A = 'rankcheck_a' + SUFFIX;          // 浏览器里的那个玩家
const B = 'rankcheck_b' + SUFFIX;          // python 侧的对手
// 段位榜要有"从低到高"的分布，才验得出"高段位更重"
const BOARD = [
  ['rb_low' + SUFFIX, 30],        // 二级水手Ⅰ 30分
  ['rb_mid' + SUFFIX, 790],       // 水手长Ⅱ 90分（作者给的例子）
  ['rb_high' + SUFFIX, 1850],     // 轮机长Ⅰ 50分
  ['rb_cap2' + SUFFIX, 2150],     // 船长Ⅰ 2150分
  ['rb_cap' + SUFFIX, 2400],      // 船长Ⅲ 2400分（顶端那一档）
];

let browser = null, ws = null, seq = 0, opponent = null;
const pending = new Map();
const problems = [];
const jsProblems = [];
const passes = [];

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
  if (r.exceptionDetails) throw new Error('页面异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeout) {
    try { last = await fn(); if (last) return last; } catch (e) { last = 'err:' + e.message; }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label + '  (最后=' + JSON.stringify(last) + ')');
}

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (ok) passes.push(label); else problems.push(label);
}

// ---------- 隔离库的读写（唯一"造数据"途径：没有 HTTP 接口能改段位分） ----------
const DB_HELPER = path.join(TMP, 'ranked_check_db.py');
fs.writeFileSync(DB_HELPER, String.raw`
# -*- coding: utf-8 -*-
"""ranked_check.mjs 用的隔离库助手：建号 / 设分 / 设开关。只动 BATTLESHIP_DB_PATH 指的那个库。"""
import json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
from werkzeug.security import generate_password_hash

cmd = sys.argv[1]
db.init_db()

def ensure(username):
    user = db.get_user(username=username)
    if not user:
        uid = db.create_user(username, generate_password_hash('check123456'))
        user = db.get_user(uid=uid)
    return user

def set_points(uid, points):
    db.set_rank_points(uid, int(points))
    raw = sqlite3.connect(str(db.db.db_path))
    try:
        raw.execute('UPDATE user_rank SET ranked_wins=?, ranked_losses=? WHERE user_id=?',
                    (max(1, int(points) // 40), max(0, int(points) // 120), uid))
        raw.commit()
    finally:
        raw.close()

if cmd == 'seed':
    n = 0
    for pair in [p for p in sys.argv[2].split(',') if p]:
        username, points = pair.split(':')
        u = ensure(username)
        if u:
            set_points(u['id'], points)
            n += 1
    print(json.dumps({'ok': True, 'count': n}))
elif cmd == 'set':
    u = ensure(sys.argv[2])
    if not u:
        print(json.dumps({'ok': False})); sys.exit(1)
    set_points(u['id'], sys.argv[3])
    print(json.dumps({'ok': True, 'points': int(sys.argv[3])}))
elif cmd == 'show_rank':
    u = ensure(sys.argv[2])
    db.set_show_rank(u['id'], int(sys.argv[3]))
    print(json.dumps({'ok': True, 'show_rank': int(sys.argv[3])}))
else:
    print(json.dumps({'ok': False, 'error': 'unknown cmd'})); sys.exit(1)
`, 'utf8');

function dbHelper(args) {
  // ⚠️ spawnSync + 参数数组，**不要** execSync 拼字符串：Windows 走 cmd.exe，
  //    参数里的引号/方括号会被 shell 吃掉（JSON 参数实测就是这么被拆坏的）。
  const r = spawnSync('python', [DB_HELPER].concat(args), {
    cwd: ROOT, encoding: 'utf8', timeout: 90000,
    env: { ...process.env, BATTLESHIP_DB_PATH: DB, PYTHONIOENCODING: 'utf-8' },
  });
  const out = String(r.stdout || '');
  const line = out.trim().split(/\r?\n/).filter((l) => l.trim().startsWith('{')).pop();
  if (!line) throw new Error('隔离库助手失败: ' + String(r.stderr || r.error || '').slice(-400));
  return JSON.parse(line);
}

// ---------- python 侧的对手：真登录 + 真 socket + 真摆船 + 真猜拳（+ 可选真投降） ----------
const OPPONENT_PY = path.join(TMP, 'ranked_check_opponent.py');
fs.writeFileSync(OPPONENT_PY, String.raw`
# -*- coding: utf-8 -*-
"""排位对局的第二个真人客户端：登录 → socket 入排位队列 → 摆船 → 猜拳 →（可选）投降。

用法：python ranked_check_opponent.py <base_url> <username> <password> <mode> <action> <rps_choice>
  action: 'surrender_after_attack' | 'none'
stdout：每行一个 JSON，供 node 侧读取进度。
"""
import json, sys, time
import requests
import socketio

base, username, password, mode, action, rps_choice = sys.argv[1:7]

s = requests.Session()
r = s.post(base + 'login', data={'username': username, 'password': password}, allow_redirects=True)
if '登录成功' not in r.text:
    s.post(base + 'register', data={'username': username, 'password': password}, allow_redirects=True)
cookie = '; '.join('%s=%s' % (k, v) for k, v in s.cookies.get_dict().items())

state = {'room_id': None, 'player_id': None, 'state': None}
flags = {'placed': False, 'rps': False, 'surrendered': False}

def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)

sio = socketio.Client(reconnection=False)

@sio.on('game_state')
def on_state(data):
    d = data or {}
    if d.get('room_id'):
        state['room_id'] = d['room_id']
    if d.get('player_id'):
        state['player_id'] = d['player_id']
    st = d.get('state')
    state['state'] = st
    out({'event': 'game_state', 'room_id': state['room_id'], 'player_id': state['player_id'],
         'state': st, 'ranked': d.get('ranked'), 'mode': d.get('mode')})
    if not (state['room_id'] and state['player_id']):
        return
    if st == 'placing_ships' and not flags['placed']:
        flags['placed'] = True
        # ⚠️ 形状必须与前端 gameState.ships 一致：positions **和** hits 都要有
        #    （服务端是 PlayerShip(**x)，少一个 hits 直接 TypeError →
        #     handler 抛异常、**不回 ack**、船也没放上，而 rps_choice 不看 state，
        #     于是对局还会"顺利"进 attacking —— 假绿得非常彻底）。
        resp = sio.call('place_ships', {'room_id': state['room_id'], 'player_id': state['player_id'],
                                        'ships': [{'positions': [{'x': i, 'y': 2}], 'hits': []} for i in range(6)]},
                        timeout=8)
        out({'event': 'place_ack', 'resp': resp})
    elif st == 'rock_paper_scissors' and not flags['rps']:
        flags['rps'] = True
        # ⚠️ 两边必须出**不同的**手，否则永远平局（作者/父代理实测提醒）
        resp = sio.call('rps_choice', {'room_id': state['room_id'], 'player_id': state['player_id'],
                                       'choice': rps_choice}, timeout=8)
        out({'event': 'rps_ack', 'resp': resp})
    elif st == 'attacking' and action == 'surrender_after_attack' and not flags['surrendered']:
        flags['surrendered'] = True
        time.sleep(2.0)      # 等双方都真的进了 attacking（"真开打"之后再投降）
        sio.emit('surrender', {'room_id': state['room_id'], 'player_id': state['player_id']})
        out({'event': 'surrendered'})

@sio.on('error')
def on_error(data):
    out({'event': 'error', 'data': data})

sio.connect(base.rstrip('/'), headers={'Cookie': cookie}, wait_timeout=20)
sio.emit('find_match', {'player_name': username, 'mode': mode})
out({'event': 'queued', 'mode': mode})

t0 = time.time()
while time.time() - t0 < 45:
    time.sleep(0.3)
    if flags['surrendered'] and time.time() - t0 > 10:
        break
    if state['state'] == 'attacking' and action == 'none' and time.time() - t0 > 12:
        break
if not flags['placed']:
    out({'event': 'no_match'})
time.sleep(4)
sio.disconnect()
`, 'utf8');

function startOpponent(action, rpsChoice) {
  const p = spawn('python', [OPPONENT_PY, APP, B, PW, 'ranked', action, rpsChoice], {
    cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const events = [];
  let buf = '';
  p.stdout.on('data', (d) => {
    buf += d.toString('utf8');
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line.startsWith('{')) continue;
      try { events.push(JSON.parse(line)); } catch (e) { /* 忽略非 JSON 行 */ }
    }
  });
  p.stderr.on('data', (d) => {
    const s = d.toString('utf8');
    if (/Traceback|Error/.test(s)) jsProblems.push('python 对手: ' + s.replace(/\s+/g, ' ').slice(0, 220));
  });
  return { proc: p, events };
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

const RECT = 'function R(e){var b=e.getBoundingClientRect();return {x:Math.round(b.left),y:Math.round(b.top),w:Math.round(b.width),h:Math.round(b.height)};}';

/** 「这块东西有没有被别的元素盖住」——矩形内多点采样 elementFromPoint。 */
const OCCLUSION_PROBE = (sel) => `(function(){
  ${RECT}
  var el = document.querySelector(${JSON.stringify(sel)});
  if (!el) return { present: false };
  var cs = getComputedStyle(el);
  if (cs.display === 'none' || cs.visibility === 'hidden') return { present: false, hidden: true };
  var r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return { present: false, zero: true };
  var samples = 0, occluded = 0, worst = null;
  for (var i = 1; i <= 3; i++) for (var j = 1; j <= 3; j++) {
    var x = r.left + r.width * i / 4, y = r.top + r.height * j / 4;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
    samples++;
    var top = document.elementFromPoint(x, y);
    var hit = top === el || (top && el.contains(top)) || (top && top.contains(el));
    if (!hit) { occluded++; if (!worst) worst = { tag: top ? top.tagName : null, id: top ? top.id : null,
      cls: top ? String(top.className).slice(0, 60) : null, x: Math.round(x), y: Math.round(y) }; }
  }
  return { present: true, samples: samples, occluded: occluded, worst: worst, rect: R(el) };
})()`;

// 页面侧"代替玩家操作"的脚手架：只做**玩家本来就会做**的事（摆船 / 出拳），
// 走的都是真 socket、真服务端校验。段位面板本身仍然只由服务端事件驱动。
//
// ⚠️ `hold`（默认 true）：先只挂监听、不真摆船。因为**两边一摆完船，对局就立刻进猜拳**，
//    匹配成功那个 5 秒等待界面会当场消失 —— 而"等待界面上的两枚段位 chip"要在这之前断言。
//    所以流程是：挂监听（hold）→ 断言 chip → `hold=false` + `step()` 放行。
const AUTOPLAY = `(function () {
  window.__auto = window.__auto || { placed: false, rps: false, room: null, pid: null, last: null, states: [], ev: [], hold: true };
  var s = gameState.socket;
  if (!s) return false;
  var auto = window.__auto;
  auto.step = function () {
    if (auto.hold) return 'hold';
    var d = auto.last || {};
    if (!(auto.room && auto.pid)) return 'no-room';
    if ((d.state === 'placing_ships' || !d.state) && !auto.placed) {
      auto.placed = true;
      s.emit('place_ships', { room_id: auto.room, player_id: auto.pid,
        ships: [0, 1, 2, 3, 4, 5].map(function (i) { return { positions: [{ x: i, y: 4 }], hits: [] }; }) },
        function (resp) { auto.placeAck = resp; });
      return 'placed';
    }
    if (d.state === 'rock_paper_scissors' && !auto.rps) {
      auto.rps = true;
      s.emit('rps_choice', { room_id: auto.room, player_id: auto.pid, choice: 'rock' },
        function (resp) { auto.rpsAck = resp; });
      return 'rps';
    }
    return 'idle';
  };
  if (!window.__autoOn) {
    window.__autoOn = true;
    // 记录服务端发过来的所有事件名：面板没出现时，"rank_changed 到底来没来"是第一个要回答的问题
    s.onAny(function (name) { auto.ev.push(name); });
    s.on('game_state', function (d) {
      d = d || {};
      auto.last = d;
      if (d.room_id) auto.room = d.room_id;
      if (d.player_id) auto.pid = d.player_id;
      if (d.state) auto.states.push(d.state + '@' + (d.ranked ? 'ranked' : 'casual'));
      try { auto.step(); } catch (e) { auto.err = String(e && e.message); }
    });
  }
  return true;
})()`;

const PANEL_TEXT = `(function(){
  var p = document.getElementById('rank-gain-panel');
  if (!p || p.classList.contains('hidden')) return null;
  var fill = document.getElementById('rank-bar-fill');
  var bar = document.getElementById('rank-bar');
  return { visible: true, delta: (document.getElementById('rank-delta') || {}).textContent || '',
    prefix: (document.getElementById('rank-delta-prefix') || {}).textContent || '',
    before: (document.getElementById('rank-label-before') || {}).textContent || '',
    after: (document.getElementById('rank-label-after') || {}).textContent || '',
    beforeIcon: document.getElementById('rank-icon-before').querySelector('.rank-icon') ? document.getElementById('rank-icon-before').querySelector('.rank-icon').getAttribute('data-tier') : null,
    afterIcon: document.getElementById('rank-icon-after').querySelector('.rank-icon') ? document.getElementById('rank-icon-after').querySelector('.rank-icon').getAttribute('data-tier') : null,
    promote: (document.getElementById('rank-promote') || {}).textContent || '',
    promoteHidden: document.getElementById('rank-promote').classList.contains('hidden'),
    clampNote: (document.getElementById('rank-clamp-note') || {}).textContent || '',
    clampHidden: document.getElementById('rank-clamp-note').classList.contains('hidden'),
    note: (document.getElementById('rank-admiral-note') || {}).textContent || '',
    noteHidden: document.getElementById('rank-admiral-note').classList.contains('hidden'),
    points: (document.getElementById('rank-points-text') || {}).textContent || '',
    isLoss: p.classList.contains('is-loss'),
    pct: (fill && bar) ? Math.round(fill.getBoundingClientRect().width / bar.getBoundingClientRect().width * 100) : null }; })()`;

/** 打开查看面并等段位块渲染（真入口；首屏可能还在"加载中…"，所以带一次重试）。 */
async function openProfileAndWaitRank(usernameExpr) {
  for (let attempt = 0; attempt < 2; attempt++) {
    await ev(`(function(){ window.showUserProfile(${usernameExpr}); return true; })()`);
    try {
      await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view-rank")'),
        attempt ? 20000 : 12000, '段位块渲染');
      return true;
    } catch (e) { /* 再试一次：接口 + 徽章目录可能刚好慢一拍 */ }
  }
  return false;
}

try {
  // ---------- A. 准备 ----------
  if (!fs.existsSync(DB)) {
    console.error('找不到隔离库 ' + DB + '：请用 BATTLESHIP_DB_PATH=' + DB + ' 起服务端');
    process.exit(2);
  }
  const seed = dbHelper(['seed', BOARD.map(([u, p]) => u + ':' + p).join(',')]);
  check(!!(seed && seed.ok), 'A1 隔离库里造出 5 个不同段位的账号（段位榜要有高低分布）', seed);
  // 对手（python 那一侧）也造出段位：匹配等待界面的「对手段位 chip」要有内容可断言
  const seedOpp = dbHelper(['seed', B + ':790']);
  check(!!(seedOpp && seedOpp.ok), 'A1b 给 python 侧的对手也造出段位（水手长Ⅱ 90分）', seedOpp);

  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE_DIR, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank'], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      // ⚠️ 无头 Edge 自带 edge://sync-confirmation-dialog 且稳定排在 /json/list 第一位：
      //    按 URL 过滤，但**必须留 type==='page' 兜底**（初始页是 about:blank）。
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^(https?|about|file):/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 浏览器还在启动 */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });

  // 拦截 fetch：记录 /api/profile/card 的请求体（验保存载荷字段数）
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `(function(){
    window.__cardPosts = [];
    var orig = window.fetch;
    window.fetch = function (url, opts) {
      opts = opts || {};
      try {
        if (String(url).indexOf('/api/profile/card') === 0) window.__cardPosts.push(JSON.parse(opts.body || '{}'));
      } catch (e) { window.__cardPosts.push({ __parse_error: String(opts.body) }); }
      return orig.apply(this, arguments);
    };
    return 'hooked';
  })()` });

  // ---------- 0. 从游客态开始（持久 profile 里带着上一轮的 cookie） ----------
  await goto(APP + 'logout', APP);
  check(!(await ev('window.__USERNAME || null')), 'A2 起点是游客态（先登出，避免旧 cookie 污染）');

  // ---------- E. 排位入口：游客被拒后要能恢复按钮 ----------
  const guestEnv = await ev(`(function(){
    var btn = document.getElementById('ranked-match');
    var st = document.getElementById('ranked-status');
    var cancel = document.getElementById('cancel-ranked');
    return { btn: !!btn, status: !!st, cancel: !!cancel,
      btnVisible: btn ? btn.offsetHeight > 0 : null }; })()`);
  check(guestEnv.btn && guestEnv.status && guestEnv.cancel,
    '★ E1 #ranked-match / #ranked-status / #cancel-ranked 三个契约 id 都在页面上且按钮可见', guestEnv);
  // 点下去的**同一帧**读状态：排队态是乐观渲染的，网络往返之后就被复位了 ——
  // 只在之后轮询会读到"已经复位"，那是抓不到"压根没反应"的（两种失败长得一样）。
  const clickNow = await ev(`(function(){
    var b = document.getElementById('ranked-match');
    b.click();
    var s = document.getElementById('ranked-status');
    var c = document.getElementById('cancel-ranked');
    return { btnHidden: b.classList.contains('hidden'),
      statusShown: !s.classList.contains('hidden'), cancelShown: !c.classList.contains('hidden') }; })()`);
  check(clickNow.btnHidden === true && clickNow.statusShown === true && clickNow.cancelShown === true,
    'E2 点 #ranked-match 立刻隐藏按钮、显示「正在寻找排位对手…」+ 取消按钮', clickNow);
  const restored = await waitFor(async () => {
    const o = await ev(`(function(){
      var b = document.getElementById('ranked-match');
      var s = document.getElementById('ranked-status');
      var c = document.getElementById('cancel-ranked');
      return { btnHidden: b.classList.contains('hidden'),
        statusHidden: s.classList.contains('hidden'),
        cancelHidden: c.classList.contains('hidden') }; })()`);
    return (o && o.btnHidden === false && o.statusHidden === true && o.cancelHidden === true) ? o : null;
  }, 12000, '游客被拒后按钮恢复').catch(() => null);
  check(!!restored, '★ E3 服务端拒绝（未登录 → emit error）之后按钮**恢复了**，没有卡在"正在寻找"', restored);

  // ---------- 登录 ----------
  const auth = await ev(`(async function () {
    var post = function (url) {
      return fetch(url, { method: 'POST', redirect: 'follow',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username: ${JSON.stringify(A)}, password: ${JSON.stringify(PW)} }).toString() });
    };
    var r1 = await post('/login');
    if ((await r1.text()).indexOf('登录成功') >= 0) return 'login-ok';
    var r2 = await post('/register');
    var t2 = await r2.text();
    if (t2.indexOf('注册成功') >= 0) return 'register-ok';
    return 'auth-failed: ' + t2.replace(/\\s+/g, ' ').slice(0, 120);
  })()`);
  check(typeof auth === 'string' && /ok$/.test(auth), 'A3 真实登录一次性账号（后面的接口断言都要真身份）', auth);
  dbHelper(['set', A, '90']);          // 注册会新建行；这里先置成"局 1 的起点"
  await goto(APP);
  const me = await ev('window.__USERNAME');
  check(me === A, 'A4 页面认得当前登录用户', me);

  // ★ socket 真的连上了吗：连不上时页面**不报错**，只是排队/匹配全部静默失效
  //   （本机踩过一次：服务端没放行 CORS_ORIGINS → 后面的断言全成了假红）。
  await ev('(function(){ if (typeof ensureSocket === "function") ensureSocket(); return true; })()');
  const sock = await waitFor(async () => {
    const o = await ev('(function(){ return { has: !!gameState.socket, connected: gameState.socket ? gameState.socket.connected : false, id: gameState.socket ? gameState.socket.id : null }; })()');
    return (o && o.connected) ? o : null;
  }, 15000, '页面 socket 连上服务端').catch(() => null);
  check(!!sock, '★ A5 页面的 socket 真的连上了服务端（连不上时后面全是静默假红：CORS_ORIGINS 要放行本端口）', sock);

  // ---------- 1. 段位榜 ----------
  // 先补一条「休闲那条没被改坏」：排位是加在同一个按钮组里的，休闲匹配是既有功能。
  const casual = await ev(`(function(){
    document.getElementById('find-match').click();
    return true; })()`);
  // 休闲那条**不是**乐观渲染：要等服务端 `match_queued` 才显示「正在寻找匹配…」
  // （排位那条我写成乐观的，所以两边的时序不一样——这里按休闲的真实时序等）
  const casualQueued = await waitFor(async () => {
    const o = await ev(`(function(){
      var st = document.getElementById('match-status');
      var rs = document.getElementById('ranked-status');
      var rb = document.getElementById('ranked-match');
      return { casualShown: !st.classList.contains('hidden'), rankedHidden: rs.classList.contains('hidden'),
        rankedBtnVisible: !rb.classList.contains('hidden') }; })()`);
    return (o && o.casualShown) ? o : null;
  }, 12000, '休闲匹配进入排队').catch(() => null);
  check(!!casualQueued && casualQueued.rankedHidden === true && casualQueued.rankedBtnVisible === true,
    '★ B0 休闲匹配还是老样子（#match-status 亮起），排位那套不会被点亮', casualQueued);
  const casualCancel = await waitFor(async () => {
    await ev('(function(){ var b = document.getElementById("cancel-match"); if (b) b.click(); return true; })()');
    await sleep(400);
    const o = await ev(`(function(){ return { hidden: document.getElementById('match-status').classList.contains('hidden'),
      rankedBtn: !document.getElementById('ranked-match').classList.contains('hidden') }; })()`);
    return (o && o.hidden === true && o.rankedBtn === true) ? o : null;
  }, 12000, '取消休闲匹配').catch(() => null);
  check(!!casualCancel, 'B0b 取消休闲匹配后状态收起、排位按钮回到原位（两套 UI 不打架）', casualCancel);

  const tabs = await ev(`(function(){
    var bar = document.getElementById('leaderboard-tabs');
    if (!bar) return { present: false };
    var btns = [].slice.call(bar.querySelectorAll('.lb-tab'));
    return { present: true, labels: btns.map(function (b) { return b.textContent.trim(); }),
      tabs: btns.map(function (b) { return b.dataset.tab; }) }; })()`);
  check(tabs.present && tabs.tabs.indexOf('record') >= 0 && tabs.tabs.indexOf('ranked') >= 0,
    '★ B1 #leaderboard-tabs 存在，有「战绩榜」「段位榜」两个页签', tabs);

  await ev('(function(){ window.showLeaderboard(); return true; })()');
  await waitFor(async () => await ev('document.getElementById("leaderboard-screen").classList.contains("active")'), 10000, '排行榜页');
  const before = await ev(`(function(){
    var t = document.getElementById('ranked-table');
    var rec = document.getElementById('leaderboard-container');
    return { rankedExists: !!t, rankedVisible: t ? t.offsetHeight > 0 : null,
      recordVisible: rec ? rec.offsetHeight > 0 : null,
      rows: t ? t.querySelectorAll('tbody tr').length : -1 }; })()`);
  check(before.rankedExists === true && before.rankedVisible === false,
    'B2 未点页签时段位榜不可见（数据不是页面加载时就拉来的）', before);
  check(before.recordVisible === true, 'B3 默认显示的还是原来的战绩榜', before);

  await ev('(function(){ document.getElementById("lb-tab-ranked").click(); return true; })()');
  const rows = await waitFor(async () => {
    const o = await ev(`(function(){
      var t = document.getElementById('ranked-table');
      if (!t) return null;
      var trs = [].slice.call(t.querySelectorAll('tbody tr.ranked-row'));
      if (!trs.length) return null;       // ⚠️ 先渲染「加载中…」再取数 → 必须等真行出现
      return { n: trs.length,
        points: trs.map(function (tr) { return Number(tr.querySelector('.ranked-points').textContent.trim()); }),
        tiers: trs.map(function (tr) { return tr.dataset.tier; }),
        labels: trs.map(function (tr) { return tr.querySelector('.ranked-label').textContent.trim(); }),
        positions: trs.map(function (tr) { return Number(tr.querySelector('.ranked-pos').textContent.trim()); }),
        recordHidden: document.getElementById('leaderboard-container').classList.contains('hidden') }; })()`);
    return o && o.n > 0 ? o : null;
  }, 15000, '段位榜出现真实行');
  check(rows.n >= 5, '★ B4 点「段位榜」后 #ranked-table 出现且有真实行（不是空表 / 不是"加载中"）', { n: rows.n });
  check(rows.recordHidden === true, 'B5 切到段位榜后，战绩榜那张表被收起（两块不会同时摊着）', rows.recordHidden);
  check(rows.points.every((p, i) => i === 0 || rows.points[i - 1] >= p), '★ B6 段位榜按排位分倒序', rows.points);
  check(rows.positions.every((p, i) => p === i + 1), 'B7 名次列是 1..N 连续（用的是服务端的 position）', rows.positions);

  const apiBoard = await ev(`fetch('/api/ranked_leaderboard?limit=100&offset=0', { headers: { 'Accept': 'application/json' } })
    .then(function (r) { return r.json(); })
    .then(function (d) { return { labels: (d.leaderboard || []).map(function (x) { return x.label; }) }; })`);
  check(apiBoard && JSON.stringify(apiBoard.labels.slice(0, rows.n)) === JSON.stringify(rows.labels),
    '★ B8 段位列显示的就是接口下发的 `label`（前端没有自己拼段位文案）',
    { dom: rows.labels.slice(0, 3), api: apiBoard && apiBoard.labels.slice(0, 3) });

  // 高段位是不是**真的**更重：直接对比两行的 computed style（不只断言 class 存在）
  const weight = await ev(`(function(){
    ${RECT}
    var t = document.getElementById('ranked-table');
    var rows = [].slice.call(t.querySelectorAll('tbody tr.ranked-row'));
    var top = rows.filter(function (r) { return r.classList.contains('top-tier'); })[0];
    var low = rows.filter(function (r) { return !r.classList.contains('high-tier') && !r.classList.contains('top-tier'); })[0];
    if (!top || !low) return { skip: 'top=' + !!top + ' low=' + !!low };
    var probe = function (tr) {
      var lab = tr.querySelector('.ranked-label');
      var td = tr.querySelector('td');
      var icon = tr.querySelector('.rank-icon');
      var cl = getComputedStyle(lab), ct = getComputedStyle(td);
      return { label: lab.textContent.trim(), color: cl.color, weight: cl.fontWeight,
        shadow: cl.textShadow, tdBg: ct.backgroundImage.slice(0, 80), tdShadow: ct.boxShadow.slice(0, 90),
        icon: icon ? Math.round(icon.getBoundingClientRect().width) : 0 }; };
    return { top: probe(top), low: probe(low) }; })()`);
  const w = weight && weight.top && weight.low ? weight : null;
  check(!!w, 'B9 段位榜里同时存在「顶端段位行」与「低段位行」（才比得出轻重）', weight);
  if (w) {
    check(w.top.color !== w.low.color, '★ B10 高段位的段位文字**颜色真的不同**（computed color 对比）',
      { top: w.top.color, low: w.low.color });
    check(Number(w.top.weight) > Number(w.low.weight), '★ B11 高段位的段位文字**字重真的更重**（computed fontWeight 对比）',
      { top: w.top.weight, low: w.low.weight });
    check(w.top.shadow !== w.low.shadow && /rgb/.test(w.top.shadow), '★ B12 顶端那一档**真的带发光**（computed textShadow 非 none）',
      { top: w.top.shadow, low: w.low.shadow });
    check(w.top.tdBg !== w.low.tdBg && /gradient/.test(w.top.tdBg), '★ B13 高段位的行底色**真的是另一套渐变**（不是被通用规则盖掉的空类）',
      { top: w.top.tdBg, low: w.low.tdBg });
    check(w.top.tdShadow !== w.low.tdShadow && w.top.tdShadow !== 'none', '★ B14 高段位的行**真的带左侧色条 / 发光**（computed boxShadow 对比）',
      { top: w.top.tdShadow, low: w.low.tdShadow });
    check(w.top.icon > w.low.icon, '★ B15 高段位的图标**真的更大**（不只是换了个颜色）',
      { top: w.top.icon, low: w.low.icon });
  }

  await ev('(function(){ document.getElementById("lb-tab-record").click(); return true; })()');
  const back = await waitFor(async () => {
    const o = await ev(`(function(){
      var rec = document.getElementById('leaderboard-container');
      var rk = document.getElementById('leaderboard-ranked-container');
      return { recVisible: rec ? rec.offsetHeight > 0 : null,
        recTable: !!document.querySelector('#leaderboard-table tbody'),
        rankedHidden: rk ? rk.classList.contains('hidden') : null }; })()`);
    return (o && o.recVisible === true && o.rankedHidden === true && o.recTable) ? o : null;
  }, 12000, '切回战绩榜').catch(() => null);
  check(!!back, 'B16 两个页签可以来回切，切回去战绩榜照样在（没有互相踩坏）', back);

  // ---------- 2. 个人信息查看面的段位块 ----------
  await ev('(function(){ var s = document.getElementById("leaderboard-screen"); if (s) s.classList.remove("active"); return true; })()');
  const mine = await ev(`fetch('/api/profile', { headers: { 'Accept': 'application/json' } })
    .then(function (r) { return r.json(); }).then(function (d) { return d.profile; })`);
  check(!!(mine && mine.rank_info && mine.rank_info.label),
    '★ C1 /api/profile 自己视角恒带 rank_info（含 label）', mine && mine.rank_info);

  // 真入口：页头「个人信息」→ 查看面
  await ev('(function(){ document.getElementById("show-profile").click(); return true; })()');
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'), 20000, '查看面渲染');
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view-rank")'),
    20000, '查看面的段位块渲染出来');
  const viewRank = await ev(`(function(){
    var c = document.getElementById('opponent-stats-content');
    var b = c.querySelector('#profile-view-rank');
    if (!b) return { present: false };
    var fill = b.querySelector('.pf-rank-bar > i');
    var bar = b.querySelector('.pf-rank-bar');
    return { present: true,
      text: b.textContent.replace(/\\s+/g, ' ').trim(),
      label: (b.querySelector('.pf-rank-label') || {}).textContent || '',
      hasIcon: !!b.querySelector('.rank-icon'),
      iconTier: b.querySelector('.rank-icon') ? b.querySelector('.rank-icon').getAttribute('data-tier') : null,
      next: (b.querySelector('.pf-rank-next') || {}).textContent || '',
      fillPct: fill && bar ? Math.round(fill.getBoundingClientRect().width / bar.getBoundingClientRect().width * 100) : null }; })()`);
  check(viewRank.present === true && viewRank.hasIcon === true, '★ C2 查看面渲染出 #profile-view-rank（带段位图标）', viewRank);
  check(viewRank.label === mine.rank_info.label,
    '★ C3 段位文案**就是**接口下发的 label（前端没有自己拼）', { dom: viewRank.label, api: mine.rank_info.label });
  check(viewRank.iconTier === mine.rank_info.tier_id, 'C4 图标用的是服务端的 tier_id', { dom: viewRank.iconTier, api: mine.rank_info.tier_id });
  const expPct = Math.round((mine.rank_info.progress / (mine.rank_info.sub_points || 100)) * 100);
  check(viewRank.fillPct !== null && Math.abs(viewRank.fillPct - expPct) <= 3,
    'C5 进度条宽度 = 服务端的 progress / sub_points（前端不重算）',
    { dom: viewRank.fillPct, expect: expPct, progress: mine.rank_info.progress });
  check(String(viewRank.next).indexOf(String(mine.rank_info.to_next)) >= 0,
    'C6 「还差 N 分」用的是服务端的 to_next', { dom: viewRank.next, api: mine.rank_info.to_next });

  // ---------- 3. 别人关掉「段位公开」→ 整块不显示（不许画假段位） ----------
  const otherName = 'rb_mid' + SUFFIX;
  dbHelper(['show_rank', otherName, '0']);
  const otherSeen = await ev(`fetch('/user_stats?username=' + encodeURIComponent(${JSON.stringify(otherName)}))
    .then(function (r) { return r.json(); })`);
  check(otherSeen && otherSeen.stats && otherSeen.stats.rank_info === null,
    '★ C7 别人关掉「段位公开」时接口给的是 null（不是空 dict）',
    otherSeen && otherSeen.stats && { show_rank: otherSeen.stats.show_rank, rank_info: otherSeen.stats.rank_info });
  await ev(`(function(){ window.showUserProfile(${JSON.stringify(otherName)}); return true; })()`);
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view")'), 20000, '别人名片渲染');
  await sleep(500);
  const otherCard = await ev(`(function(){
    var c = document.getElementById('opponent-stats-content');
    var b = c.querySelector('#profile-view-rank');
    return { block: !!b, hasFake: /二级水手Ⅰ 0分/.test(c.textContent) }; })()`);
  check(otherCard.block === false, '★ C8 别人未公开段位 → 段位块**整个不显示**（不是画成 0 分）', otherCard);
  check(otherCard.hasFake === false, '★ C9 页面上没有「二级水手Ⅰ 0分」这种假段位', otherCard.hasFake);
  dbHelper(['show_rank', otherName, '1']);

  // ---------- 3b. 船长（`to_next === null`）：不画进度条、也不写「还差 N 分」 ----------
  const capName = 'rb_cap' + SUFFIX;
  const capSeen = await ev(`fetch('/user_stats?username=' + encodeURIComponent(${JSON.stringify(capName)}))
    .then(function (r) { return r.json(); })`);
  const capInfo = (capSeen && capSeen.stats && capSeen.stats.rank_info && typeof capSeen.stats.rank_info === 'object')
    ? capSeen.stats.rank_info : null;
  check(!!(capInfo && capInfo.to_next === null && /船长/.test(capInfo.label)),
    '★ C10 船长段位的 `to_next` 是 null（后面没有小级了），label 带累计分 + 全服排名', capInfo && capInfo.label);
  await ev(`(function(){ window.showUserProfile(${JSON.stringify(capName)}); return true; })()`);
  await waitFor(async () => await ev('!!document.querySelector("#opponent-stats-content #profile-view-rank")'),
    20000, '船长的段位块渲染');
  const capBlock = await ev(`(function(){
    var b = document.querySelector('#opponent-stats-content #profile-view-rank');
    return { label: (b.querySelector('.pf-rank-label') || {}).textContent || '',
      hasBar: !!b.querySelector('.pf-rank-bar'), next: (b.querySelector('.pf-rank-next') || {}).textContent || '',
      icon: b.querySelector('.rank-icon') ? b.querySelector('.rank-icon').getAttribute('data-tier') : null }; })()`);
  check(capBlock.label === capInfo.label && capBlock.icon === 'captain',
    '★ C11 船长的段位块文案 = 服务端 label，图标是 captain', capBlock);
  check(capBlock.hasBar === false && capBlock.next === '',
    '★ C12 `to_next === null` 时**不画进度条、也不写"还差 N 分"**', capBlock);

  // ---------- 4. 编辑面第 5 个开关 + 保存载荷 10 字段 ----------
  await ev('(function(){ var m = document.getElementById("opponent-stats-modal"); if (m) m.classList.add("hidden"); return true; })()');
  await ev('(async function(){ await window.openMyProfileEditor(); return true; })()');
  await waitFor(async () => await ev('(function(){ var m = document.getElementById("profile-modal"); return m ? !m.classList.contains("hidden") : false; })()'),
    15000, '编辑面打开');
  const toggle = await waitFor(async () => {
    const o = await ev(`(function(){
      var box = document.getElementById('profile-show-rank');
      if (!box) return null;
      var labels = [].slice.call(document.querySelectorAll('#profile-edit .pf-pane[data-pane="card"] .pf-toggles label'))
        .map(function (l) { return (l.querySelector('input') || {}).id; });
      return { exists: true, checked: box.checked, kind: box.type, order: labels }; })()`);
    return o && o.exists ? o : null;
  }, 12000, '#profile-show-rank 出现').catch(() => null);
  check(!!toggle, '★ D1 #profile-show-rank 存在（编辑面第 5 个展示开关）', toggle);
  check(!!toggle && toggle.checked === true, 'D2 默认是「公开」（checked）', toggle && toggle.checked);
  if (toggle) {
    check(toggle.order.indexOf('profile-show-rank') === 4 && toggle.order.length === 5,
      'D3 #profile-show-rank 是**第 5 个**展示开关（前 4 个原样保留）', toggle.order);
  }

  await ev('(function(){ document.getElementById("profile-show-rank").checked = false; return true; })()');
  await ev('(function(){ window.__cardPosts = []; document.getElementById("profile-card-save").click(); return true; })()');
  await waitFor(async () => await ev('window.__cardPosts.length > 0'), 15000, '保存请求发出');
  const post = await ev('window.__cardPosts[0]');
  const need = ['title_id', 'tags', 'status_text', 'frame_id', 'card_bg_id',
    'show_stats', 'show_fav_cards', 'show_history', 'show_guestbook', 'show_rank'];
  check(!!post && need.every((k) => k in post) && Object.keys(post).length === 10,
    '★ D4 保存载荷带齐全部 10 个字段（缺一个服务端就整次 400）',
    { got: post ? Object.keys(post) : null, missing: post ? need.filter((k) => !(k in post)) : null });
  check(!!post && Number(post.show_rank) === 0, '★ D5 关掉开关后请求体里 show_rank 真的是 0（不是假控件）', post && post.show_rank);
  await sleep(800);
  const afterSave = await ev(`fetch('/api/profile', { headers: { 'Accept': 'application/json' } })
    .then(function (r) { return r.json(); }).then(function (d) { return d.profile.show_rank; })`);
  check(Number(afterSave) === 0, '★ D6 关掉之后回读 /api/profile 是 0（真的落库了）', afterSave);
  await ev('(function(){ document.getElementById("profile-show-rank").checked = true; return true; })()');
  await ev('(function(){ window.__cardPosts = []; document.getElementById("profile-card-save").click(); return true; })()');
  const backOn = await waitFor(async () => {
    const v = await ev(`fetch('/api/profile', { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); }).then(function (d) { return d.profile.show_rank; })`);
    return Number(v) === 1 ? v : null;
  }, 12000, 'show_rank 恢复成 1').catch(() => null);
  check(Number(backOn) === 1, 'D7 再打开后回读是 1（开关双向都能落库）', backOn);

  // ================= 5. 真链路：三局排位（摆船 → 猜拳 → 投降 → 真结算） =================
  //
  // 每一局都：重置 A 的分数 → 重新加载页面（面板回到隐藏，也顺带证明它只在事件到达时出现）
  //          → 装页面侧脚手架（摆船/出拳）→ 两个真账号同时排位 → 等 rank_changed。
  const matches = [
    { name: '局 1：赢 +20（跨小段位）', points: 90, surrender: 'opponent', rps: 'paper',
      expect: { delta: '+20 分', before: '二级水手Ⅰ 90分', after: '二级水手Ⅱ 10分', promote: true, clamped0: false, pct: 10 } },
    { name: '局 2：0 分封底（delta = 0）', points: 0, surrender: 'browser', rps: 'paper',
      expect: { delta: '已到 0 分下限，本局未扣分', before: '二级水手Ⅰ 0分', after: '二级水手Ⅰ 0分', promote: false, clamped0: true, pct: 0 } },
    { name: '局 3：部分扣分（clamped, delta = -5）', points: 5, surrender: 'browser', rps: 'paper',
      expect: { delta: '-5 分', before: '二级水手Ⅰ 5分', after: '二级水手Ⅰ 0分', promote: false, clamped0: false, pct: 0, clampNote: true } },
  ];

  for (let m = 0; m < matches.length; m++) {
    const cfg = matches[m];
    dbHelper(['set', A, String(cfg.points)]);
    await goto(APP);
    await waitFor(async () => await ev('!!window.__USERNAME'), 12000, '页面就绪');
    check(await ev('(function(){ var p = document.getElementById("rank-gain-panel"); return !!p && p.classList.contains("hidden"); })()'),
      `★ F${m + 1}.1 ${cfg.name} —— 事件没来之前 #rank-gain-panel 是隐藏的（休闲局永远收不到 → 永远不显示）`);

    opponent = startOpponent(cfg.surrender === 'opponent' ? 'surrender_after_attack' : 'none', cfg.rps);
    await ev('(function(){ if (typeof ensureSocket === "function") ensureSocket(); return true; })()');
    await waitFor(async () => await ev('(function(){ return !!(gameState.socket && gameState.socket.connected); })()'), 15000, 'socket 就绪');
    await ev(AUTOPLAY);                       // 只挂监听（hold=true）：先别摆船，否则等待界面立刻消失
    await ev('(function(){ document.getElementById("ranked-match").click(); return true; })()');

    // 匹配成功界面上的两枚段位 chip（只在局 1 断言：后面几局的段位相同，重复没意义）
    let chips = null;
    if (m === 0) {
      chips = await waitFor(async () => {
        const o = await ev(`(function(){
          var s = document.getElementById('match-success-screen');
          var box = document.getElementById('opponent-chips');
          return { success: s ? s.classList.contains('active') : false,
            self: (document.getElementById('match-self-rank') || {}).textContent || '',
            opp: box ? box.textContent : '',
            oppRankChip: box ? !!box.querySelector('.match-chip.rank') : null }; })()`);
        return (o && o.success && o.self && o.opp) ? o : null;
      }, 45000, '排位匹配成功 + 两边段位 chip 出现').catch(() => null);
      check(!!chips, '★ F1.2 两个真账号真配成一局排位（匹配成功界面出现）', chips);
      check(!!chips && chips.self.indexOf('你 ') >= 0 && /二级水手Ⅰ/.test(chips.self),
        '★ F1.3 等待界面显示**自己的段位**（页面加载时缓存的那份，不是这 5 秒里现拉的）', chips && chips.self);
      check(!!chips && chips.oppRankChip === true && /水手长Ⅱ 90分/.test(chips.opp),
        '★ F1.4 等待界面出现**对手的段位 chip**（文案用服务端 label）', chips && chips.opp);
      // 段位 chip 里有一枚 24px 的 SVG，很容易比同排的"称号/等级"chip 高一截。
      // 要求：同一排里**一样高**（flex 的 align-items: stretch 生效），且不把容器撑出横向滚动。
      const chipGeo = await ev(`(function(){
        var box = document.getElementById('opponent-chips');
        var rank = box.querySelector('.match-chip.rank');
        var others = [].slice.call(box.querySelectorAll('.match-chip')).filter(function (c) { return c !== rank; });
        var sib = others[0] || null;
        var r = rank ? rank.getBoundingClientRect() : null;
        var s = sib ? sib.getBoundingClientRect() : null;
        return { rankH: r ? Math.round(r.height) : null, sibH: s ? Math.round(s.height) : null,
          sameRow: (r && s) ? Math.abs(r.top - s.top) < 2 : null, sibText: sib ? sib.textContent : null,
          overflow: box.scrollWidth - box.clientWidth, chips: box.querySelectorAll('.match-chip').length }; })()`);
      check(chipGeo && chipGeo.rankH !== null && chipGeo.sibH !== null && Math.abs(chipGeo.rankH - chipGeo.sibH) <= 1,
        '★ F1.5 段位 chip 与同一排的称号/等级 chip **一样高**（没有把别的 chip 挤变形）', chipGeo);
      check(chipGeo && chipGeo.overflow <= 1, 'F1.6 段位 chip 没有把 #opponent-chips 撑出横向溢出', chipGeo);
    } else {
      // 后面两局只要"配上了"就够（chip 已经在局 1 验过）
      await waitFor(async () => await ev('(function(){ var s = document.getElementById("match-success-screen"); return !!(s && s.classList.contains("active")); })()'),
        45000, '匹配成功界面').catch(() => null);
    }
    // 放行：真摆船（走真 socket，服务端真校验）
    await ev('(function(){ window.__auto.hold = false; return window.__auto.step(); })()');

    // 轮到自己投降的那两局：进了 attacking 之后由浏览器这一侧真投降
    if (cfg.surrender === 'browser') {
      await waitFor(async () => {
        const st = await ev('(function(){ return { state: window.__auto.states[window.__auto.states.length - 1] || "", room: window.__auto.room, pid: window.__auto.pid }; })()');
        return (st && /attacking/.test(st.state) && st.room && st.pid) ? st : null;
      }, 45000, '进入 attacking').catch(() => null);
      await sleep(1200);      // 让对手也真的进了 attacking
      await ev('(function(){ gameState.socket.emit("surrender", { room_id: window.__auto.room, player_id: window.__auto.pid }); return true; })()');
    }

    const panel = await waitFor(async () => {
      const o = await ev(PANEL_TEXT);
      return o && o.delta ? o : null;
    }, 45000, `rank_changed 到达 → 段位面板出现（${cfg.name}）`).catch(async () => {
      // 失败时把"卡在哪一步"直接打出来（python 对手走到哪、页面收到了哪些事件）——
      // 本工具的假红基本都出在这一段，没有这两份证据只能瞎猜。
      const auto = await ev('(function(){ return { auto: window.__auto, hidden: (document.getElementById("rank-gain-panel")||{}).className }; })()').catch(() => null);
      const opp = (opponent && opponent.events) ? opponent.events : [];
      check(false, `F${m + 1}.2 诊断（${cfg.name}）`, {
        page: auto,
        opponent: opp.slice(-6),
        oppStates: opp.filter((e) => e.event === 'game_state').map((e) => e.state),
      });
      return null;
    });
    check(!!panel, `★★ F${m + 1}.2 ${cfg.name}：真打完一局排位后 \`rank_changed\` 真的到达、#rank-gain-panel 真的出现（不是手动调函数）`, panel);
    if (!panel) continue;

    check(panel.delta === cfg.expect.delta,
      `★ F${m + 1}.3 ${cfg.name}：分差文案 = ${cfg.expect.delta}`, { dom: panel.delta, prefix: panel.prefix });
    check(panel.before === cfg.expect.before && panel.after === cfg.expect.after,
      `★ F${m + 1}.4 ${cfg.name}：before.label → after.label 用的是服务端下发的文案`,
      { before: panel.before, after: panel.after });
    if (cfg.expect.clamped0) {
      check(!/^[-+]?0\s*分$/.test(panel.delta) && panel.delta.indexOf('未扣分') >= 0,
        '★★ 0 分封底时**不显示 ±0**，而是写「已到 0 分下限，本局未扣分」', panel.delta);
      check(panel.isLoss === false, '★ 0 分封底（一分没扣）**不套掉分配色**，进度条也不会播成掉分', panel.isLoss);
      check(panel.clampHidden === true, '封底且没扣分时不显示额外的"已触及下限"补充行（主文案已经说清楚了）', panel.clampNote);
    }
    if (cfg.expect.clampNote) {
      check(panel.clampHidden === false && /0 分下限/.test(panel.clampNote) && /5/.test(panel.clampNote),
        '★ clamped 且真的扣了分时：显示实际扣的分数 + 一句「已触及 0 分下限」', panel.clampNote);
    }
    if (cfg.expect.promote) {
      check(panel.promoteHidden === false && /升段/.test(panel.promote) && /二级水手Ⅰ/.test(panel.promote)
        && /二级水手Ⅱ/.test(panel.promote),
        '★ 升段提示出现，且判据是 `promoted`（不是自己比 label 字符串）', panel.promote);
      check(panel.noteHidden === true && panel.note === '',
        '★ 低段位**不显示**大舰长那行小字（服务端给的是「需要先达到船长段位」，没有信息量）', panel.note);
    }
    check(panel.beforeIcon === 'sailor2' && panel.afterIcon === 'sailor2',
      `F${m + 1}.5 两枚段位图标用的是服务端的 tier_id`, { before: panel.beforeIcon, after: panel.afterIcon });
    check(/累计排位分/.test(panel.points), `F${m + 1}.6 累计排位分显示的是服务端的 points`, panel.points);

    const barEnd = await waitFor(async () => {
      const o = await ev('(function(){ var f = document.getElementById("rank-bar-fill"); var b = document.getElementById("rank-bar");' +
        ' return { pct: (f && b) ? Math.round(f.getBoundingClientRect().width / b.getBoundingClientRect().width * 100) : null }; })()');
      return (o && Math.abs(o.pct - cfg.expect.pct) <= 2) ? o : null;
    }, 12000, '进度条滚动结束').catch(async () => await ev('(function(){ var f = document.getElementById("rank-bar-fill"); var b = document.getElementById("rank-bar");' +
      ' return { pct: (f && b) ? Math.round(f.getBoundingClientRect().width / b.getBoundingClientRect().width * 100) : null }; })()'));
    check(barEnd && Math.abs(barEnd.pct - cfg.expect.pct) <= 2,
      `★ F${m + 1}.7 ${cfg.name}：进度条最终停在 ${cfg.expect.pct}%` +
      (cfg.expect.pct === 10 ? '（走满 → 清空重来 → 继续涨，跨小段位的滚动真的发生了）' : '（掉分方向也对）'),
      barEnd);

    try { opponent.proc.kill(); } catch (e) { /* ignore */ }
    opponent = null;
    await sleep(600);
  }

  // ---------- 5b. 大舰长 / 船长那两行小字：**注入 payload 直接调真实入口** ----------
  //
  // ⚠️ 这一段**不是真链路**，明确标注：本服 `ADMIRAL_MIN_CAPTAINS=50` 意味着现在
  //    **没有任何账号能升到大舰长**（作者有意为之），所以"大舰长晋升金光 + 船长段
  //    那句还差什么"这两条只能注入 payload 验。走的是**真实入口**
  //    `showRankGainPanel()`（socket 处理器调的就是它），不是工具专用的旁路函数。
  const admiralBefore = { tier_id: 'captain', tier_name: '船长', tier_index: 7, sub: 'Ⅲ', progress: 0,
    points: 2400, to_next: null, sub_points: 100, is_admiral: false, label: '船长Ⅲ 2400分 #3', server_rank: 3, captain_pool_rank: 2 };
  const admiralAfter = { tier_id: 'admiral', tier_name: '大舰长', tier_index: 8, sub: '', progress: 0,
    points: 2420, to_next: null, sub_points: 100, is_admiral: true, label: '大舰长 #2', server_rank: 2, captain_pool_rank: 2 };
  const injected = await ev(`(function(){
    if (typeof window.showRankGainPanel !== 'function') return { skip: 'no-entry' };
    window.showRankGainPanel({ role: 'winner', delta: 20, clamped: false,
      points_before: 2400, points_after: 2420, before: ${JSON.stringify(admiralBefore)}, after: ${JSON.stringify(admiralAfter)},
      promoted: true, demoted: false, tier_up: true, tier_down: false,
      admiral_promoted: true, admiral_demoted: false, admiral_reason: '' });
    var p = document.getElementById('rank-gain-panel');
    return { admiralClass: p.classList.contains('is-admiral'),
      promote: (document.getElementById('rank-promote') || {}).textContent || '',
      beforeLabel: (document.getElementById('rank-label-before') || {}).textContent || '',
      afterLabel: (document.getElementById('rank-label-after') || {}).textContent || '',
      icon: document.getElementById('rank-icon-after').querySelector('.rank-icon') ? document.getElementById('rank-icon-after').querySelector('.rank-icon').getAttribute('data-tier') : null,
      points: (document.getElementById('rank-points-text') || {}).textContent || '',
      noteHidden: document.getElementById('rank-admiral-note').classList.contains('hidden') }; })()`);
  check(!!injected && injected.admiralClass === true && /大舰长/.test(injected.promote),
    '★（注入式）admiral_promoted 时整块套金光 + 晋升文案', injected);
  check(!!injected && injected.afterLabel === '大舰长 #2' && injected.icon === 'admiral' && /2420/.test(injected.points),
    '（注入式）大舰长用服务端的 label / tier_id / 累计分渲染', injected);
  const capNote = await ev(`(function(){
    window.showRankGainPanel({ role: 'loser', delta: -15, clamped: false,
      points_before: 2300, points_after: 2285,
      before: { tier_id: 'captain', tier_name: '船长', tier_index: 7, sub: 'Ⅲ', progress: 200, points: 2300, to_next: null, sub_points: 100, is_admiral: false, label: '船长Ⅲ 2300分 #60', server_rank: 60, captain_pool_rank: 60 },
      after: { tier_id: 'captain', tier_name: '船长', tier_index: 7, sub: 'Ⅲ', progress: 185, points: 2285, to_next: null, sub_points: 100, is_admiral: false, label: '船长Ⅲ 2285分 #60', server_rank: 60, captain_pool_rank: 60 },
      promoted: false, demoted: false, tier_up: false, tier_down: false,
      admiral_promoted: false, admiral_demoted: false,
      admiral_reason: '船长段位内排名需进入前 50（当前第 63）' });
    var n = document.getElementById('rank-admiral-note');
    return { hidden: n.classList.contains('hidden'), text: n.textContent }; })()`);
  check(!!capNote && capNote.hidden === false && /前 50/.test(capNote.text),
    '★（注入式）船长段位 + admiral_reason → 显示那行「还差什么」小字', capNote);
  const lowNote = await ev(`(function(){
    window.showRankGainPanel({ role: 'loser', delta: -15, clamped: false, points_before: 30, points_after: 15,
      before: { tier_id: 'sailor2', tier_name: '二级水手', tier_index: 0, sub: 'Ⅰ', progress: 30, points: 30, to_next: 70, sub_points: 100, is_admiral: false, label: '二级水手Ⅰ 30分', server_rank: 20, captain_pool_rank: null },
      after: { tier_id: 'sailor2', tier_name: '二级水手', tier_index: 0, sub: 'Ⅰ', progress: 15, points: 15, to_next: 85, sub_points: 100, is_admiral: false, label: '二级水手Ⅰ 15分', server_rank: 20, captain_pool_rank: null },
      promoted: false, demoted: false, tier_up: false, tier_down: false,
      admiral_promoted: false, admiral_demoted: false, admiral_reason: '需要先达到船长段位' });
    var n = document.getElementById('rank-admiral-note');
    return { hidden: n.classList.contains('hidden'), text: n.textContent }; })()`);
  check(!!lowNote && lowNote.hidden === true,
    '★（注入式）低段位**不显示**那行小字（服务端给的是「需要先达到船长段位」，没有信息量）', lowNote);
  await ev('(function(){ var p = document.getElementById("rank-gain-panel"); if (p) p.classList.add("hidden"); return true; })()');

  // ---------- 6. 视口不压元素 ----------
  for (const [w, h] of [[320, 568], [390, 844], [1600, 1000]]) {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await sleep(350);

    const okRank = await openProfileAndWaitRank('window.__USERNAME');
    check(okRank, `${w}×${h}：查看面的段位块能渲染出来（分段位下进度条 + label）`);
    if (okRank) {
      const rankProbe = await ev(OCCLUSION_PROBE('#opponent-stats-content #profile-view-rank'));
      check(rankProbe.present && rankProbe.occluded === 0 && rankProbe.samples >= 3,
        `${w}×${h}：查看面的段位块没有被任何元素压住`, rankProbe);
      const modalOverflow = await ev(`(function(){
        var c = document.querySelector('#opponent-stats-modal .modal-content');
        return { sw: c ? c.scrollWidth : 0, cw: c ? c.clientWidth : 0 }; })()`);
      check(modalOverflow.sw <= modalOverflow.cw + 4, `${w}×${h}：段位块没有把个人信息弹窗撑出横向滚动`, modalOverflow);
    }
    await ev('(function(){ var m = document.getElementById("opponent-stats-modal"); if (m) m.classList.add("hidden"); return true; })()');

    await ev('(function(){ window.showLeaderboard(); return true; })()');
    await waitFor(async () => await ev('document.getElementById("leaderboard-screen").classList.contains("active")'), 12000, '排行榜页');
    await ev('(function(){ document.getElementById("lb-tab-ranked").click(); return true; })()');
    await waitFor(async () => await ev('!!document.querySelector("#ranked-table tbody tr.ranked-row")'), 20000, '段位榜有行');
    const boardProbe = await ev(OCCLUSION_PROBE('#ranked-table tbody tr.ranked-row .ranked-tier'));
    check(boardProbe.present && boardProbe.occluded === 0 && boardProbe.samples >= 3,
      `${w}×${h}：段位榜的段位列没有被任何元素压住`, boardProbe);
    const boardOverflow = await ev(`(function(){
      var box = document.getElementById('leaderboard-ranked-container');
      return { sw: box ? box.scrollWidth : 0, cw: box ? box.clientWidth : 0,
        pageSw: document.scrollingElement.scrollWidth, iw: innerWidth }; })()`);
    check(boardOverflow.sw <= boardOverflow.cw + 4, `${w}×${h}：段位榜容器没有横向溢出`, boardOverflow);
    check(boardOverflow.pageSw <= boardOverflow.iw + 1, `${w}×${h}：排行榜页整体没有横向溢出`, boardOverflow);
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await sleep(300);

  if (SHOT) {
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(png.data, 'base64'));
    console.log('截图已保存: ' + SHOT);
  }

  check(jsProblems.length === 0, '全程无 JS 异常 / console.error', jsProblems.slice(0, 4));
} catch (err) {
  console.error('检查中断: ' + err.message);
  problems.push('中断: ' + err.message);
} finally {
  try { if (opponent && opponent.proc) opponent.proc.kill(); } catch (e) { /* ignore */ }
  try { if (ws) ws.close(); } catch (e) { /* ignore */ }
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
}

console.log('');
console.log(`通过 ${passes.length} 项 / 失败 ${problems.length} 项`);
console.log(problems.length ? ('✗ 未通过: ' + problems.join(' | ')) : '✓ 全部通过');
process.exit(problems.length ? 1 : 0);
