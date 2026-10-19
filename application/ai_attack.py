"""AI 攻击目标选择策略。"""


def choose_attack(*, room, player_id, rng, candidates, is_master, informed_choice):
    """从可攻击格中选择目标；大师优先使用已探明的敌船位置。"""
    if not candidates:
        return None
    if is_master:
        chosen = informed_choice(room, player_id, rng=rng)
        if chosen:
            return chosen
    return rng.choice(candidates)
