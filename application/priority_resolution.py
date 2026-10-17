"""阶段转换优先权询问的结果处理。"""


class PriorityResolution:
    def __init__(self, *, clear, play_speed3, emit, continue_action):
        self._clear = clear
        self._play_speed3 = play_speed3
        self._emit = emit
        self._continue_action = continue_action

    def resolve(self, room, respond=False, card=None, targets=None):
        pending = getattr(room, 'priority_pending', None)
        if not pending:
            return
        actor_id = pending['actor']
        responder_id = pending['responder']
        action = pending['action']
        self._clear(room)
        if respond and card is not None:
            result = self._play_speed3(room, responder_id, card, targets or [])
            if result is not None and result.get('status') == 'error':
                self._emit(
                    'message',
                    {'text': result.get('message', '响应失败，已视为取消')},
                    to=room.players[responder_id].sid,
                )
                self._continue_action(room, actor_id, action)
                return
            if room.chain or room.chain_waiting:
                room.priority_continue = {'actor': actor_id, 'action': action}
                return
        self._continue_action(room, actor_id, action)
