"""大厅在线状态、成员关系与公屏消息的运行时所有者。"""

import threading
import time

LOBBY_CHAT_MAX_LEN = 120
LOBBY_CHAT_MIN_INTERVAL = 1.0
LOBBY_CHAT_BACKLOG = 30
LOBBY_PROFILE_TTL = 60.0
LOBBY_NAME_MAX_LEN = 24


def clean_lobby_name(name, fallback: str = '游客') -> str:
    """玩家名的统一清洗：去首尾空白 → 截断 → 空串回落。

    ⚠️ 大厅的名字有三个来源（session / find_match 的 payload / 大厅订阅的 payload），
    必须在**入口处**统一，不能各写各的截断长度。
    """
    text = str(name or '').strip()
    if not text:
        return fallback
    return text[:LOBBY_NAME_MAX_LEN]


class LobbyManager:
    """大厅状态：在线表 + 成员表 + 公屏聊天。

    所有读写都持同一把锁（eventlet 下 threading 已被 monkey_patch，锁是绿的）。
    """

    def __init__(self, profile_lookup):
        self._profile_lookup = profile_lookup
        self._lock = threading.RLock()
        # sid -> {'name','user_id','connected_at','profile','profile_at'}
        self._presence: dict[str, dict] = {}
        # sid -> {'name','joined_at'}（presence 的子集）
        self._members: dict[str, dict] = {}
        # 公屏最近消息（只保留 LOBBY_CHAT_BACKLOG 条）
        self._chat: list[dict] = []
        # 单调序号：前端靠它做"这条我有没有"的判断。没有它就只能靠文案/时间猜，
        # 而补发的历史与实时推送**会重叠**（见 applyLobbyChatHistory 的注释）。
        self._chat_seq = 0
        # sid -> 上一条发言时间（防刷）
        self._last_chat_at: dict[str, float] = {}

    # ---- 在线表 -----------------------------------------------------------
    def add_connection(self, sid: str, name=None, user_id=None) -> None:
        """连接建立时登记。名字可能还不知道（游客在首页才输入），后面再补。"""
        with self._lock:
            row = self._presence.get(sid)
            if row is None:
                row = {'name': '', 'user_id': None, 'connected_at': time.time(),
                       'profile': None, 'profile_at': 0.0}
                self._presence[sid] = row
            if name:
                row['name'] = clean_lobby_name(name)
            if user_id is not None:
                row['user_id'] = user_id

    def update_identity(self, sid: str, name=None, user_id=None) -> None:
        """补写身份（游客名 / 登录态）。连接不在表里时自动补登。"""
        if sid not in self._presence:
            self.add_connection(sid, name, user_id)
            return
        with self._lock:
            row = self._presence[sid]
            if name:
                row['name'] = clean_lobby_name(name)
            if user_id is not None:
                row['user_id'] = user_id

    def remove_connection(self, sid: str) -> bool:
        """连接断开：同时退出在线表、成员表与防刷记录。"""
        with self._lock:
            existed = self._presence.pop(sid, None) is not None
            self._members.pop(sid, None)
            self._last_chat_at.pop(sid, None)
        return existed

    def online_count(self) -> int:
        with self._lock:
            return len(self._presence)

    def presence(self) -> dict:
        """在线表快照（浅拷贝，供 build_lobby_state 遍历用）。"""
        with self._lock:
            return {sid: dict(row) for sid, row in self._presence.items()}

    def profile_of(self, sid: str) -> dict:
        """取该连接的头像 / 称号缓存；过期或缺失时查库并回写（TTL = LOBBY_PROFILE_TTL）。

        ⚠️ 必须缓存：`lobby_state` 每 4 秒兜底广播一次，逐人查库等于每秒几十次查询。
        游客（没有 user_id）直接返回空缓存，不查库。
        """
        now = time.time()
        with self._lock:
            row = self._presence.get(sid)
            if row is None:
                return {'avatar': '', 'title': '', 'name_style': ''}
            cached = row.get('profile')
            if cached is not None and now - float(row.get('profile_at') or 0) < LOBBY_PROFILE_TTL:
                return dict(cached)
            uid = row.get('user_id')
        profile = self._profile_lookup(uid)
        with self._lock:
            row = self._presence.get(sid)
            if row is not None:
                row['profile'] = profile
                row['profile_at'] = now
        return dict(profile)

    # ---- 大厅成员 ---------------------------------------------------------
    def subscribe(self, sid: str, name=None, user_id=None) -> bool:
        """进入大厅。幂等：重复调用只刷新名字，不重复入表。"""
        self.update_identity(sid, name, user_id)
        with self._lock:
            if sid in self._members:
                if name:
                    self._members[sid]['name'] = clean_lobby_name(name)
                return False
            self._members[sid] = {'name': clean_lobby_name(name), 'joined_at': time.time()}
        return True

    def unsubscribe(self, sid: str) -> bool:
        with self._lock:
            return self._members.pop(sid, None) is not None

    def is_member(self, sid: str) -> bool:
        with self._lock:
            return sid in self._members

    def member_count(self) -> int:
        with self._lock:
            return len(self._members)

    def members(self) -> list[str]:
        with self._lock:
            return list(self._members.keys())

    # ---- 公屏聊天 ---------------------------------------------------------
    def chat_allowed(self, sid: str, now: float = None) -> bool:
        """频率闸门：同一连接两条之间至少间隔 LOBBY_CHAT_MIN_INTERVAL 秒。"""
        now = time.time() if now is None else now
        with self._lock:
            last = self._last_chat_at.get(sid)
            if last is not None and now - last < LOBBY_CHAT_MIN_INTERVAL:
                return False
            self._last_chat_at[sid] = now
        return True

    def add_chat(self, sid: str, name: str, message: str) -> dict | None:
        """入库一条公屏消息。空白消息返回 None（调用方据此静默丢弃）。"""
        text = str(message or '').strip()[:LOBBY_CHAT_MAX_LEN]
        if not text:
            return None
        with self._lock:
            self._chat_seq += 1
            item = {'key': sid, 'name': clean_lobby_name(name),
                    'message': text, 'ts': time.time(), 'seq': self._chat_seq}
            self._chat.append(item)
            if len(self._chat) > LOBBY_CHAT_BACKLOG:
                del self._chat[:len(self._chat) - LOBBY_CHAT_BACKLOG]
        return item

    def recent_chat(self) -> list[dict]:
        with self._lock:
            return [dict(m) for m in self._chat]
