"""AI 房间运行时的基础状态与棋盘初始化。"""


def player_id(room):
    for pid in room.players:
        if pid.startswith('ai-'):
            return pid
    return None


def is_master(room, player_id=None):
    by_player = getattr(room, 'ai_difficulty_by_player', None)
    if player_id and isinstance(by_player, dict) and player_id in by_player:
        return by_player[player_id] == 'master'
    return getattr(room, 'ai_difficulty', 'normal') == 'master'


def difficulty(room, player_id):
    by_player = getattr(room, 'ai_difficulty_by_player', None)
    if player_id and isinstance(by_player, dict) and player_id in by_player:
        return str(by_player[player_id] or 'normal')
    return str(getattr(room, 'ai_difficulty', 'normal') or 'normal')


def runtime(room, default):
    return getattr(room, 'ai_runtime', None) or default


