"""攻击造成伤害后的攻击方增益。"""


class AttackDamageEffects:
    def __init__(self, *, draw_card, emit):
        self._draw_card = draw_card
        self._emit = emit

    def apply(self, room, room_id, attacker_id):
        attacker = room.players[attacker_id]
        flags = attacker.effect_flags
        if flags.vampire:
            self._draw_card(room, attacker_id)
            self._emit('message', {'text': '饮血效果发动，抽一张卡'}, to=attacker.sid)
        if flags.battle_spirit:
            room.attacks_remaining += 1
            self._emit('message', {
                'text': '越战越勇效果发动，攻击次数净增加1',
            }, room=room_id)
        attacker.damage_dealt_this_turn += 1
