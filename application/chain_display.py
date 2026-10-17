"""连锁结算前展示停留及其看门狗兜底。"""


class ChainDisplay:
    def __init__(self, *, delay, slack, monotonic, resolve, get_room,
                 get_rooms, start_background_task, sleep, log):
        self._delay = delay
        self._slack = slack
        self._monotonic = monotonic
        self._resolve = resolve
        self._get_room = get_room
        self._get_rooms = get_rooms
        self._start_background_task = start_background_task
        self._sleep = sleep
        self._log = log

    def clear(self, room):
        room.chain_display_token = None
        room.chain_display_deadline = None

    def still_current(self, room, token):
        return bool(room.chain and room.chain_timer == token
                    and getattr(room, 'state', None) != 'game_over'
                    and not room.chain_waiting)

    def finish(self, room, display_delay=True):
        if not display_delay or self._delay() <= 0:
            self._resolve(room)
            return False
        room.chain_timer += 1
        token = room.chain_timer
        room.chain_display_token = token
        room.chain_display_deadline = (
            self._monotonic() + self._delay() + self._slack())
        try:
            self._start_background_task(self._display_then_resolve, room.id, token)
        except Exception as exc:
            self.clear(room)
            self._log(f'连锁展示停留排不进后台任务，改为就地结算：{exc!r}')
            self._resolve(room)
            return False
        return True

    def _display_then_resolve(self, room_id, token):
        try:
            self._sleep(self._delay())
            room = self._get_room(room_id)
            if room is None or getattr(room, 'chain_display_token', None) != token:
                return
            self.clear(room)
            if self.still_current(room, token):
                self._resolve(room)
        except Exception as exc:
            self._log(f'连锁展示停留结算失败：{exc!r}')

    def sweep(self, now=None):
        now = self._monotonic() if now is None else now
        swept = []
        for room_id, room in list(self._get_rooms().items()):
            token = getattr(room, 'chain_display_token', None)
            deadline = getattr(room, 'chain_display_deadline', None)
            if token is None or deadline is None or now < deadline:
                continue
            if not self.still_current(room, token):
                self.clear(room)
                continue
            self.clear(room)
            self._log(f'连锁展示停留超时未结算，看门狗兜底结算：room={room_id} token={token}')
            self._resolve(room)
            swept.append(room_id)
        return swept
