"""AI 手牌选择策略。"""


def choose_safe_card(room, player_id, *, safe_cards, can_play):
    player = room.players.get(player_id)
    if not player or not player.magic_hand:
        return None
    candidates = [
        (int(card.speed), index)
        for index, card in enumerate(player.magic_hand)
        if card.name in safe_cards and can_play(room, player_id, card)
    ]
    return min(candidates)[1] if candidates else None


def choose_card(room, player_id, *, difficulty, is_master, safe_cards,
                can_play, master_pick, cards_played=0):
    if difficulty == 'easy':
        return None, {}
    if not is_master:
        return choose_safe_card(
            room, player_id, safe_cards=safe_cards, can_play=can_play), {}
    return master_pick(room, player_id, cards_played)
