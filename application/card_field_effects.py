"""三张场地魔法生效后的房间状态更新。"""


class FieldEffects:
    def __init__(self, *, place_field_magic, recalc_attacks, emit,
                 clear_ship_picks, recalc_after_removal, field_name):
        self._place_field_magic = place_field_magic
        self._recalc_attacks = recalc_attacks
        self._emit = emit
        self._clear_ship_picks = clear_ship_picks
        self._recalc_after_removal = recalc_after_removal
        self._field_name = field_name

    def clear(self, room, previous_field=None):
        """清理场地留下的效果，并修正受影响的攻击额度。"""
        had_papal = bool(room.game_effects.get('papal_edict'))
        previous = (previous_field if previous_field is not None
                    else self._field_name(room))
        if room.game_effects.pop('demon_contract', None) is not None:
            self._clear_ship_picks(room, 'demon_contract')
        room.game_effects.pop('papal_edict', None)
        self._recalc_after_removal(room, previous, had_papal=had_papal)

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
        elif card.name == '教皇旨意':
            # 这张速阶 1 场地卡也允许在战斗阶段打出，所以不能只依赖
            # preparation -> battle 的阶段切换来归零；必须在结算当场更新。
            room.game_effects['papal_edict'] = True
            room.attacks_remaining = 0
            self._emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining,
            }, room=room.id)
            result.message = (
                '教皇旨意已生效，双方攻击次数变为0，通过弃置魔法卡攻击对方两次')
        return True
