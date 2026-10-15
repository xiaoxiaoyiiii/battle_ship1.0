"""临时战舰类魔法卡效果（当前为滥竽充数）。"""


class TemporaryShipEffects:
    CARD_NAME = '滥竽充数'

    def __init__(self, *, requirement_reason, blocked_cells, start_placement,
                 emit, add_game_log, log_name, is_ship_alive,
                 emit_player_ships, emit_ships_updated, opponent_of,
                 finish_game_win, rank_payload):
        self._requirement_reason = requirement_reason
        self._blocked_cells = blocked_cells
        self._start_placement = start_placement
        self._emit = emit
        self._add_game_log = add_game_log
        self._log_name = log_name
        self._is_ship_alive = is_ship_alive
        self._emit_player_ships = emit_player_ships
        self._emit_ships_updated = emit_ships_updated
        self._opponent_of = opponent_of
        self._finish_game_win = finish_game_win
        self._rank_payload = rank_payload

    def apply(self, room, caster_id, card, result):
        if card.name != self.CARD_NAME:
            return False, False
        reason = self._requirement_reason(room, caster_id, card)
        if reason:
            result.success = False
            result.message = reason
            return True, True
        caster = room.players[caster_id]
        max_ships = int(getattr(caster, 'max_ships', 6) or 6)
        needed = max_ships - caster.remaining_ships
        available = 36 - len(self._blocked_cells(room, caster_id))
        count = min(needed, available)
        if count <= 0:
            result.success = False
            result.message = '没有可放置的格子，滥竽充数无法生效'
            return True, True
        lanyu = room.game_effects.setdefault('lanyu_temp_ships', {})
        lanyu.setdefault(caster_id, [])
        self._start_placement(room, caster_id, 'lanyu', count)
        result.temp_data_id = 'lanyu_placement'
        result.message = f'请选择{count}艘补充战舰的部署位置（大回合结束时收回）'
        self._add_game_log(
            room,
            f'第{room.round}回合 · {self._log_name(room, caster_id)} 的【滥竽充数】'
            f'补充{count}艘战舰（大回合结束时收回）',
            'magic', {'caster': caster_id, 'card': self.CARD_NAME, 'count': count})
        return True, False

    def recall(self, room, room_id):
        """回合末收回存活临时船；不把收回记录为沉没。"""
        lanyu = room.game_effects.pop('lanyu_temp_ships', None)
        if not lanyu:
            return False
        changed = {}
        for player_id, ship_list in lanyu.items():
            if player_id not in room.players:
                continue
            player = room.players[player_id]
            removed = 0
            for ship in ship_list:
                if ship not in player.ships or not self._is_ship_alive(player, ship):
                    continue
                player.ships.remove(ship)
                player.remaining_ships -= 1
                removed += 1
            if removed:
                changed[player_id] = removed
                self._emit_player_ships(room, player_id)
        if not changed:
            return False
        self._emit_ships_updated(room)
        for pid, count in changed.items():
            self._emit('lanyu_recalled', {'player': pid, 'count': count}, room=room_id)
            self._add_game_log(
                room,
                f'第{room.round}回合 · {self._log_name(room, pid)} 的【滥竽充数】'
                f'临时战舰已收回({count}艘)',
                'magic', {'player': pid, 'card': self.CARD_NAME, 'count': count})
        for pid in changed:
            player = room.players[pid]
            if player.remaining_ships <= 0 and player.ships and room.state != 'game_over':
                opponent_id = self._opponent_of(room, pid)
                if opponent_id and opponent_id in room.players:
                    self._finish_game_win(
                        room, room_id, opponent_id, pid,
                        f'第{room.round}回合 · {self._log_name(room, pid)} 的'
                        '临时战舰已全部收回，无战舰可用')
                    self._emit('game_state', {
                        'state': 'game_over', 'winner': opponent_id,
                        'reason': '滥竽充数临时战舰已收回，无战舰可用',
                        **self._rank_payload(room),
                    }, room=room_id)
                    return True
        return False
