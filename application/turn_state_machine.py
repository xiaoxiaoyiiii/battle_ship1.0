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
