#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""好友邀战 E2E 的「python 侧 socket 陪练」——被 tools/friend_invite_battle_check.mjs 拉起。

为什么需要它（那段工具头注释里说的"一条干净的 python socket 去 join_room 探这间房"）：
  两个无头浏览器验证的是**页面**上看到了什么；而"这间房在服务端到底坐了几个人"
  只有从**第三条、完全干净的会话**看才作数 —— 否则就是拿被测对象自证。

⚠️ 2026-09-29：这个文件此前**从未入库**（`git log --all -- '*invite_occupy_probe*'` 为空），
   而 `friend_invite_battle_check.mjs` 是硬编码 `spawn('python', [.tmp/invite_occupy_probe.py, …])`。
   在干净检出上那个路径不存在 → python 立刻退出 → 工具永远等不到回话，
   连着 5 条断言一起红（`python 探针命令超时 #1` 及其派生）。这里把它补成
   **受版本控制**的一等文件，并把 PY_HELPER 指过来。

协议（与那个 .mjs 里的 startProbe / probeCmd / waitProbeResult 一一对应）：
    argv:  <APP_URL> <username> <cmd_file>
    stdout: 一行一个 JSON，必须 flush
      {"event":"probe_connected","username":…}      连上并登录成功
      {"event":"fatal","message":…}                  起不来（工具会提前收手，不再白等 45s）
      {"event":"cmd_result","seq":N,…}               某条命令的结果
    cmd_file: 每次被整体覆写为 {"seq":N,"cmd":"…", …参数}

支持的 cmd：
    mkroom                     → {room, ack}           建一间房（供边界用例用）
    joinroom {room}            → {ack}                 直接 join 并返回 ack（成功就留在房里）
    occupy_probe_only {room}   → {seats, ack, game_state_frames}
        语义：试坐这间房，用 ack 反推"**我去之前**房里几个人"：
          ack 成功（我坐上了最后一把椅子）⇒ 之前 1 人
          ack 失败且原因含「已满」        ⇒ 之前 2 人
        这就是工具里 `seats === 1` / `seats === 2` 那条断言的口径。
        失败原因不含「已满」时给 seats=None（宁可判不出，也不猜）。

身份：与 tools/friend_invite_battle_check.mjs 的 PW 常量**必须一致**（同一个字面量两处手抄
是本项目的老病根，所以两边都写了注释指向对方）。
"""

import json
import os
import re
import sys
import time

import requests
import socketio

# ⚠️ 与 tools/friend_invite_battle_check.mjs 的 `const PW = 'invitechk123456';` 保持一致。
PW = 'invitechk123456'

CMD_POLL_SECONDS = 0.1
FULL_MARK = '已满'


def out(obj):
    """一行一个 JSON 并立刻 flush —— 父进程是按行读的，缓冲住就等于超时。"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def login(base, username):
    """确保这个身份可用并返回 Cookie 头。返回 (cookie_header, error)。

    ⚠️ **必须"登录失败就注册再登录"**：`tools/friend_invite_battle_check.mjs` 只注册
       A / B / A3 / B3 四个身份（见它的 `await authCookie(UA)` 那几行），探针的
       `invchk_p/q/r<后缀>` 三个身份**从来没人注册过** —— 那是这个陪练自己的活。
       少了这一步，探针永远停在"登录后身份不是 …（页面 __USERNAME 拿到 ''）"，
       工具那头看到的就是 5 条超时红。
    ⚠️ api.py 对 `/login` 与 `/register` 各有限流（10 次 / 60 秒 / IP）。工具自己撞上时会
       等 65 秒重试；这里照做一轮，免得因为并发登录把整支检查拖成全红。
    """
    def attempt():
        cookie = _post_login(base, username)
        if cookie and _verify_identity(base, cookie, username):
            return cookie
        _post_register(base, username)
        cookie = _post_login(base, username)
        if cookie and _verify_identity(base, cookie, username):
            return cookie
        return None

    cookie = attempt()
    if cookie:
        return cookie, None
    time.sleep(65)                       # 多半撞上 login/register 限流
    cookie = attempt()
    if cookie:
        return cookie, None
    return None, ('身份 %s 登录/注册都失败（多半是 login/register 限流 10 次/60 秒；'
                  '工具那支 authCookie() 同样会在这里等 65 秒重试）' % username)


def _post_login(base, username):
    s = requests.Session()
    try:
        s.post(base + '/login', data={'username': username, 'password': PW},
               allow_redirects=False, timeout=15)
    except Exception:                              # noqa: BLE001
        return None
    return '; '.join('%s=%s' % (k, v) for k, v in s.cookies.items())


def _post_register(base, username):
    try:
        requests.post(base + '/register', data={'username': username, 'password': PW},
                      allow_redirects=False, timeout=15)
    except Exception:                              # noqa: BLE001
        pass


def _verify_identity(base, cookie, username):
    """读首页 HTML 里的 `window.__USERNAME` 确认会话真的建立。
    ⚠️ 不能读 /api/profile 的 `profile.username` —— **那个字段不存在**
       （该接口只返回 {profile:{id,avatar,level_info,…}}）。工具那支 authCookie()
       也是落到同一条 HTML 判据上的。"""
    try:
        r = requests.get(base + '/', headers={'Cookie': cookie}, timeout=15)
        return _page_username(r.text) == username
    except Exception:                              # noqa: BLE001
        return False


def _page_username(html):
    # 与 tools/friend_invite_battle_check.mjs 的 pageUser() 同一个口径
    # （那边是 JS 正则，这边是 Python 的 —— 语义必须一致：转义引号也要吃掉）。
    m = re.search(r'window\.__USERNAME\s*=\s*("(?:[^"\\]|\\.)*")', html or '')
    if not m:
        return ''
    try:
        return str(json.loads(m.group(1)))
    except ValueError:
        return ''


class Probe(object):
    def __init__(self):
        self.sio = socketio.Client(request_timeout=20, reconnection=False)
        self.game_state_frames = 0
        self.acks = {}
        self.sio.on('game_state', self._on_game_state)

    def _on_game_state(self, data):
        # 只数帧数（工具会记进 capture，不作断言）
        self.game_state_frames += 1

    def emit_ack(self, event, payload, timeout=15):
        """emit 一个带 ack 的事件并等 ack。socketio 的 call() 就是干这个的。"""
        return self.sio.call(event, payload, timeout=timeout)

    def do(self, cmd, args):
        if cmd == 'mkroom':
            ack = self.emit_ack('create_room', {'player_name': args.get('name') or 'probe'})
            room = ''
            if isinstance(ack, dict):
                room = str(ack.get('room_id') or '')
            return {'room': room, 'ack': ack}
        if cmd == 'joinroom':
            ack = self.emit_ack('join_room', {'room_id': args.get('room')})
            return {'ack': ack}
        if cmd == 'occupy_probe_only':
            ack = self.emit_ack('join_room', {'room_id': args.get('room')})
            seats = None
            if isinstance(ack, dict):
                if ack.get('status') == 'success':
                    seats = 1          # 我坐上了最后一把椅子 ⇒ 我去之前只有 1 人
                elif FULL_MARK in str(ack.get('message') or ''):
                    seats = 2          # 被「房间已满」挡在门外 ⇒ 我去之前已 2 人
            # 坐进去了就**待在房里**（不摆船、不推进阶段）——"occupy only" 就是这个意思；
            # 工具随后 killProbe 拆掉这条连接。
            return {'seats': seats, 'ack': ack, 'game_state_frames': self.game_state_frames}
        return {'error': '未知命令：%s' % cmd}


def main():
    if len(sys.argv) < 4:
        out({'event': 'fatal', 'message': '用法: invite_occupy_probe.py <APP_URL> <username> <cmd_file>'})
        return 2
    app, username, cmd_file = sys.argv[1], sys.argv[2], sys.argv[3]
    base = app.rstrip('/')

    cookie, err = login(base, username)
    if err:
        out({'event': 'fatal', 'message': err})
        return 3

    probe = Probe()
    try:
        # 只走 polling：本机环境没有 websocket-client，而 eventlet 服务端两种都收。
        probe.sio.connect(base, headers={'Cookie': cookie}, transports=['polling'],
                          wait_timeout=20)
    except Exception as exc:                       # noqa: BLE001
        out({'event': 'fatal', 'message': 'socket 连接失败：%s' % exc})
        return 4

    out({'event': 'probe_connected', 'username': username, 'pid': os.getpid()})

    last_seq = None
    while True:
        try:
            with open(cmd_file, 'r') as fh:
                raw = fh.read()
        except (IOError, OSError):
            raw = ''
        if raw:
            try:
                cmd = json.loads(raw)
            except ValueError:
                cmd = None
            if isinstance(cmd, dict) and cmd.get('seq') != last_seq:
                last_seq = cmd.get('seq')
                args = dict(cmd)
                name = args.pop('cmd', '')
                seq = args.pop('seq', None)
                try:
                    result = probe.do(name, args)
                except Exception as exc:           # noqa: BLE001
                    result = {'error': '%s: %s' % (type(exc).__name__, exc)}
                result.update({'event': 'cmd_result', 'seq': seq, 'cmd': name})
                out(result)
        time.sleep(CMD_POLL_SECONDS)


if __name__ == '__main__':
    sys.exit(main())
