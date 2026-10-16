"""回合状态机的基础转换。"""


class TurnStateMachine:
    def __init__(self, *, recalc_attacks,
                 emit, run_ai_turn, attacks_forced_zero, trigger_wuxian,
                 settle_wuyou, settle_bingliang, prune_flags, emit_active_effects,
                 keep_across_turn):
        self._recalc_attacks = recalc_attacks
        self._emit = emit
        self._run_ai_turn = run_ai_turn
        self._attacks_forced_zero = attacks_forced_zero
        self._trigger_wuxian = trigger_wuxian
        self._settle_wuyou = settle_wuyou
        self._settle_bingliang = settle_bingliang
        self._prune_flags = prune_flags
        self._emit_active_effects = emit_active_effects
        self._keep_across_turn = keep_across_turn

    def enter_battle(self, room, player_id):
        room.current_phase = 'battle'
        self._recalc_attacks(room)
        player = room.players[player_id]
        if player.effect_flags.double_attacks:
            room.attacks_remaining = max(0, room.attacks_remaining) * 2
            self._emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining,
            }, room=room.id)
            player.effect_flags.double_attacks = False
        self._emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining,
        }, room=room.id)
        if room.attacks_remaining <= 0 and not self._attacks_forced_zero(room):
            self._trigger_wuxian(room, player_id)
        self._emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker,
        }, room=room.id)

    def next_turn_target(self, room):
        """计算下一位行动者并消费一次性跳过标记。"""
        current_index = room.attack_order.index(room.current_attacker)
        next_index = (current_index + 1) % len(room.attack_order)
        next_attacker = room.attack_order[next_index]
        if room.skip_opponent_turn == next_attacker:
            room.skip_opponent_turn = None
            next_index = (next_index + 1) % len(room.attack_order)
            next_attacker = room.attack_order[next_index]
        if room.skip_next_turn == next_attacker:
            room.skip_next_turn = None
            next_index = (next_index + 1) % len(room.attack_order)
            next_attacker = room.attack_order[next_index]
        skip_stages = room.skip_opponent_stages == next_attacker
        if skip_stages:
            room.skip_opponent_stages = None
            next_index = (next_index + 1) % len(room.attack_order)
            next_attacker = room.attack_order[next_index]
        return next_index, next_attacker, skip_stages

    def continue_turn(self, room, next_attacker):
        """完成同一大回合内的普通换手。"""
        room.current_attacker = next_attacker
        room.current_phase = 'preparation'
        room.players[next_attacker].damage_dealt_this_turn = 0
        self._recalc_attacks(room)
        self._settle_wuyou(room)
        self._settle_bingliang(room)
        self._prune_flags(room, self._keep_across_turn)
        self._emit_active_effects(room)
        self._emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker,
        }, room=room.id)
        self._emit('turn_change', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining,
            'phase': room.current_phase,
        }, room=room.id)
        self._run_ai_turn(room)

    def begin_new_round(self, room):
        """切入新大回合的猜拳阶段，清理上一大回合的流程状态。"""
        room.state = 'rock_paper_scissors'
        room.rps_choices = {}
        room.rps_processed = False
        room.skip_opponent_turn = None
        room.skip_next_turn = None
        room.skip_opponent_stages = None
        room.current_phase = 'preparation'

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
