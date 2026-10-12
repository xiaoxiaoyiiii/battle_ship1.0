"""从已净化的公开事实构造观战快照。"""
from __future__ import annotations


def project_snapshot(*, room_public, sides, seat_labels, game_logs, chain,
                     effects, spectators, spectator_limit):
    """只接受公开字段；棋盘攻击方向由座位攻击记录转置得到。"""
    visible_sides = {label: dict(side) for label, side in sides.items()}
    board_attacks = {
        label: [dict(cell) for cell in visible_sides.get(
            'p2' if label == 'p1' else 'p1', {}).get('attacks', [])]
        for label in visible_sides
    }
    return {
        **room_public,
        'sides': visible_sides,
        'seat_labels': dict(seat_labels),
        'board_attacks': board_attacks,
        'game_logs': list(game_logs),
        'chain': dict(chain),
        'shenwei_holes': [dict(h) for h in effects.get('shenwei_holes', [])],
        'frozen_area': dict(effects.get('frozen_area') or {}) or None,
        'last_stand_cells': [
            {'x': x, 'y': y} for x, y in effects.get('last_stand_cells', [])
        ],
        'last_stand_owner': effects.get('last_stand_owner'),
        'spectator_count': len(spectators),
        'spectator_limit': spectator_limit,
        'spectators': [
            {'name': info.get('name'), 'joined_at': info.get('joined_at')}
            for info in spectators
        ],
    }
