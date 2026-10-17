"""阶段转换优先权的门禁和状态清理。"""


class PriorityGate:
    def __init__(self, *, has_context, is_ai_room, is_disconnected,
                 decline_enabled, has_chain, emit):
        self._has_context = has_context
        self._is_ai_room = is_ai_room
        self._is_disconnected = is_disconnected
        self._decline_enabled = decline_enabled
        self._has_chain = has_chain
        self._emit = emit

    def should_ask(self, room, actor_id, responder_id):
        if not self._has_context() or self._is_ai_room(room):
            return False
        if not responder_id or responder_id not in room.players:
            return False
        if room.state == 'game_over' or self._is_disconnected(room, responder_id):
            return False
        if self._decline_enabled(room, responder_id) or self._has_chain(room):
            return False
        return not getattr(room, 'priority_pending', None)

    def clear(self, room):
        pending = getattr(room, 'priority_pending', None)
        actor_id = pending.get('actor') if pending else None
        room.priority_pending = None
        room.priority_token += 1
        if actor_id and actor_id in room.players:
            sid = getattr(room.players[actor_id], 'sid', None)
            if sid:
                self._emit('priority_waiting_end', {
                    'action': pending.get('action'),
                }, to=sid)
