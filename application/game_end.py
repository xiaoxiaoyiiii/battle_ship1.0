"""对局终局收口和特殊判负。"""


class GameEnd:
    def __init__(self, *, add_log, finalize_match, emit, log_name,
                 clear_ship_picks, clear_pending):
        self._add_log = add_log
        self._finalize_match = finalize_match
        self._emit = emit
        self._log_name = log_name
        self._clear_ship_picks = clear_ship_picks
        self._clear_pending = clear_pending

    @staticmethod
    def payload(room, extra=None):
        payload = dict(extra or {})
        match_id = getattr(room, 'match_id', None)
        if match_id:
            payload['match_id'] = match_id
        return payload

    def finish_win(self, room, room_id, winner_id, loser_id, log_message=None):
        if room.state == 'game_over':
            return
        room.state = 'game_over'
        room.winner = winner_id
        self._add_log(
            room,
            log_message or f'第{room.round}回合 · {self._log_name(room, winner_id)} 获胜，游戏结束',
            'result', {'winner': winner_id, 'loser': loser_id},
        )
        self._finalize_match(room, winner_id, loser_id)
        self._emit('game_over', self.payload(room, {'winner': winner_id}), room=room_id)

    def check_last_chance(self, room, attacker_id, defender_id):
        effect = room.game_effects.get('last_chance')
        if not (effect and effect.get('caster') == defender_id
                and effect.get('round', room.round) == room.round):
            return False
        self.finish_win(
            room, room.id, attacker_id, defender_id,
            f'第{room.round}回合 · {self._log_name(room, defender_id)} 触发回光返照失败并判负',
        )
        return True

    def finish_reason(self, room, winner_id, loser_id, reason):
        room.state = 'game_over'
        room.winner = winner_id
        self._clear_ship_picks(room)
        self._clear_pending(room)
        self._add_log(
            room, f'第{room.round}回合 · {self._log_name(room, winner_id)} 获胜，游戏结束',
            'result', {'winner': winner_id, 'loser': loser_id, 'reason': reason},
        )
        self._finalize_match(room, winner_id, loser_id)
        self._emit('game_over', self.payload(
            room, {'winner': winner_id, 'reason': reason}), room=room.id)
