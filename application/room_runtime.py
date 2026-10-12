"""旧房间对象的注册、入座与匹配队列运行时。"""

import secrets
import threading
import time
import uuid
from typing import Any


class RoomManager:
    def __init__(self, *, room_factory, player_factory, card_catalog,
                 ai_runtime_factory, difficulties, normalize_mode, default_mode):
        self._room_factory = room_factory
        self._player_factory = player_factory
        self._card_catalog = card_catalog
        self._ai_runtime_factory = ai_runtime_factory
        self._difficulties = difficulties
        self._normalize_mode = normalize_mode
        self._default_mode = default_mode
        # 游戏房间数据结构
        self.rooms: dict[str, Any] = {}
        # 匹配队列：单结构列表，避免"三列平行数组"在并发下错位。
        # 每项形如 {'sid': str, 'name': str, 'user_id': str | None, 'mode': str}
        # ⚠️ `mode` 是 2026-09-17 排位批新增的第 4 个字段（'casual' / 'ranked'），
        #    **只在同 mode 之间配对**。所有使用点：入队 / 出队 / 去重 / 取消 /
        #    配对扫描（add_to_match_queue / remove_from_match_queue /
        #    has_player_in_match_queue / handle_find_match / handle_disconnect /
        #    handle_cancel_match）—— 改成平行数组的话漏一处就是错位。
        self.match_queue: list[dict] = []
        # 保护 rooms / match_queue 的读写（eventlet 下 threading 已被 monkey_patch）
        self._lock = threading.RLock()

    # 房间管理方法
    def create_room(self, room_id: str = None) -> str:
        """创建新房间，返回房间ID"""
        if not room_id:
            room_id = str(uuid.uuid4())[:6]
        room = self._room_factory(room_id)
        # 自定义房（create_room / join_room）**恒为休闲局**：双方可以互相刷分，
        # 所以排位标记只可能由匹配流程（handle_find_match）置 True。
        room.ranked = False
        with self._lock:
            self.rooms[room_id] = room
        return room_id

    def create_ai_room(self, player_id: str, player_name: str, player_user_id=None,
                         difficulty: str = 'normal') -> str:
        """创建人机对战房间：预置AI玩家，真人随后 join_room 走正常双人开局流程"""
        room_id = str(uuid.uuid4())[:6]
        room = self._room_factory(room_id)
        room.is_ai_room = True
        room.ai_seed = secrets.randbits(64)
        room.ai_runtime = self._ai_runtime_factory(room.ai_seed)
        # 人机局不给段位分（打电脑不能刷段位，与"人机不计 users.wins / 不发徽章"同一口径）。
        room.ranked = False
        room.ai_difficulty = difficulty if difficulty in self._difficulties() else 'normal'
        # 逐座位难度覆盖（默认空 = 全房间同档，即线上人机房的语义）。
        # 只有**自对弈度量**（tools/headless_game.py 的两个 AI 座位）才会填它：
        # 房间级的单一档位表达不了"p1 大师 / p2 困难"，不区分就会量成大师 vs 大师。
        room.ai_difficulty_by_player = {}
        with self._lock:
            self.rooms[room_id] = room
        ai_id = 'ai-' + room_id
        room.players[ai_id] = self._player_factory(name='AI', ships=[], attacks=[], remaining_ships=0, user_id=None, sid=ai_id)
        room.init_player_magic(ai_id, self._card_catalog())
        return room_id

    def join_room(self, room_id: str, player_id: str, player_name: str, sid: str) -> bool:
        """玩家加入房间，返回是否成功"""
        with self._lock:
            if room_id not in self.rooms:
                return False

            room = self.rooms[room_id]
            if len(room.players) >= 2:
                return False

            # 自定义房恒为休闲局（排位房只由匹配流程直接建，不走这里）。
            room.ranked = False
            room.players[player_id] = self._player_factory(**{
                'name': player_name,
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': player_id,
                'sid': sid
            })
        return True

    def get_room(self, room_id: str) -> Any | None:
        """获取房间对象"""
        return self.rooms.get(room_id)

    def delete_room(self, room_id: str) -> bool:
        """删除房间，返回是否成功"""
        with self._lock:
            if room_id in self.rooms:
                del self.rooms[room_id]
                return True
        return False

    def get_all_rooms(self) -> dict[str, Any]:
        """获取所有房间"""
        return self.rooms

    # 匹配功能方法
    def add_to_match_queue(self, player_id: str, player_name: str, user_id: str = None,
                           mode: str = None, ip: str = '') -> bool:
        """添加玩家到匹配队列，返回是否成功。

        `mode` 是**队列条目上的第四个字段**（2026-09-17 排位批）。队列本身仍是
        「单结构列表」（每项一个 dict，见 `match_queue` 的注释）—— 早年那版
        **三列平行数组** `[sids, names, user_ids]` 已被 2026-09-11 的有序性修复
        取代，因为"平行数组漏改一个就是错位"（把 A 的 mode 配给 B）。
        所以这里扩的是 dict 的键，不是列表的列；口径不变、错位风险更小。

        `ip` / `enqueued_at`（2026-09-20 匹配规避批）同样是**新增的键**：
        `ip` 用于同 IP 规避；`enqueued_at` 用于"等得久的人优先配上"。
        ⚠️ `ip` 只放在内存里，**不落库**（隐私决策，见 `_dirty_ips` 的说明）。
        """
        mode = self._normalize_mode(self._default_mode if mode is None else mode)
        with self._lock:
            if any(e['sid'] == player_id for e in self.match_queue):
                return False
            self.match_queue.append({'sid': player_id, 'name': player_name,
                                     'user_id': user_id, 'mode': mode,
                                     'ip': ip or '',
                                     'enqueued_at': time.time()})
        return True

    def remove_from_match_queue(self, player_id: str) -> bool:
        """从匹配队列移除玩家，返回是否成功"""
        with self._lock:
            for i, entry in enumerate(self.match_queue):
                if entry['sid'] == player_id:
                    self.match_queue.pop(i)
                    return True
        return False

    def has_player_in_match_queue(self, player_id: str) -> bool:
        """检查玩家是否在匹配队列中"""
        return any(e['sid'] == player_id for e in self.match_queue)

    def get_match_queue_size(self) -> int:
        """获取匹配队列大小"""
        return len(self.match_queue)
