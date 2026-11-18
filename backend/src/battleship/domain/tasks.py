"""航海任务的定义与北京时间周期；不依赖数据库和客户端上报。"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import time
from .room import Room

BEIJING = timezone(timedelta(hours=8))
TASKS = {
    'daily': (('wins', '每日首胜', '赢得任意对局', 1), ('cards', '魔法练习', '累计打出魔法卡', 5), ('ranked', '排位出航', '完成排位对局', 1)),
    'weekly': (('wins', '胜利航线', '赢得对局', 5), ('cards', '魔法研习', '累计打出魔法卡', 30), ('ranked', '排位远征', '完成排位对局', 8)),
}

# 每期轮换池：按周期 key 确定性选取，同一个周期内所有玩家看到同一套目标。
# 只复用服务端已跟踪的指标（wins/cards/ranked），不新增计数也不动数据库。
ROTATION = {
    'daily': {
        'cards': [(5, '魔法练习', '累计打出魔法卡'), (8, '火力全开', '累计打出魔法卡'), (10, '牌海无涯', '累计打出魔法卡')],
        'ranked': [(1, '排位出航', '完成排位对局'), (2, '两度远航', '完成排位对局')],
    },
    'weekly': {
        'wins': [(5, '胜利航线', '赢得对局'), (7, '连战连捷', '赢得对局')],
        'cards': [(30, '魔法研习', '累计打出魔法卡'), (40, '魔导深潜', '累计打出魔法卡')],
        'ranked': [(8, '排位远征', '完成排位对局'), (10, '舰队征途', '完成排位对局')],
    },
}

def _slot(seed: str, size: int, *, offset: int = 0) -> int:
    from zlib import crc32
    return (crc32(seed.encode('utf-8')) + offset * 0x9E3779B1) % size

def tasks_for(period: str, now: float | None = None) -> tuple:
    """当期任务：锚点条目固定，其余从轮换池按周期 key 选取。"""
    variants = TASKS[period]
    pool = ROTATION.get(period, {})
    seed = periods(now)[period]['start']
    chosen = []
    for position, (metric, title, description, target) in enumerate(variants):
        candidates = pool.get(metric)
        if candidates:
            entry = candidates[_slot(seed, len(candidates), offset=position)]
            target, title, description = entry
        chosen.append((metric, title, description, target))
    return tuple(chosen)

def periods(now: float | None = None) -> dict:
    current = datetime.fromtimestamp(time.time() if now is None else now, BEIJING)
    day = current.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - timedelta(days=day.weekday())
    return {
        'daily': {'start': day.date().isoformat(), 'end': (day + timedelta(days=1)).date().isoformat(), 'next_reset_at': int((day + timedelta(days=1)).timestamp())},
        'weekly': {'start': week.date().isoformat(), 'end': (week + timedelta(days=7)).date().isoformat(), 'next_reset_at': int((week + timedelta(days=7)).timestamp())},
    }

def record_card_play(room: Room, player_id: str, *, now: float | None = None) -> None:
    """只在真实扣牌入链后调用；被拒绝的请求不会进入此处。"""
    player = room.players.get(player_id)
    if not player or not player.registered or not player.user_id or player_id.startswith('ai-'):
        return
    day = periods(now)['daily']['start']
    by_day = room.task_card_uses.setdefault(player.user_id, {})
    by_day[day] = by_day.get(day, 0) + 1
