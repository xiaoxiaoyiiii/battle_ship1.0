"""掉线宽限到期后的对局状态决策。"""


class DisconnectResolution:
    def __init__(self, *, sleep, now, get_room, emit, drop_room, start_timeout,
                 finalize_match, game_over_payload, start_cleanup, grace):
        self._sleep = sleep
        self._now = now
        self._get_room = get_room
        self._emit = emit
        self._drop_room = drop_room
        self._finalize_match = finalize_match
        self._game_over_payload = game_over_payload
        self._start_cleanup = start_cleanup
        self._start_timeout = start_timeout
        self._grace = grace

    def start_grace(self, room_id, player_id):
        self._sleep(0.2)
        room = self._get_room(room_id)
        if not room or room.state == 'game_over' or player_id in room.disconnected:
            return
        room.disconnect_seq += 1
        deadline = self._now() + self._grace()
        room.disconnected[player_id] = {
            'deadline': deadline,
            'token': room.disconnect_seq,
        }
        for pid, player in list(room.players.items()):
            if pid != player_id:
                self._emit('opponent_disconnected', {
                    'player_id': player_id,
                    'seconds': self._grace(),
                    'deadline': deadline,
                }, to=player.sid)
        self._start_timeout(room_id, player_id, room.disconnect_seq)

    def resolve(self, room_id, player_id, token):
        self._sleep(self._grace())
        room = self._get_room(room_id)
        if not room:
            return
        entry = room.disconnected.get(player_id)
        if not entry or entry.get('token') != token:
            return
        room.disconnected.pop(player_id, None)
        other = next((p for p in room.players if p != player_id), None)
        cancel = (
            getattr(room, 'is_ai_room', False)
            or room.state in ('placing_ships', 'rock_paper_scissors')
            or other is None
            or other in room.disconnected
            or room.state == 'game_over'
        )
        if cancel:
            self._emit('game_canceled', {
                'reason': 'opponent_disconnected',
                'message': '对局已取消（对手掉线）',
                'room_id': room_id,
            }, room=room_id)
            self._drop_room(room_id, '对手掉线/未开局，取消对局')
            return
        room.state = 'game_over'
        room.winner = other
        room.game_over_reason = 'opponent_disconnected'
        self._finalize_match(room, other, player_id)
        self._emit('game_over', self._game_over_payload(
            room, {'winner': other, 'reason': 'opponent_disconnected'}
        ), room=room_id)
        self._start_cleanup(room_id, 120)
