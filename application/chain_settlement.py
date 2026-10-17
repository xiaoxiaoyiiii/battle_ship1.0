"""连锁结算完成后的统一状态同步。"""


class ChainSettlement:
    def __init__(self, *, emit, clear_display, active_effects,
                 emit_ships_updated, emit_player_ships, continue_priority):
        self._emit = emit
        self._clear_display = clear_display
        self._active_effects = active_effects
        self._emit_ships_updated = emit_ships_updated
        self._emit_player_ships = emit_player_ships
        self._continue_priority = continue_priority

    def finalize(self, room, results):
        self._emit('chain_resolved', {'results': results}, room=room.id)
        room.chain = []
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes = 0
        self._clear_display(room)
        room.game_effects.pop('stolen_cards', None)
        self._active_effects(room)
        for player in room.players.values():
            if getattr(player, 'sid', None):
                self._emit('hand_updated', {'hand': player.magic_hand}, to=player.sid)
        self._emit_ships_updated(room)
        for player_id in room.players:
            self._emit_player_ships(room, player_id)
        self._emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker,
        }, room=room.id)
        pending = getattr(room, 'priority_continue', None)
        if pending:
            room.priority_continue = None
            self._continue_priority(room, pending['actor'], pending['action'])
