"""困难 AI 的连锁响应策略。"""


class ChainAIResponse:
    def __init__(self, *, sleep, get_room, can_negate_top, respond, report_error):
        self._sleep = sleep
        self._get_room = get_room
        self._can_negate_top = can_negate_top
        self._respond = respond
        self._report_error = report_error

    def respond(self, room_id, token):
        try:
            self._sleep(0.8)
            room = self._get_room(room_id)
            if not room or room.state == 'game_over':
                return
            if not room.chain_waiting or room.chain_timer != token:
                return
            ai_id = room.chain_window
            if not ai_id or not ai_id.startswith('ai-'):
                return
            player = room.players.get(ai_id)
            if not player:
                return
            card = next((c for c in player.magic_hand if c.name == '失灵！'), None)
            if card is None or not self._can_negate_top(room, ai_id):
                self._respond({'room_id': room_id, 'player_id': ai_id, 'chain': False})
                return
            response = self._respond({
                'room_id': room_id,
                'player_id': ai_id,
                'chain': True,
                'card': {'name': card.name, 'speed': card.speed, 'type': card.type},
                'targets': [],
            })
            if not (response and response.get('status') == 'success'):
                self._respond({'room_id': room_id, 'player_id': ai_id, 'chain': False})
        except Exception as exc:
            self._report_error(exc)
