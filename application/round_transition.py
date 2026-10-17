"""新大回合开始前的效果准备。"""


class RoundTransition:
    def __init__(self, *, restore_shenwei, recall_lanyu):
        self._restore_shenwei = restore_shenwei
        self._recall_lanyu = recall_lanyu

    def prepare(self, room, room_id):
        """执行进入新大回合前的效果准备，返回是否已经结束对局。"""
        for player in room.players.values():
            player.magic_blocked = None
        self._restore_shenwei(room, room.round)
        return self._recall_lanyu(room, room_id)
