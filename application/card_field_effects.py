"""三张场地魔法生效后的房间状态更新。"""


class FieldEffects:
    def __init__(self, *, place_field_magic, recalc_attacks, emit):
        self._place_field_magic = place_field_magic
        self._recalc_attacks = recalc_attacks
        self._emit = emit

    def apply(self, room, caster_id, card, result):
        self._place_field_magic(room, caster_id, card)
        if card.name == '恶魔契约':
            room.game_effects['demon_contract'] = True
            result.message = '恶魔契约生效，双方船数增减绑定'
        elif card.name == '禁忌果实':
            result.message = '禁忌果实生效，双方只能使用失灵！和场地魔法'
        elif card.name == '伊甸园':
            result.message = '伊甸园生效，攻击次数变为6-n'
            if (room.state == 'attacking'
                    and getattr(room, 'current_phase', None) == 'preparation'
                    and room.current_attacker in room.players):
                self._recalc_attacks(room)
                self._emit('attacks_updated', {
                    'current_attacker': room.current_attacker,
                    'attacks_remaining': room.attacks_remaining,
                }, room=room.id)
        return True
