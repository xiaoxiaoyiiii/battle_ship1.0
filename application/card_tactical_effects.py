"""持续状态类魔法卡：守株待兔、卧薪尝胆、神机妙算。"""


class TacticalEffects:
    def __init__(self, *, opponent_of, alive_ships, request_ship_pick,
                 emit_player_ships, emit, add_game_log, log_name,
                 open_prediction, apply_prediction):
        self._opponent_of = opponent_of
        self._alive_ships = alive_ships
        self._request_ship_pick = request_ship_pick
        self._emit_player_ships = emit_player_ships
        self._emit = emit
        self._add_game_log = add_game_log
        self._log_name = log_name
        self._open_prediction = open_prediction
        self._apply_prediction = apply_prediction

    def apply(self, room, caster_id, card, result, *, caster):
        if card.name == '守株待兔':
            return self._trap(room, caster_id, result, caster)
        if card.name == '卧薪尝胆':
            return self._shield(room, caster_id, result, caster)
        if card.name == '神机妙算':
            if 'prediction' not in room.magic_temp_data:
                self._open_prediction(room, caster_id, result)
            else:
                try:
                    value = max(0, min(6, int(room.magic_temp_data.get('prediction'))))
                except Exception:
                    value = 0
                self._apply_prediction(room, caster_id, value, result)
            return True
        return False

    def _trap(self, room, caster_id, result, caster):
        if caster.remaining_ships == 0:
            result['success'] = False
            result['message'] = '没有战舰可设置陷阱'
            return True
        picked = self._request_ship_pick(
            room, caster_id, 'trap_setup',
            '守株待兔：请点选一艘自己的战舰设置陷阱')
        if picked is not None:
            picked.trap = True
            self._add_game_log(
                room,
                f'第{room.round}回合 · {self._log_name(room, caster_id)} 的【守株待兔】'
                '为一艘战舰设置陷阱',
                'magic', {'caster': caster_id, 'card': '守株待兔'})
            self._emit('trap_set', {
                'player': caster_id,
                'positions': [{'x': p.x, 'y': p.y} for p in picked.positions],
            }, room=room.id)
            result['message'] = '已为一艘战舰设置陷阱（本回合该船被击沉时对方需牺牲两艘）'
        else:
            result['message'] = '请选择要设置陷阱的战舰'
        return True

    def _shield(self, room, caster_id, result, caster):
        opponent_id = self._opponent_of(room, caster_id)
        if opponent_id and caster.remaining_ships >= room.players[opponent_id].remaining_ships:
            result['success'] = False
            result['message'] = '自己的船数不小于对方，卧薪尝胆无法发动'
            return True
        alive = self._alive_ships(caster)
        if not alive:
            result['success'] = False
            result['message'] = '没有战舰可添加护盾'
            return True
        for ship in alive:
            ship.shield = True
        self._emit_player_ships(room, caster_id)
        self._emit('shields_added', {
            'player': caster_id, 'count': len(alive),
        }, room=room.id)
        self._add_game_log(
            room,
            f'第{room.round}回合 · {self._log_name(room, caster_id)} 的【卧薪尝胆】'
            f'为{len(alive)}艘战舰添加护盾',
            'magic', {'caster': caster_id, 'card': '卧薪尝胆', 'count': len(alive)})
        result['message'] = f'已为{len(alive)}艘战舰添加护盾'
        return True
