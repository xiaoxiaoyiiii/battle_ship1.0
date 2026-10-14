"""船位变化后的攻击次数同步规则。"""


class ShipAttackSync:
    """按注入的运行时查询同步当前攻击者的攻击额度。"""

    def __init__(self, *, attacks_forced_zero, field_magic_name, emit):
        self._attacks_forced_zero = attacks_forced_zero
        self._field_magic_name = field_magic_name
        self._emit = emit

    def sync(self, room, player_id, ships_added=1):
        if room.state != 'attacking':
            return
        if room.current_attacker != player_id:
            return
        if self._attacks_forced_zero(room):
            return
        if ships_added <= 0:
            return
        field = self._field_magic_name(room)
        if field == '教皇旨意':
            per_ship = 0
        elif field == '伊甸园':
            per_ship = -1
        else:
            per_ship = 1
        if per_ship:
            room.attacks_remaining = max(
                0, room.attacks_remaining + per_ship * ships_added)
        self._emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining,
        }, room=room.id)
