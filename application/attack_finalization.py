"""攻击动作完成后的记录、广播和终局处理。"""


class AttackFinalization:
    def __init__(self, *, attack_result, position, compare_shadow,
                 log_name, add_game_log, emit, finish_game, trigger_wuxian,
                 warn_shadow):
        self._attack_result = attack_result
        self._position = position
        self._compare_shadow = compare_shadow
        self._log_name = log_name
        self._add_game_log = add_game_log
        self._emit = emit
        self._finish_game = finish_game
        self._trigger_wuxian = trigger_wuxian
        self._warn_shadow = warn_shadow

    def finalize(self, room, room_id, attacker_id, defender_id, x, y,
                 hit, ship_sunk, shield_blocked, shadow_resolution=None):
        room.last_attack = {
            'attacker': attacker_id, 'x': x, 'y': y,
            'hit': hit, 'ship_sunk': ship_sunk, 'round': room.round,
        }
        room.attacks_remaining = max(0, room.attacks_remaining - 1)
        if shadow_resolution is not None:
            shadow_diff = self._compare_shadow(
                shadow_resolution,
                hit=hit,
                ship_sunk=ship_sunk,
                shield_blocked=shield_blocked,
                remaining_attacks=room.attacks_remaining,
                defender_remaining_ships=room.players[defender_id].remaining_ships,
            )
            if shadow_diff:
                self._warn_shadow(room_id, attacker_id, x, y, shadow_diff)
        if not shield_blocked:
            room.players[attacker_id].attacks.append(
                self._position(x, y, hit=hit, ship_sunk=ship_sunk))
        result = self._attack_result(
            attacker=attacker_id, x=x, y=y, hit=hit,
            ship_sunk=ship_sunk, remaining_attacks=room.attacks_remaining,
            attacker_remaining_ships=room.players[attacker_id].remaining_ships,
            defender_remaining_ships=room.players[defender_id].remaining_ships,
            shield_blocked=shield_blocked,
        )
        note = '，被护盾挡下' if shield_blocked else ('，击沉战舰' if ship_sunk else '')
        self._add_game_log(
            room,
            f"第{room.round}回合 · {self._log_name(room, attacker_id)} 攻击 ({x},{y}) — "
            f"{'命中' if hit else '未命中'}{note}",
            'attack', {
                'attacker': attacker_id,
                'target': {'x': x, 'y': y},
                'hit': hit, 'ship_sunk': ship_sunk,
                'shield_blocked': shield_blocked,
            },
        )
        self._emit('attack_result', result, room=room_id)
        defender = room.players[defender_id]
        if defender.remaining_ships <= 0 and len(defender.ships) > 0:
            self._finish_game(room, room_id, attacker_id, defender_id)
            return {'game_over': True}
        if room.attacks_remaining == 0:
            self._trigger_wuxian(room, attacker_id)
            self._emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining,
            }, room=room_id)
        return {'game_over': False}
