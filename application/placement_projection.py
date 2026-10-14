"""把放置待办投影为客户端 placement_request 事件。"""


class PlacementProjection:
    def __init__(self, *, blocked_cells, cell_xy, emit):
        self._blocked_cells = blocked_cells
        self._cell_xy = cell_xy
        self._emit = emit

    def emit_request(self, room, player_id):
        pending = room.magic_temp_data.get('pending_placement')
        if not pending:
            return
        payload = {
            'kind': pending['kind'],
            'remaining': pending['remaining'],
            'total': pending['total'],
            'placed': pending['placed'],
            'blocked': self._blocked_cells(room, player_id),
        }
        kind = pending['kind']
        if kind == 'last_stand':
            payload['allowed'] = room.game_effects.get('last_stand_cells') or []
            allowed = {self._cell_xy(cell) for cell in payload['allowed']}
            allowed.discard(None)
            payload['blocked'] = [
                cell for cell in payload['blocked']
                if (cell['x'], cell['y']) not in allowed
            ]
        elif kind == 'shenji_redeploy':
            allowed = {
                (int(cell[0]), int(cell[1]))
                for cell in (room.game_effects.get('shenji_redeploy_cells') or [])
            }
            payload['blocked'] = self._blocked_cells(
                room, player_id, ignore_sunken=True)
            payload['blocked'] = [
                cell for cell in payload['blocked']
                if (cell['x'], cell['y']) not in allowed
            ]
            payload['message'] = (
                '预言成功：请选择这艘战舰重新部署的位置（原位置或对方未打过的格子）'
            )
        elif kind == 'lanyu':
            payload['message'] = (
                '滥竽充数：请选择补充战舰的部署位置（未被攻击过的空格，大回合结束时收回）'
            )
        self._emit('placement_request', payload,
                   to=room.players[player_id].sid)
