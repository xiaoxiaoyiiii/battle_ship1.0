"""AI 自动补摆棋盘的流程边界。"""


def is_ai_seat(player_id):
    return str(player_id or '').startswith('ai-')


def place_board(room, player_id, *, place_ships, handle_place):
    player = room.players.get(player_id)
    if player is None:
        return False
    count = int(getattr(player, 'max_ships', None) or 6)
    if len(getattr(player, 'ships', None) or []) >= count:
        return False
    place_ships(room, player_id)
    ships = [
        {'positions': [{'x': pos.x, 'y': pos.y} for pos in ship.positions],
         'hits': []}
        for ship in player.ships
    ]
    response = handle_place({'room_id': room.id, 'player_id': player_id,
                             'ships': ships})
    return bool(response and response.get('status') == 'success')


def seat_places_board_now(room, player_id, *, place_board):
    if not is_ai_seat(player_id) or room.players.get(player_id) is None:
        return False
    return place_board(room, player_id)
