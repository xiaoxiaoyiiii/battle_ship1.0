"""房间生命周期、匹配队列和掉线宽限的纯领域模型。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


class RoomRuleError(ValueError):
    pass


@dataclass(frozen=True)
class MatchEntry:
    sid: str
    name: str
    user_id: str | None = None
    mode: Literal["casual", "ranked"] = "casual"
    ip: str = ""
    enqueued_at: float = 0.0


@dataclass(frozen=True)
class MatchQueue:
    entries: tuple[MatchEntry, ...] = ()

    def enqueue(self, entry: MatchEntry) -> "MatchQueue":
        if any(old.sid == entry.sid for old in self.entries):
            raise RoomRuleError("玩家已在匹配队列")
        if entry.mode not in ("casual", "ranked"):
            raise RoomRuleError("匹配模式无效")
        return replace(self, entries=self.entries + (entry,))

    def remove(self, sid: str) -> tuple["MatchQueue", bool]:
        kept = tuple(entry for entry in self.entries if entry.sid != sid)
        return replace(self, entries=kept), len(kept) != len(self.entries)

    def pick_pair(self) -> tuple["MatchQueue", tuple[MatchEntry, MatchEntry] | None]:
        for i, first in enumerate(self.entries):
            for j in range(i + 1, len(self.entries)):
                second = self.entries[j]
                if first.mode != second.mode:
                    continue
                if first.user_id and first.user_id == second.user_id:
                    continue
                kept = tuple(e for n, e in enumerate(self.entries) if n not in (i, j))
                return replace(self, entries=kept), (first, second)
        return self, None


@dataclass(frozen=True)
class DisconnectLease:
    player_id: str
    token: int
    deadline: float

    def is_expired(self, now: float) -> bool:
        return now >= self.deadline


@dataclass(frozen=True)
class RoomLifecycle:
    state: str
    is_ai_room: bool = False
    players: tuple[str, ...] = ()
    disconnected: tuple[str, ...] = ()

    def disconnect_expiry_action(self, player_id: str) -> Literal["cancel", "forfeit", "ignore"]:
        if player_id not in self.players or self.state == "game_over":
            return "ignore"
        other = tuple(pid for pid in self.players if pid != player_id)
        if self.is_ai_room or self.state in ("waiting", "placing_ships", "rock_paper_scissors") \
                or not other or any(pid in self.disconnected for pid in other):
            return "cancel"
        return "forfeit"
