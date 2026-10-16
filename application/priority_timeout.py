"""阶段转换优先权询问的超时调度。"""


class PriorityTimeout:
    def __init__(self, *, sleep, get_room, resolve, seconds, start_background_task):
        self._sleep = sleep
        self._get_room = get_room
        self._resolve = resolve
        self._seconds = seconds
        self._start_background_task = start_background_task

    def schedule(self, room_id, token):
        def _timeout():
            self._sleep(self._seconds())
            room = self._get_room(room_id)
            if room and room.priority_pending and room.priority_token == token:
                self._resolve(room, respond=False)

        self._start_background_task(_timeout)
