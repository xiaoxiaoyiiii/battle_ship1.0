"""阶段转换优先权询问窗口。"""


class PriorityPrompt:
    def __init__(self, *, opponent_of, should_ask, speed3_cards,
                 action_text, seconds, emit, schedule_timeout):
        self._opponent_of = opponent_of
        self._should_ask = should_ask
        self._speed3_cards = speed3_cards
        self._action_text = action_text
        self._seconds = seconds
        self._emit = emit
        self._schedule_timeout = schedule_timeout

    def ask(self, room, actor_id, action):
        responder_id = self._opponent_of(room, actor_id)
        if not self._should_ask(room, actor_id, responder_id):
            return False
        room.priority_token += 1
        token = room.priority_token
        cards = self._speed3_cards(room, responder_id)
        countdown = self._seconds()
        room.priority_pending = {
            'actor': actor_id,
            'responder': responder_id,
            'action': action,
            'speed3_cards': cards,
            'countdown': countdown,
        }
        self._emit('priority_request', {
            'action': action,
            'actor': actor_id,
            'speed3_cards': cards,
            'countdown': countdown,
        }, to=room.players[responder_id].sid)
        self._emit('priority_waiting', {
            'action': action,
            'action_text': self._action_text.get(action, '阶段转换'),
            'countdown': countdown,
        }, to=room.players[actor_id].sid)
        self._schedule_timeout(room.id, token)
        return True
