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
