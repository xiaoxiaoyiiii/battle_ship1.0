"""攻击额度的计算与增量更新。"""


class AttackQuota:
    def __init__(self, *, forced_zero, field_magic, frozen_ships, emit):
        self._forced_zero = forced_zero
        self._field_magic = field_magic
        self._frozen_ships = frozen_ships
        self._emit = emit

    def _emit_updated(self, room):
        self._emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining,
        }, room=room.id)

    def grant(self, room, player_id, count=1):
        if int(count) <= 0 or room.state != 'attacking':
            return 0
        if room.current_attacker != player_id:
            return 0
        if self._forced_zero(room) or self._field_magic(room) == '教皇旨意':
            return 0
        before = int(room.attacks_remaining or 0)
        room.attacks_remaining = max(0, before + int(count))
        self._emit_updated(room)
        return room.attacks_remaining - before

    def recalculate(self, room):
        player_id = room.current_attacker
        if not player_id or player_id not in room.players:
            return
        if self._forced_zero(room):
            room.attacks_remaining = 0
            return
        player = room.players[player_id]
        bonus = int(getattr(player.effect_flags, 'subsidy_bonus', 0) or 0)
        field = self._field_magic(room)
        if field == '教皇旨意':
            base = 0
        elif field == '伊甸园':
            base = max(0, 6 - player.remaining_ships)
        else:
            base = max(0, player.remaining_ships - self._frozen_ships(player))
        room.attacks_remaining = base + bonus

    def apply_last_stand(self, room, player_id):
        """绝处逢生后按唯一存活战舰重置攻击额度。"""
        if room.state != 'attacking' or room.current_attacker != player_id:
            return
        if self._forced_zero(room):
            room.attacks_remaining = 0
        else:
            player = room.players[player_id]
            field = self._field_magic(room)
            if field == '教皇旨意':
                base = 0
            elif field == '伊甸园':
                base = max(0, 6 - player.remaining_ships)
            else:
                base = 1
            bonus = int(getattr(player.effect_flags, 'subsidy_bonus', 0) or 0)
            room.attacks_remaining = max(0, base + bonus)
        self._emit_updated(room)

    def recalculate_after_field_removal(self, room, previous_field, *, had_papal=False):
        """场地魔法移除后，按仍在场的规则修正当前攻击额度。"""
        if room.state != 'attacking':
            return
        player_id = room.current_attacker
        if not player_id or player_id not in room.players:
            return
        if not had_papal and previous_field not in ('伊甸园', '教皇旨意'):
            return
        active_field = self._field_magic(room)
        if previous_field is not None and active_field == previous_field:
            active_field = None
        player = room.players[player_id]
        bonus = int(getattr(player.effect_flags, 'subsidy_bonus', 0) or 0)
        if active_field == '伊甸园':
            base = max(0, 6 - player.remaining_ships)
        elif active_field == '教皇旨意':
            base = 0
        else:
            base = max(0, player.remaining_ships - self._frozen_ships(player))
        room.attacks_remaining = max(0, base + bonus)
        self._emit_updated(room)
