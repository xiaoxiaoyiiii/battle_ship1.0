# -*- coding: utf-8 -*-
"""在线状态 / 对局中状态的**纯内存**登记表（2026-09-18 好友批）。

存在的唯一理由：`api.py`（HTTP 侧的好友接口）与 `server.py`（Socket.IO 侧）都要问
「这个 uid 现在在不在线、在不在局里」，而 `api.py` 被 `server.py` 反向依赖
（`server.py` 里 `from api import app`）—— api.py 一旦 import server 就是**循环导入**。
所以这份状态单独抽成零依赖模块：谁都能 import，谁也不依赖谁。

约定（与 server.py / api.py 冻结的契约一致，**名字一个都不能改**）：

    mark_online(uid) / mark_offline(uid)   同一 uid 多标签页：计数 ±1
    is_online(uid) -> bool
    is_in_game(uid) -> bool                是否坐在某局里（不在局里时好友申请要提示"对局中"）
    set_in_game(uid, on)
    online_uids() -> set[str]
    add_sid(uid, sid) / remove_sid(uid, sid) / sids_of(uid) -> list[str]
    clear()                                单测用

三条硬规矩：
  1. **任何函数都不许抛异常** —— 脏数据（None / 空串 / 非字符串）一律当没发生。
     调用点全在连接 / 断线 / 结算这些主链路上，这里抛一下就会把对局搞崩。
  2. **只维护内存**，不碰数据库、不 import 任何项目内模块（零依赖）。
  3. 一切读写都在 `threading.RLock()` 里。eventlet 下 `threading` 已被 monkey_patch
     成协程安全的版本，所以同一把锁在 eventlet 与 pytest 两种环境下都成立。

⚠️ `sids_of()` 与 `is_online()` 是**两件事**：前者只回答"这个 uid 名下登记过哪些
连接"，后者回答"他还在不在线"。推送前必须先判 `is_online()`（对方不在线就不发），
再对 `sids_of()` 里的每个 sid 各发一份（多标签页每张都要收到）。
"""
import threading

__all__ = [
    'mark_online', 'mark_offline', 'is_online',
    'is_in_game', 'set_in_game', 'online_uids',
    'add_sid', 'remove_sid', 'sids_of',
    'clear',
]


def _norm_id(value):
    """把 uid / sid 规范化成字符串；脏数据返回 None（**不抛异常**）。

    `hash()` 先试一下是为了挡掉 list / dict 这类不可哈希对象 —— 它们当真了会在
    查字典时抛 TypeError，而调用点（connect / disconnect / 结算）都在主链路上。
    """
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        hash(value)
    except TypeError:
        return None
    text = str(value).strip()
    return text if text else None


class Presence:
    """在线 / 对局中状态的唯一一份实现（模块底部导出一个共享实例）。"""

    def __init__(self):
        # 可重入锁：同一线程里 mark_offline → is_online 这种嵌套调用不会自锁死。
        self._lock = threading.RLock()
        # uid -> 在线连接数（同一 uid 开两个标签页就是 2）
        self._online = {}
        # uid -> [sid, ...]（登记过的连接，按登记顺序，去重）
        self._sids = {}
        # 对局中的 uid（由 server.py 在进房 / 结算处显式维护）
        self._in_game = set()

    # ---------------- 在线人数 ----------------
    def mark_online(self, uid) -> None:
        """登记一次连接：同一 uid 每来一个连接计数 +1（多标签页就是多次调用）。"""
        key = _norm_id(uid)
        if key is None:
            return
        try:
            with self._lock:
                self._online[key] = int(self._online.get(key, 0)) + 1
        except Exception:
            # 计数失败也不许把连接流程搞崩：最坏情况只是这个人显示为离线。
            return

    def mark_offline(self, uid) -> None:
        """注销一次连接：计数 -1，归零才真的算离线。

        ⚠️ 只对**登记过的** uid 生效（`mark_offline(None)` 或"从没 mark_online 过"
        的 uid 一律当没发生）—— 否则脏输入会把计数压成负数，`is_online` 的判据就
        "看着有、其实恒真/恒假"了。
        """
        key = _norm_id(uid)
        if key is None:
            return
        try:
            with self._lock:
                if key not in self._online:
                    return                       # 没登记过：当没发生（不抛、不置负）
                left = int(self._online.get(key, 0)) - 1
                if left > 0:
                    self._online[key] = left
                else:
                    self._online.pop(key, None)
        except Exception:
            return

    def is_online(self, uid) -> bool:
        key = _norm_id(uid)
        if key is None:
            return False
        try:
            with self._lock:
                return self._online.get(key, 0) > 0
        except Exception:
            return False

    def online_uids(self) -> set:
        """当前在线的全部 uid（**返回副本**，调用方改它不会影响登记表）。"""
        try:
            with self._lock:
                return {u for u, n in self._online.items() if n > 0}
        except Exception:
            return set()

    # ---------------- 对局中 ----------------
    def set_in_game(self, uid, on) -> None:
        """有人进入某局 / 离开某局时调用（挂点见 server.py 的 `_bind_presence_game`）。

        只认布尔真假的"真值"：`on` 传字符串 'false' 也会被当成 True —— 所以
        **调用方必须传真正的 bool**（server.py 两处都传字面量 True / False）。
        """
        key = _norm_id(uid)
        if key is None:
            return
        try:
            with self._lock:
                if on:
                    self._in_game.add(key)
                else:
                    self._in_game.discard(key)
        except Exception:
            return

    def is_in_game(self, uid) -> bool:
        key = _norm_id(uid)
        if key is None:
            return False
        try:
            with self._lock:
                return key in self._in_game
        except Exception:
            return False

    # ---------------- 连接登记（按 uid 推事件用） ----------------
    def add_sid(self, uid, sid) -> None:
        """登记 uid 名下的一条连接（同一个 sid 重复登记只留一份）。"""
        key, conn = _norm_id(uid), _norm_id(sid)
        if key is None or conn is None:
            return
        try:
            with self._lock:
                bucket = self._sids.setdefault(key, [])
                if conn not in bucket:
                    bucket.append(conn)
        except Exception:
            return

    def remove_sid(self, uid, sid) -> None:
        """注销一条连接（断线时调；uid 名下清空后连键一起删，不留空壳）。"""
        key, conn = _norm_id(uid), _norm_id(sid)
        if key is None or conn is None:
            return
        try:
            with self._lock:
                bucket = self._sids.get(key)
                if not bucket:
                    return
                try:
                    bucket.remove(conn)
                except ValueError:
                    return
                if not bucket:
                    self._sids.pop(key, None)
        except Exception:
            return

    def sids_of(self, uid) -> list:
        """uid 名下登记过的全部 sid（副本）。按 uid 推事件时逐个发，别只发第一个。"""
        key = _norm_id(uid)
        if key is None:
            return []
        try:
            with self._lock:
                return list(self._sids.get(key, ()))
        except Exception:
            return []

    # ---------------- 测试用 ----------------
    def clear(self) -> None:
        """清空全部内存状态（单测用；生产代码不许调）。"""
        try:
            with self._lock:
                self._online.clear()
                self._sids.clear()
                self._in_game.clear()
        except Exception:
            return


# 模块级共享实例 —— server.py / api.py / 单测都拿这一个。
presence = Presence()


# ---------------------------------------------------------------------------
# 冻结契约（模块级函数）：一律转调共享实例
# ---------------------------------------------------------------------------
def mark_online(uid) -> None:
    presence.mark_online(uid)


def mark_offline(uid) -> None:
    presence.mark_offline(uid)


def is_online(uid) -> bool:
    return presence.is_online(uid)


def is_in_game(uid) -> bool:
    return presence.is_in_game(uid)


def set_in_game(uid, on) -> None:
    presence.set_in_game(uid, on)


def online_uids() -> set:
    return presence.online_uids()


def add_sid(uid, sid) -> None:
    presence.add_sid(uid, sid)


def remove_sid(uid, sid) -> None:
    presence.remove_sid(uid, sid)


def sids_of(uid) -> list:
    return presence.sids_of(uid)


def clear() -> None:
    presence.clear()
