"""连锁响应资格判定，不负责 Socket 窗口或连锁结算。"""


class ChainPolicy:
    def __init__(self, *, speed3_cards, ai_can_negate_top):
        self._speed3_cards = speed3_cards
        self._ai_can_negate_top = ai_can_negate_top

    def can_respond(self, room, player_id):
        if not player_id:
            return False
        player = room.players.get(player_id)
        if not player or player.magic_blocked:
            return False
        if player.effect_flags.last_stand:
            return False
        if player_id.startswith('ai-'):
            if getattr(room, 'ai_difficulty', 'normal') != 'hard':
                return False
            if not any(c.name == '失灵！' for c in player.magic_hand):
                return False
            return self._ai_can_negate_top(room, player_id)
        return bool(self._speed3_cards(room, player_id))
