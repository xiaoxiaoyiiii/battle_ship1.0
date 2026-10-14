"""布船放置完成后的状态清理与攻击额度同步。"""


class PlacementCompletion:
    def __init__(self, *, apply_last_stand_attacks, sync_attacks,
                 emit):
        self._apply_last_stand_attacks = apply_last_stand_attacks
        self._sync_attacks = sync_attacks
        self._emit = emit

    def finish(self, room, player_id, kind):
        pending = room.magic_temp_data.get('pending_placement') or {}
        placed = int(pending.get('placed') or 0)
        room.magic_temp_data.pop('pending_placement', None)
        if kind == 'last_stand':
            room.game_effects.pop('last_stand_cells', None)
            room.game_effects.pop('last_stand_owner', None)
        if kind == 'shenji_redeploy':
            room.game_effects.pop('shenji_redeploy_cells', None)
            room.game_effects.pop('shenji_redeploy_ships', None)
        self._emit('placement_done', {'kind': kind},
                   to=room.players[player_id].sid)
        if kind == 'last_stand':
            self._apply_last_stand_attacks(room, player_id)
        else:
            self._sync_attacks(room, player_id, placed)
