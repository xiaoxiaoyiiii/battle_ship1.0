"""连锁响应窗口的超时推进。"""


class ChainTimeout:
    def __init__(
        self,
        *,
        sleep,
        get_room,
        resolve_chain,
        advance_window,
        opponent_of,
        response_seconds,
        start_background_task,
    ):
        self._sleep = sleep
        self._get_room = get_room
        self._resolve_chain = resolve_chain
        self._advance_window = advance_window
        self._opponent_of = opponent_of
        self._response_seconds = response_seconds
        self._start_background_task = start_background_task

    def schedule(self, room_id, token):
        def _timeout():
            self._sleep(self._response_seconds())
            room = self._get_room(room_id)
            if room and room.chain_waiting and room.chain_timer == token:
                window_player = room.chain_window
                room.chain_waiting = False
                room.chain_window = None
                room.chain_passes += 1
                if room.chain_passes >= 2 or window_player is None:
                    self._resolve_chain(room)
                else:
                    self._advance_window(
                        room,
                        self._opponent_of(room, window_player),
                        display_delay=False,
                    )

        self._start_background_task(_timeout)
