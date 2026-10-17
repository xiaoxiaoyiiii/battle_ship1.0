"""优先权询问结束后的原操作续接。"""


class PriorityContinuation:
    def __init__(self, *, sleep, start_background_task, enter_battle, enter_end):
        self._sleep = sleep
        self._start_background_task = start_background_task
        self._enter_battle = enter_battle
        self._enter_end = enter_end

    def continue_action(self, room, actor_id, action):
        def run():
            self._sleep(0)
            if room.state == 'game_over':
                return
            data = {'room_id': room.id, 'player_id': actor_id}
            if action == 'enter_battle':
                self._enter_battle(data, _priority_confirmed=True)
            elif action == 'enter_end':
                self._enter_end(data, _priority_confirmed=True)

        try:
            self._start_background_task(run)
        except Exception:
            run()
