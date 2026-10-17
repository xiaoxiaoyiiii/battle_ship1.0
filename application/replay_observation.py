"""将运行中的房间压缩为回放记录器需要的单次观察值。"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from replay import new_state


def capture_replay_observation(room):
    """复制双方的回放事实；仅录制状态在同一局内持续共享。"""
    if room is None:
        return None
    if not isinstance(getattr(room, 'replay', None), dict):
        if getattr(room, 'state', None) == 'game_over':
            return None
        room.replay = new_state()
    players = {}
    for pid, player in (getattr(room, 'players', None) or {}).items():
        players[pid] = SimpleNamespace(
            sid=getattr(player, 'sid', None),
            user_id=getattr(player, 'user_id', None),
            name=getattr(player, 'name', None),
            remaining_ships=getattr(player, 'remaining_ships', 0),
            ships=deepcopy(getattr(player, 'ships', None) or []),
            attacks=deepcopy(getattr(player, 'attacks', None) or []),
            magic_hand=[SimpleNamespace(name=getattr(card, 'name', str(card)))
                        for card in (getattr(player, 'magic_hand', None) or [])],
        )
    return SimpleNamespace(
        players=players,
        game_effects=deepcopy(getattr(room, 'game_effects', None) or {}),
        created_at=getattr(room, 'created_at', None),
        match_started_at=getattr(room, 'match_started_at', None),
        replay=room.replay,
    )


def clear_replay_observation(room) -> None:
    """结算收口释放单局状态，不依赖记录器持有房间。"""
    if room is not None:
        room.replay = None
