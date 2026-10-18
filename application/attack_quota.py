"""攻击额度的计算与增量更新。"""


class AttackQuota:
    def __init__(self, *, forced_zero, field_magic, frozen_ships, emit):
        self._forced_zero = forced_zero
        self._field_magic = field_magic
        self._frozen_ships = frozen_ships
        self._emit = emit

    def grant(self, room, player_id, count=1):
        if int(count) <= 0 or room.state != 'attacking':
            return 0
        if room.current_attacker != player_id:
            return 0
        if self._forced_zero(room) or self._field_magic(room) == '教皇旨意':
            return 0
        before = int(room.attacks_remaining or 0)
        room.attacks_remaining = max(0, before + int(count))
        self._emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining,
        }, room=room.id)
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
