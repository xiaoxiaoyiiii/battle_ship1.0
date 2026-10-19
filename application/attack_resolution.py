"""攻击命中后的战舰状态结算。"""


class AttackResolution:
    def __init__(self, *, position, emit, emit_player_ships,
                 ship_sunk_effects, check_last_chance, emit_ships_updated,
                 apply_damage_buffs, finish_game, log_name):
        self._position = position
        self._emit = emit
        self._emit_player_ships = emit_player_ships
        self._ship_sunk_effects = ship_sunk_effects
        self._check_last_chance = check_last_chance
        self._emit_ships_updated = emit_ships_updated
        self._apply_damage_buffs = apply_damage_buffs
        self._finish_game = finish_game
        self._log_name = log_name

    @staticmethod
    def _result(*, game_over, hit, ship_sunk, shield_blocked):
        return {
            'game_over': game_over,
            'hit': hit,
            'ship_sunk': ship_sunk,
            'shield_blocked': shield_blocked,
        }

    def resolve(self, room, room_id, attacker_id, defender_id, x, y):
        hit = False
        ship_sunk = False
        shield_blocked = False
        attacker = room.players[attacker_id]
        defender = room.players[defender_id]
        defender_ships = defender.ships
        forced = attacker.effect_flags.forced_kill > 0
        hit_position = self._position(x, y)
        target = hit_position
        for ship in defender_ships:
            if target not in ship.positions:
                continue
            hit = True
            if 'holy_heart' in room.game_effects and not ship.invincible:
                room.game_effects['holy_heart']['no_damage'] = False
            if forced:
                ship.hits.append(hit_position)
                ship_sunk = True
                self._ship_sunk_effects(room, room_id, attacker_id, defender_id, ship)
            elif ship.invincible:
                ship_sunk = False
            elif ship.shield:
                shield_blocked = True
                ship.shield = False
                self._emit('shield_absorbed', {
                    'player': defender_id,
                    'positions': [{'x': p.x, 'y': p.y} for p in ship.positions],
                }, room=room_id)
                self._emit_player_ships(room, defender_id)
            else:
                ship.hits.append(hit_position)
                ship_sunk = len(ship.hits) == len(ship.positions)
                if ship_sunk:
                    self._ship_sunk_effects(room, room_id, attacker_id, defender_id, ship)

            damaged = forced or (not ship.invincible and not ship.shield)
            if damaged:
                if self._check_last_chance(room, attacker_id, defender_id):
                    return self._result(
                        game_over=True, hit=hit, ship_sunk=ship_sunk,
                        shield_blocked=shield_blocked)
                self._emit_ships_updated(room)
                self._apply_damage_buffs(room, room_id, attacker_id)
                if (room.players[attacker_id].effect_flags.last_stand_win
                        and (ship_sunk or forced)):
                    self._finish_game(
                        room, room_id, attacker_id, defender_id,
                        f'第{room.round}回合 · {self._log_name(room, attacker_id)} 绝处逢生击杀敌舰获胜')
                    return self._result(
                        game_over=True, hit=hit, ship_sunk=ship_sunk,
                        shield_blocked=shield_blocked)
            break
        return self._result(
            game_over=False, hit=hit, ship_sunk=ship_sunk,
            shield_blocked=shield_blocked)
