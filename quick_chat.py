# -*- coding: utf-8 -*-
"""局内快捷语 / 表情（第 4 批）—— 单一来源：**纯数据 + 纯函数，无 IO**。

为什么单独一个文件（与第 2 批的 `achievements.py` 同一套路）：
  * `api.py` 要下发这份表；若把它写进 `server.py`，`api.py` 就反向依赖
    `server.py`（而 `server.py` 是 `from api import app` 的，会成环）；
  * 前端**不许**写死任何一句文案：`game.js` 从 `GET /api/quick_chat` 取，
    服务端只认 id。前后端各写一份文案必然漂移（本项目已吃过多次）。

所以这里只有两样东西：`QUICK_CHAT`（顺序即界面顺序）与几个纯函数。
**频率状态不住在这里** —— 它属于房间（`GameRoom.quick_chat_recent` /
`GameRoom.quick_chat_last`），本模块只提供判定规则 `check_rate()`，
这样"同一个房间里的两个人才互相约束"，也避免进程级全局状态串房间。
"""

from typing import Any

# 分组顺序即界面上的分组顺序（前端按 GROUPS 的顺序渲染分组）。
GROUPS = ["开局", "催促", "交手", "被击沉", "投降前", "结束"]

# 快捷语表。**顺序即界面顺序**，文案逐字与 `docs/BATCH_2_3_4_PLAN.md` §4.3 一致。
#
# ⚠️ 作者点名必须有这一句：id="hurry_flowers" / "快点儿吧，我等的花都谢了"
#    —— 一个标点都不许改（端到端工具会拿接口 / 页面 / 对手收到的 payload 三处逐字比对）。
QUICK_CHAT: list[dict[str, str]] = [
    {"id": "hi", "group": "开局", "text": "你好，开打吧！"},
    {"id": "lets_go", "group": "开局", "text": "来，先手我拿走了"},
    {"id": "hurry_flowers", "group": "催促", "text": "快点儿吧，我等的花都谢了"},
    {"id": "think_fast", "group": "催促", "text": "想好了没呀？"},
    {"id": "nice_shot", "group": "交手", "text": "打得漂亮！"},
    {"id": "oops", "group": "交手", "text": "哎呀，手滑了"},
    {"id": "lucky", "group": "交手", "text": "这运气也没谁了"},
    {"id": "almost", "group": "交手", "text": "就差一点"},
    {"id": "watch_this", "group": "交手", "text": "看我这手"},
    {"id": "ouch", "group": "被击沉", "text": "我的船！"},
    {"id": "surrender_soon", "group": "投降前", "text": "我快撑不住了…"},
    {"id": "gg", "group": "结束", "text": "GG，打得好"},
    {"id": "rematch", "group": "结束", "text": "再来一局？"},
    {"id": "thanks", "group": "结束", "text": "多谢指教"},
]

# 白名单索引（只此一份；校验与取文案都走它，不允许别处再抄一份 id 列表）
_BY_ID: dict[str, dict[str, str]] = {m["id"]: m for m in QUICK_CHAT}

WINDOW_SECONDS = 10   # 频率窗口（秒）
MAX_PER_WINDOW = 3    # 窗口内最多能发几条


def by_id(msg_id: Any) -> dict | None:
    """按 id 取一条快捷语（含 text）；取不到返回 None。

    返回的是**副本**：调用方改不动这张表（曾经吃过"顺手改一下常量"的亏）。
    非字符串一律当取不到 —— 直接拿 list/dict 去查会抛 TypeError（不可哈希）。
    """
    item = _BY_ID.get(msg_id) if isinstance(msg_id, str) else None
    return dict(item) if item else None


def catalog() -> list[dict]:
    """下发给前端的形状：每条只有 id / group / text，顺序同 QUICK_CHAT。

    逐字段显式构造（不是 `dict(item)`）：以后往表里加内部字段（例如权限位）
    也不会顺手泄露给前端，`catalog()` 的形状是冻结契约的一部分。
    """
    return [{"id": m["id"], "group": m["group"], "text": m["text"]} for m in QUICK_CHAT]


def is_valid(msg_id: Any) -> bool:
    """id 是否在白名单内（非字符串一律 False）。"""
    return isinstance(msg_id, str) and msg_id in _BY_ID


def _last_of(last_id: Any) -> tuple[Any, Any]:
    """把 `last_id` 归一化成 (msg_id | None, ts | None)。

    接受房间里的存法 `{'id': …, 'ts': …}`，也接受 `(id, ts)` 二元组。
    传入裸字符串时 ts 未知 —— 交给 check_rate 按"无法证明窗口已过"处理。
    """
    if not last_id:
        return None, None
    if isinstance(last_id, dict):
        return last_id.get("id"), last_id.get("ts")
    if isinstance(last_id, (tuple, list)) and len(last_id) == 2:
        return last_id[0], last_id[1]
    return last_id, None


def _count_in_window(recent: Any, now: float) -> int:
    """窗口内的时间戳条数。非数字的脏数据直接忽略（房间状态坏了不该 500）。"""
    count = 0
    for t in recent or []:
        try:
            if now - float(t) < WINDOW_SECONDS:
                count += 1
        except (TypeError, ValueError):
            continue
    return count


def check_rate(recent: Any, now: float, last_id: Any, msg_id: str) -> tuple[bool, str]:
    """纯函数：这条快捷语现在能不能发。返回 `(ok, reason)`，通过时 reason 为空串。

    两条规则（契约 §4.3）：
      ① 窗口内最多 `MAX_PER_WINDOW` 条 —— 连点刷屏在这里被挡；
      ② 同一句 `msg_id` 在窗口内不许重复 —— 「连点同样内容」不会变成刷屏工具。

    `recent`：该玩家最近发送的时间戳列表（升序；本函数不依赖升序，只看差值）；
    `last_id`：该玩家最近一条的 `{'id': …, 'ts': …}`（见 `_last_of`），没有就 None。

    ⚠️ 两条规则都只**判定**、不记账：时间戳由调用方（socket handler）在
    "真的发出去之后"才写进房间状态 —— 被拒的那条不留痕，否则拒绝本身
    也会把窗口占满（连点 5 次会被拒到 20 秒之后）。
    """
    if _count_in_window(recent, now) >= MAX_PER_WINDOW:
        return False, f'发得太快了，{WINDOW_SECONDS} 秒内最多发 {MAX_PER_WINDOW} 条快捷语'

    last_msg, last_ts = _last_of(last_id)
    if last_msg is not None and last_msg == msg_id:
        # ts 缺失（调用方只传了 id）时无法证明窗口已过 → 保守拒绝
        if last_ts is None or now - last_ts < WINDOW_SECONDS:
            return False, f'同一句快捷语 {WINDOW_SECONDS} 秒内不能重复发送'

    return True, ''
