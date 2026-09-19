# -*- coding: utf-8 -*-
"""好友功能的**接线**守卫 —— 每条都对应一次真踩过的坑，而**纯行为测试一条也测不到**。

背景：本地与线上都是 `python server.py` 启动的，那时模块名是 `__main__`。
api.py 曾经在请求处理里写 `import server` —— 那会把整个 server.py **再执行一遍**、
得到**另一个模块对象**：那份 socketio 发不出事件（申请/接受**静默丢弃**，接口照样回
sent/ok、服务端零报错），那份 room_manager 建的房在真进程里**根本不存在**
（邀战返回一个野 room_id）。线上是 run_prod.py 起的、模块名又正常 ——
属于"本地坏、线上好"的环境相关 bug。

⚠️ 为什么守卫必须是**源码级**的：pytest 里 server 就叫 `server` 这个名字，
`import server` 拿到的是同一个对象、行为完全正常，**这条 bug 在 pytest 里永远复现不出来**。
同理 `from api import app` 让 `api` 这个名字根本没绑定，注入那行会 NameError
被 except 吞成一句警告 —— 也是"测试全绿、线上静默失效"。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import api  # noqa: E402
import server  # noqa: E402,F401 —— import 期就完成注入


def _lines(name):
    with io.open(os.path.join(ROOT, name), encoding='utf-8') as f:
        return f.read().splitlines()


def test_api_must_not_import_server_at_runtime():
    """api.py 里不许有真的 `import server`（理由见模块 docstring）。"""
    hits = [ln.strip() for ln in _lines('api.py')
            if re.match(r'^[ \t]*(import\s+server\b|from\s+server\s+import\b)', ln)]
    assert hits == [], f'api.py 又在运行期 import server 了：{hits}'


def test_server_actually_injected_its_backend_module():
    """server.py 必须真的把**它自己那个模块对象**交过来（否则好友实时功能静默失效）。"""
    assert api._FRIEND_BACKEND_MODULE is server, (
        'api 没拿到 server 模块：推送/建房会静默失效（实时提示全无、邀战回 error）'
    )


def test_injected_room_creator_makes_a_room_that_really_exists():
    """邀战建房必须建在**正在服务**的 room_manager 里（否则邀请的是野房间）。"""
    room_id = server.create_custom_room_for_invite()
    try:
        assert room_id
        assert server.room_manager.get_room(room_id) is not None
    finally:
        server.room_manager.delete_room(room_id)


def test_backend_functions_are_resolved_lazily_so_monkeypatch_works():
    """按名字**现取**：打桩 `server.push_friend_invite` 必须当场生效。

    若改成注入函数对象，打桩会被静默架空（注入期就绑死了旧引用、测试还是绿的）。
    """
    original = server.push_friend_invite
    try:
        server.push_friend_invite = lambda *a: 'stubbed'
        assert api._friend_backend('push_friend_invite') is server.push_friend_invite
    finally:
        server.push_friend_invite = original


def test_missing_backend_degrades_to_none_instead_of_raising():
    """后端缺失时取函数返回 `None`（调用方据此明确失败），不许抛异常。"""
    saved = api._FRIEND_BACKEND_MODULE
    try:
        api._FRIEND_BACKEND_MODULE = None
        assert api._friend_backend('push_friend_invite') is None
        # 推送失败只回 False，绝不把请求打成 500
        assert api._push_friend_event('push_friend_invite', 'u', 'r', 'f', 'n') is False
    finally:
        api._FRIEND_BACKEND_MODULE = saved


def test_frontend_relation_whitelist_covers_every_server_value():
    """前端的关系取值白名单必须**覆盖**服务端的取值集合（源码级对账，不用浏览器）。

    ⚠️ 守的是"同一个业务判断有两份实现就一定会漂移"（CLAUDE.md 坑 #1）。
    实测栽过的那一次：服务端会下发 `blocked_by_me` / `blocked_me`，而 `game.js` 的
    `FRIEND_RELATIONS` 没有这两个取值 —— 它在那边是**合法性白名单**（`indexOf(...) >= 0`），
    于是被判非法、**降级成 `none`** → 结算行上渲染出一个**可点的「加好友」**，
    点下去服务端只回一句中文原因（端到端验证钉出来的 PB3）。
    前端那份是字面量数组，正则读出来即可；**新增关系状态时这条会先红**。
    """
    js = '\n'.join(_lines('static/game.js'))
    m = re.search(r"const FRIEND_RELATIONS = \[(.*?)\];", js, re.S)
    assert m, 'static/game.js 里找不到 FRIEND_RELATIONS 字面量（改名了？）'
    front = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    backend = set(server.FRIEND_RELATIONS)
    missing = sorted(backend - front)
    assert not missing, f'前端不认识这些关系取值（会被降级成 none）：{missing}'
