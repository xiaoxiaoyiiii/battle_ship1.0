"""连锁响应窗口的状态推进。

该模块只负责在玩家之间推进响应窗口；SocketIO、超时调度和结算行为通过
回调注入，避免把 transport 依赖带进应用层，也保留服务端测试的替换能力。
"""


class ChainWindow:
    def __init__(
        self,
        *,
        can_respond,
        resolve_chain,
        finish_chain,
        opponent_of,
        speed3_cards,
        emit,
        schedule_timeout,
        start_background_task,
        ai_chain_respond,
        response_seconds,
    ):
        self._can_respond = can_respond
        self._resolve_chain = resolve_chain
        self._finish_chain = finish_chain
        self._opponent_of = opponent_of
        self._speed3_cards = speed3_cards
        self._emit = emit
        self._schedule_timeout = schedule_timeout
        self._start_background_task = start_background_task
        self._ai_chain_respond = ai_chain_respond
        self._response_seconds = response_seconds

    def advance(self, room, player_id, display_delay=True):
        """把响应窗口交给玩家，自动跳过无法响应者。"""
        while True:
            if not player_id or player_id not in room.players:
                return self._resolve_chain(room)
            if self._can_respond(room, player_id):
                room.chain_window = player_id
                room.chain_waiting = True
                room.chain_timer += 1
                self._emit(
                    'chain_request',
                    {
                        'card': room.chain[-1].card,
                        'caster': room.chain[-1].player_id,
                        'speed3_cards': self._speed3_cards(room, player_id),
                        'countdown': self._response_seconds(),
                    },
                    to=room.players[player_id].sid,
                )
                self._schedule_timeout(room.id, room.chain_timer)
                if player_id.startswith('ai-'):
                    self._start_background_task(
                        self._ai_chain_respond, room.id, room.chain_timer
                    )
                return
            room.chain_passes += 1
            if room.chain_passes >= 2:
                return self._finish_chain(room, display_delay=display_delay)
            player_id = self._opponent_of(room, player_id)
