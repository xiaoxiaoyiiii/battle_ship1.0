"""牌效完成后的公开播放提示，不携带私有目标、手牌或棋盘信息。"""

from __future__ import annotations

import uuid

from ..domain.room import Room
from .rooms import EventPublisher


async def emit_magic_sfx(publisher: EventPublisher, room: Room,
                         caster: str, card: str) -> None:
    await publisher.emit(
        "game_message",
        {"type": "magic_sfx", "room_id": room.id, "caster": caster,
         "card": card, "effect_id": uuid.uuid4().hex},
        room=room.id,
    )


# 这些牌的成功返回值可能只表示开始选择、部署、预测或重摆。
# 完成提示由各自确认漏斗发出，包含 AI 同步完成的路径。
COMPLETION_AUDIO_CARDS = frozenset({
    "桃园结义", "明智埋葬", "亡羊补牢", "增援", "死者苏生", "滥竽充数",
    "绝处逢生", "神机妙算", "灵气复苏", "回光返照", "败者食尘",
    # 掷骰声由真实 dice_rolled 事件负责，不在整张牌结束时重复播放。
    "命运骰子",
})

PICK_AUDIO_REASONS = {
    "守株待兔": "trap_setup", "克苏鲁之眼": "kraken_eye", "神之宣告": "divine_decree",
}


async def emit_reset_sfx(publisher: EventPublisher, room: Room) -> None:
    pending = room.game_effects.pop("reset_audio", None)
    if isinstance(pending, dict) and pending.get("caster") in room.players:
        await emit_magic_sfx(publisher, room, pending["caster"], pending["card"])
