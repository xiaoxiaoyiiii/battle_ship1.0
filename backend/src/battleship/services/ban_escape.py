"""排位 Ban 初始布船逃跑的单方事务，不进入普通双人胜负结算。"""
from __future__ import annotations

import json
import threading
import time
import uuid

from ..domain.room import Room
from ..domain.settlement import settlement_facts
from ..infra.logging import get_logger
from ..repositories import Database
from .progression import ProgressionService
from .settlement import SettlementContext, SettlementResult

logger = get_logger('ban_escape')


class BanEscapeService:
    def __init__(self, database: Database | None) -> None:
        self.database = database
        self.progression = ProgressionService(database)
        # 同步事务自身也串行检查提交标记，避免异步请求取消后重入时双扣。
        self._lock = threading.Lock()

    def settle(self, room: Room, leaver_id: str) -> SettlementResult:
        with self._lock:
            if room.ban_escape_settled:
                return SettlementResult(ok=True, skipped=True)
            if self.database is None:
                return SettlementResult(ok=False, error='段位数据库不可用')
            survivor_id = room.opponent_of(leaver_id)
            if leaver_id not in room.players or survivor_id is None:
                return SettlementResult(ok=False, error='无效的逃跑座位')

            match_id = str(uuid.uuid4())
            timestamp = int(time.time())
            try:
                facts = settlement_facts(room, survivor_id, leaver_id)
                if not facts.loser_user_id:
                    return SettlementResult(ok=False, error='排位逃跑座位缺少账号')
                # 与正常排位相同：所有连败和双方段位在写入本局前读取。
                pre = self.progression.collect_pre_facts(room, facts)
                context = SettlementContext(
                    match_id=match_id, timestamp=timestamp, facts=facts,
                    replay_saved=False, pre=pre,
                )
                with self.database.unit_of_work() as uow:
                    leaver = uow.users.get(facts.loser_user_id)
                    if leaver is None:
                        raise ValueError('排位逃跑账号不存在')
                    # 没有胜方：幸存者没有胜场、历史、奖励或连败变化。
                    uow.matches.create(
                        match_id=match_id, winner_id=None,
                        loser_id=facts.loser_user_id,
                        timestamp=timestamp, mode='ranked',
                    )
                    uow.matches.add_log(match_id, json.dumps([{
                        'text': 'Ban 亮牌后布船阶段退出，判负扣分',
                        'type': 'result', 'reason': 'ranked_ban_escape',
                        'player': leaver_id,
                    }], ensure_ascii=False))
                    uow.users.update(
                        facts.loser_user_id,
                        losses=int(leaver.losses or 0) + 1, current_streak=0,
                    )
                    uow.stats.bump_counters(facts.loser_user_id, matches_played=1)
                    self.progression.apply_ban_escape(room, uow, context)
            except Exception as error:  # noqa: BLE001 - UoW 已整体回滚
                logger.error(
                    '排位 Ban 逃跑结算失败，事务已回滚',
                    extra={'room_id': room.id, 'leaver_id': leaver_id},
                    exc_info=error,
                )
                return SettlementResult(ok=False, error=str(error))

            result = SettlementResult(ok=True, match_id=match_id,
                                      events=tuple(context.events))
            # 只有事务成功提交后才记录；数据库失败保留原房，允许重试。
            room.ban_escape_settled = True
            room.settled = True
            room.settlement_result = result
            room.match_id = match_id
            return result
