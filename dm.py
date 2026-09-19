# -*- coding: utf-8 -*-
"""好友私聊（2026-09-19）—— 单一真源：**纯数据 + 纯函数，无 IO**。

为什么单独一个文件（与 `quick_chat.py` / `achievements.py` / `profile_spec.py`
同一套路）：`api.py` 要下发这里的时间格式、长度上限与频率规则；若把它们写进
`server.py`，`api.py` 就反向依赖 `server.py`（而 `server.py` 是 `from api import app` 的，
会成环）。

三样东西各只有**一份实现**，别在别处再抄一遍：

  * `MAX_BODY_LEN` / `PER_MINUTE` —— 下发与校验用同一组常量（前端 `maxlength=300`
    也要与它一致，抄第二份必然漂移）；
  * `stamp()` —— 每条消息的显示时间**只由服务端格式化**，前端只渲染、不重算
    （本项目栽过"同一规则两份实现必然漂移"）；
  * `check_rate()` —— 频率判定规则（纯函数）。

⚠️ **频率状态不住在这里**：本模块没有任何可变状态、没有全局 dict。
本条路由的账在 `db` 里（`count_friend_messages_since` 数最近一分钟的真实行数）。
理由与 `quick_chat.py` 相同 —— 进程级全局 dict 会把**所有人**的发送串成一条队列
（甲刷屏，乙被 429），且多进程/eventlet worker 各存一份，判定与事实必然对不上。
用库里的行数当账本：天然按 `from_uid` 隔离、重启不丢、与"消息真的落库了"这件事
是同一条事实（不会出现"被拒的消息还占着配额"）。
"""

import time

# 单条正文上限（字）。**服务端拒绝**而不是静默截断 —— 截断会让用户以为自己发全了，
# 这是本项目明文记过一次的取舍（见 `docs/FRIEND_DM_2026_09_19.md` §1）。
MAX_BODY_LEN = 300

# 频率：每个发送者每分钟最多这么多条（超了回 429）。
PER_MINUTE = 20

# 频率窗口长度（秒）。与 `PER_MINUTE` 配套，单独抽出来是为了让"窗口 = 60 秒"
# 这个事实只有一处，测试与调用方不必各自写 60。
RATE_WINDOW_SECONDS = 60

# 一次取多少条历史（分页默认值与上限）。前端 `#dm-load-more` 按 `has_more` 显示。
PAGE_SIZE = 50
MAX_PAGE_SIZE = 50

# `stamp()` 用的格式串。**全年份不显示**（聊天列表里年份是噪声），
# 跨年的那一条才补上年份 —— 否则去年的「12-31 23:59」与今年的看起来一模一样。
_SHORT_FORMAT = '%m-%d %H:%M'
_FULL_FORMAT = '%Y-%m-%d %H:%M'

# `friend_message` 推送 payload 的字段（契约 §4「Socket 事件」）。
#
# ⚠️ 放进这个纯模块是**为了不让形状变成两份**：`api.py` 要按它裁掉视角字段
#    （`mine` / `to_uid` 是**发送方**视角才有的，推给收件人既没用又多一个可漂移的点），
#    `server.push_friend_message` 要按它收敛类型；两边各写一份字段列表就是
#    "同一个形状两处维护"。这里只声明一次，两边都从它取。
#    —— 与"总条数不能一边 SUM 一边 COUNT"是同一条规矩。
PUSH_PAYLOAD_KEYS = ('id', 'from_uid', 'from_username', 'from_avatar',
                     'body', 'created_at', 'stamp')


def push_payload(message: dict) -> dict:
    """把一条消息裁成**推送形状**（`PUSH_PAYLOAD_KEYS`，值一并收敛成 JSON 基础类型）。

    纯函数、只读入参（返回新 dict）：调用方（`api.py`）那份 dict 还要原样回给发送方，
    就地改它会出错。

    字段缺失时给安全的空值（`''` / `0`），而不是让 `None` 漏进 payload ——
    前端拿到 `null` 再渲染 `null.body` 会静默显示成空（本项目"接口给了 null
    而前端不报错"踩过同形状）。
    """
    src = dict(message or {})
    out = {}
    for key in PUSH_PAYLOAD_KEYS:
        raw = src.get(key)
        if key in ('id', 'created_at'):
            try:
                out[key] = int(raw or 0)
            except (TypeError, ValueError):
                out[key] = 0
        else:
            out[key] = '' if raw is None else str(raw)
    return out


def normalize_body(text) -> str:
    """正文归一化：去控制字符 → `\\n` 压成空格 → 去首尾空白。

    与 `profile_spec.normalize_status` **同口径**（那条一批是作者认可的写法）：
    控制字符（`\\x00` 等）是前端 `innerText` 渲染不出来、却能进库的脏数据，
    统一清掉再存。

    三条刻意的选择：
      · 换行**压成空格**而不是保留：私聊框是单行输入（前端 `#dm-input` 不是 textarea），
        保留的换行只会在渲染时把一条消息撑成两块，且 `\\n` 也能被用来刷屏；
      · **不截断**：超长由接口层明确回 400（"最多 300 字"），在这里悄悄砍掉半句
        就是"静默截断"那个坑；
      · 非字符串一律返回空串（不抛）—— 调用点是一个 HTTP 请求，
        为一段畸形 JSON 把请求打成 500 不值得。
    """
    if not isinstance(text, str):
        return ''
    # 与 `normalize_status` 同一套过滤：保留 `\n`（下面再压成空格），其余控制字符全清。
    cleaned = ''.join(ch for ch in text if ch == '\n' or ord(ch) >= 32)
    return cleaned.replace('\n', ' ').strip()


def body_error(text: str) -> str:
    """正文校验，返回中文原因；通过返回空串。

    **只判空与超长**（长度按 `len()` 数字符，与前端 `maxlength=300` 同一把尺子）。
    文案里点名"最多 300 字"，且超长时把当前字数也带上 —— 用户才知道自己超了多少。
    """
    if not text:
        return '消息不能为空'
    if len(text) > MAX_BODY_LEN:
        return f'消息最多 {MAX_BODY_LEN} 字（当前 {len(text)} 字）'
    return ''


def too_long(text: str) -> bool:
    """是否超过 `MAX_BODY_LEN`（接口层提前拦一道，避免把超长正文写进库）。"""
    return len(text or '') > MAX_BODY_LEN


def check_rate(timestamps, now=None) -> bool:
    """纯函数：`now` 之前 `RATE_WINDOW_SECONDS` 秒内已发条数是否已达上限。

    返回 True = **该拒绝**（429）。`timestamps` 是调用方从库里读出来的时间戳
    （`db.count_friend_messages_since` 的另一种用法：直接数条数也行，见下），
    本函数只做判定，**不记账、不存状态**。

    ⚠️ 不传 `timestamps` 而直接数条数的调用方也可以不用这个函数
    （`count >= PER_MINUTE` 就是同一条规则）—— 两种写法都只依赖这里的一个常量，
    规则仍然只有一份。保留这个纯函数是为了让"窗口 + 上限"能被单测直接钉住。

    `now` 缺省取当前时间；显式传入是为了让测试**不依赖真实时钟**。
    """
    now = time.time() if now is None else now
    count = 0
    for ts in timestamps or ():
        try:
            if now - float(ts) < RATE_WINDOW_SECONDS:
                count += 1
        except (TypeError, ValueError):
            # 脏时间戳（None / 字符串乱码）直接忽略：库里的坏一行不该把发送堵死
            continue
    return count >= PER_MINUTE


def stamp(epoch, now=None) -> str:
    """把 `created_at`（epoch 秒）格式化成显示用的时间串。**唯一一份实现。**

    规则（契约 §3）：同年 → `'09-19 15:40'`；**跨年** → `'2026-09-19 15:40'`。
    跨年判据是"那条消息的年份 ≠ 当前年份"（本地时区，与玩家感知一致）——
    不这么判的话，去年 12-31 夜里那句「23:59」与今年的是同一串字符，
    用户翻旧记录时分不出是哪一年。

    ⚠️ `now` 只用来**定年份**、不参与格式化：显式传入是为了让跨年规则可被单测
    钉住（否则那条测试只能在 12 月 31 日跑才有意义）。

    脏输入（None / 空串 / 非数字）返回空串而不是抛异常：一条读不出时间的旧行
    不该把整个会话打成 500，前端渲染空串即可（`#dm-stamp` 那格本来就是可选的）。
    """
    try:
        ts = int(epoch)
    except (TypeError, ValueError):
        return ''
    try:
        when = time.localtime(ts)
    except (OverflowError, OSError, ValueError):
        # 超出平台 time_t 范围的脏值（比如某个 0 被当成 1970 之前的巨大数）
        return ''
    ref = time.time() if now is None else now
    try:
        ref_year = time.localtime(ref).tm_year
    except (OverflowError, OSError, ValueError):
        ref_year = when.tm_year
    fmt = _SHORT_FORMAT if when.tm_year == ref_year else _FULL_FORMAT
    return time.strftime(fmt, when)


def conversation_key(me, other) -> tuple:
    """一段会话的标识（**只用于日志/调试**；库里没有会话表）。

    一对好友之间的会话由消息行本身表达（`(from,to)` 任一方向），多一张会话表
    就多一处要同步的状态（契约 §2 明确不建）。
    返回排序后的二元组，所以 A→B 与 B→A 算**同一段** —— 这正是"两个方向的会话
    合成同一条会话"的可读表达。
    """
    return tuple(sorted((str(me or ''), str(other or ''))))
