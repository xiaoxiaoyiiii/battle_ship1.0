"""攻击额度的回合级硬性限制。"""


def attacks_forced_zero(room) -> bool:
    """判断当前攻击者是否被规则强制设为 0 次攻击。"""
    effects = getattr(room, 'game_effects', None)
    if not isinstance(effects, dict):
        return False
    try:
        round_no = int(room.round)
    except (TypeError, ValueError):
        return False
    try:
        if int(effects.get('zero_attacks_round') or -1) == round_no:
            return True
    except (TypeError, ValueError):
        pass
    try:
        entry = effects.get('zero_attacks_for')
        if isinstance(entry, dict) and int(entry.get('round') or -1) == round_no \
                and entry.get('player') == room.current_attacker:
            return True
    except (TypeError, ValueError):
        pass
    try:
        turn_entry = effects.get('zero_attacks_turn')
        if isinstance(turn_entry, dict) \
                and int(turn_entry.get(room.current_attacker) or -1) == round_no:
            return True
    except (TypeError, ValueError):
        pass
    return False
