"""大师 AI 单次出牌动作。"""

def play_one(room_id, ai_id, played, *, get_room, card_limit, choose_card, use_card, log) -> bool:
    """尝试出一张牌。返回 True = **打出并成功结算**（调用方把预算 +1）。

    ⚠️ 用 `use_card` 的返回值判成败；失败（被拒）也算"这次机会用掉了"，
    但**不计入预算** —— 被拒说明这张卡当时打不出去，`_master_card_readiness`
    漏判了，不该因此白扣一次出牌额度（正是要消灭的失败模式）。
    """
    room = get_room(room_id)
    if not room or room.state == 'game_over':
        return False
    if played >= int(card_limit):
        return False
    idx, targets = choose_card(room, ai_id, played)
    if idx is None:
        return False
    hand = room.players[ai_id].magic_hand
    if not isinstance(idx, int) or not (0 <= idx < len(hand)):
        return False
    card = hand[idx]
    resp = use_card({
        'room_id': room_id, 'player_id': ai_id,
        'card': {'name': card.name, 'speed': card.speed, 'type': card.type,
                 'description': getattr(card, 'description', '')},
        'targets': targets or {},
    })
    if resp and resp.get('status') == 'success':
        return True
    # 试算漏判：记一笔（含拒绝原因），便于离线统计哪张卡的闸门还缺
    room = get_room(room_id)
    if room is not None:
        log(room, f'大师 AI 出牌被拒（{card.name}）：'
                           f'{(resp or {}).get("message", "")}', 'magic')
    return False


def maybe_play_magic(room, player_id, *, choose_card, use_card):
    index, targets = choose_card(room, player_id)
    if index is None:
        return False
    card = room.players[player_id].magic_hand[index]
    response = use_card({
        'room_id': room.id,
        'player_id': player_id,
        'card': {'name': card.name, 'speed': card.speed, 'type': card.type,
                 'description': getattr(card, 'description', '')},
        'targets': targets or {},
    })
    return bool(response and response.get('status') == 'success')

