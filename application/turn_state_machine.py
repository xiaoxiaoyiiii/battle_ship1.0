"""回合状态机的基础转换。"""


class TurnStateMachine:
    def __init__(self, *, sleep, frozen_ship_count, recalc_attacks,
                 emit, run_ai_turn):
        self._sleep = sleep
        self._frozen_ship_count = frozen_ship_count
        self._recalc_attacks = recalc_attacks
        self._emit = emit
        self._run_ai_turn = run_ai_turn

    def switch_after_end(self, room, opponent_id, delay=2):
        self._sleep(delay)
        room.current_attacker = opponent_id
        player = room.players[opponent_id]
        room.attacks_remaining = max(
            0, player.remaining_ships - self._frozen_ship_count(player)
        )
        self._recalc_attacks(room)
        room.current_phase = 'preparation'
        player.damage_dealt_this_turn = 0
        self._emit('turn_change', {
            'current_attacker': opponent_id,
            'attacks_remaining': room.attacks_remaining,
            'phase': 'preparation',
        }, room=room.id)
        self._run_ai_turn(room)

    def enter_end(self, room, player_id):
        """完成当前行动者从战斗阶段进入结束阶段的状态转换。"""
        room.current_phase = 'end'
        flags = room.players[player_id].effect_flags
        if getattr(flags, 'forced_kill', 0) > 0:
            flags.forced_kill -= 1
            if flags.forced_kill <= 0:
                del flags.forced_kill
        room.players[player_id].effect_flags.battle_spirit = False
        self._emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker,
        }, room=room.id)
