"""魔法卡发动失败后的同实例退回规则。"""


def refund_card_to_hand(room, player_id, card, result, *, emit,
                        add_game_log, log_name):
    player = room.players.get(player_id)
    if player is None or card is None:
        return False
    if any(candidate is card for candidate in player.magic_hand):
        return False
    refunded = False
    for index, candidate in enumerate(room.magic_discard):
        if candidate is card:
            room.magic_discard.pop(index)
            player.magic_hand.append(card)
            refunded = True
            break
    if not refunded and getattr(card, 'type', None) == '场地' \
            and room.field_magic is not card:
        player.magic_hand.append(card)
        refunded = True
    if not refunded:
        return False
    reason = (getattr(result, 'message', '') or '不满足发动条件').strip()
    emit('message', {
        'text': f'{card.name}未发动：{reason}，卡牌已退回手牌',
    }, to=player.sid)
    add_game_log(
        room,
        f'{log_name(room, player_id)} 发动 {card.name} 失败：'
        f'{reason}（卡牌退回手牌）',
        'magic')
    return True
