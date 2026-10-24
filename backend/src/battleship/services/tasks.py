"""任务查询与对局结算：身份、结果、用牌数量均来自服务端。"""
from __future__ import annotations
import time
from typing import TYPE_CHECKING
from ..domain.tasks import TASKS, periods
from ..domain.room import Room
from ..repositories import Database, UnitOfWork
if TYPE_CHECKING:
    from .settlement import SettlementContext

def task_view(database: Database, user_id: str | None, *, now: float | None = None) -> dict:
    timestamp = time.time() if now is None else now
    windows = periods(timestamp)
    with database.unit_of_work() as uow:
        authenticated = bool(user_id and uow.users.get(user_id))
        result = {'authenticated': authenticated, 'timezone': 'Asia/Shanghai', 'server_time': int(timestamp)}
        for period, window in windows.items():
            totals = uow.tasks.totals(user_id, window['start'], window['end']) if authenticated else {}
            result[period] = {
                **window,
                'tasks': [{'id': f'{period}_{metric}', 'metric': metric, 'title': title, 'description': description,
                    'target': target, 'current': min(totals.get(metric, 0), target),
                    'completed': authenticated and totals.get(metric, 0) >= target}
                    for metric, title, description, target in TASKS[period]],
            }
        return result

def settle_tasks(room: Room, uow: UnitOfWork, context: SettlementContext) -> None:
    """与比赛记录同事务；room.settled 防止重复结算，异常时一并回滚。"""
    day = periods(context.timestamp)['daily']['start']
    for seat, player in room.players.items():
        uid = player.user_id
        if not uid or not player.registered or seat.startswith('ai-') or not uow.users.get(uid):
            continue
        if seat == context.facts.winner_id:
            uow.tasks.increment(uid, day, 'wins')
        if context.facts.mode == 'ranked':
            uow.tasks.increment(uid, day, 'ranked')
        for played_day, count in room.task_card_uses.get(uid, {}).items():
            uow.tasks.increment(uid, played_day, 'cards', count)
