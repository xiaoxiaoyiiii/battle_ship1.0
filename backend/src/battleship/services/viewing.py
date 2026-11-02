"""观看提交编排：录制完整状态，向独立观战频道发布公开帧。"""
from __future__ import annotations

from ..domain import replay
from ..domain.replay_v2 import record_state, record_presentation
from ..domain.viewing import build_view_frame, public_cue, replay_cue
from ..infra.logging import get_logger

logger = get_logger('viewing')


class ViewingService:
    def __init__(self, rooms):
        self.rooms = rooms
        self.spectators = None

    def bind(self, spectators) -> None:
        self.spectators = spectators

    async def commit(self, room, *, cause: str = 'state') -> None:
        if not room.settled:
            record_state(room, step=max(0, replay.step_count(room) - 1), cause=cause)
        await self._publish(room, [])

    async def present(self, room, cue: dict) -> None:
        record_state(room, step=max(0, replay.step_count(room) - 1), cause='presentation')
        recorded = replay_cue(cue, room)
        if recorded:
            record_presentation(room, recorded, step=max(0, replay.step_count(room) - 1))
        clean = public_cue(cue, room)
        await self._publish(room, [clean] if clean else [])

    async def attack(self, room, outcome) -> None:
        """前导、实际落点、尾声有序保存；观战先展示上一权威帧。"""
        step = replay.step_count(room)
        cue = {'stage': 'attack_windup', 'attacker': outcome.attacker, 'target': outcome.defender,
               'cell': {'x': outcome.x, 'y': outcome.y},
               'result': {'hit': outcome.hit, 'sunk': outcome.ship_sunk,
                          'shield_blocked': outcome.shield_blocked, 'invincible': outcome.invincible}}
        clean = public_cue(cue, room)
        record_presentation(room, clean, step=step)
        await self._publish(room, [clean], frame=room._viewing_public_frame)
        record_state(room, step=step, cause='attack_impact')
        tail = {**clean, 'stage': 'attack_tail'}
        record_presentation(room, tail, step=step)
        await self._publish(room, [tail])

    async def _publish(self, room, cues: list[dict], *, frame=None) -> None:
        frame = frame if frame is not None else build_view_frame(room, audience='spectator')
        if not cues and frame == room._viewing_public_frame:
            return
        room._viewing_public_frame = frame
        room.viewing_sequence += 1
        if self.spectators is not None:
            try:
                await self.spectators.publish_view_frame(room, frame, seq=room.viewing_sequence, cues=cues)
            except Exception as error:  # 观战网络失败不能回滚或中断已经完成的玩家动作。
                logger.warning('观战帧发送失败', extra={'room_id': room.id}, exc_info=error)
