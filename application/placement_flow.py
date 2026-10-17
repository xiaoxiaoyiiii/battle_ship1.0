"""布船待办的创建与神机妙算重新部署流程。"""


class PlacementFlow:
    """维护放置待办，具体 Socket 投影由调用方注入。"""

    def __init__(self, *, emit_request):
        self._emit_request = emit_request

    def start(self, room, caster_id, kind, count):
        room.magic_temp_data['pending_placement'] = {
            'caster': caster_id,
            'kind': kind,
            'remaining': count,
            'total': count,
            'placed': 0,
        }
        self._emit_request(room, caster_id)

    def begin_shenji_redeploy(self, room, player_id, count,
                              already_sunken_ids=None):
        player = room.players.get(player_id)
        if player is None:
            return 0
        sunken = list(getattr(player, 'sunken_ships', []) or [])
        if already_sunken_ids is None:
            fresh = sunken[-int(count):] if count else []
        else:
            before = set(already_sunken_ids)
            fresh = [ship for ship in sunken if id(ship) not in before]
        n = min(int(count), len(fresh))
        if n <= 0:
            return 0
        chosen = fresh[:n]
        original_cells = []
        for ship in chosen:
            for pos in ship.positions:
                original_cells.append([pos.x, pos.y])
        room.game_effects['shenji_redeploy_cells'] = original_cells
        room.game_effects['shenji_redeploy_ships'] = chosen
        self.start(room, player_id, 'shenji_redeploy', n)
        return n
