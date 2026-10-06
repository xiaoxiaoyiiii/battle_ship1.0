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
