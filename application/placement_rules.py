"""布船可用格判定。

该模块只保存棋盘放置规则；房间、Socket 和卡牌流程仍由服务端适配。
"""


class PlacementRules:
    """通过注入运行时查询，统一服务端与前端投影使用的放置口径。"""

    def __init__(self, *, opponent_of, cell_in_shenwei_hole,
                 own_occupied_cells, shenwei_holes):
        self._opponent_of = opponent_of
        self._cell_in_shenwei_hole = cell_in_shenwei_hole
        self._own_occupied_cells = own_occupied_cells
        self._shenwei_holes = shenwei_holes

    def error(self, room, player_id, x, y, allow_cells=None,
              ignore_sunken=False):
        if not (0 <= x <= 5 and 0 <= y <= 5):
            return '坐标超出棋盘范围'
        allow = allow_cells or set()
        opponent_id = self._opponent_of(room, player_id)
        if opponent_id:
            attacks = [(a.x, a.y) for a in room.players[opponent_id].attacks]
            if (x, y) in attacks and (x, y) not in allow:
                return '该位置已被对方攻击过，不能放置'
        if self._cell_in_shenwei_hole(room, player_id, x, y):
            return '该区域已被神威！扣掉，不能放置'
        owner = room.players[player_id]
        if (x, y) in self._own_occupied_cells(owner,
                                               ignore_sunken=ignore_sunken):
            return '该位置已被己方战舰占用'
        return None

    def blocked_cells(self, room, player_id, ignore_sunken=False):
        blocked = set()
        opponent_id = self._opponent_of(room, player_id)
        if opponent_id:
            blocked.update((a.x, a.y)
                           for a in room.players[opponent_id].attacks)
        blocked |= self._own_occupied_cells(room.players[player_id],
                                            ignore_sunken=ignore_sunken)
        for hole in self._shenwei_holes(room):
            if hole['player'] == player_id:
                for x in range(hole['x1'], hole['x2'] + 1):
                    for y in range(hole['y1'], hole['y2'] + 1):
                        blocked.add((x, y))
        return [{'x': x, 'y': y} for x, y in sorted(blocked)]
