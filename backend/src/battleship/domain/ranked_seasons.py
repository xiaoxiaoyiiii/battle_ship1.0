"""排位季的纯规则。段位索引沿用 Ban 与资料系统。"""
from .progression import ranks

MIN_GAMES = 10
CLAIM_SECONDS = 14 * 86400


def tier_index(points: int, is_admiral: bool = False) -> int:
    return 8 if is_admiral else ranks.points_tier_index(points)


def reset_points(points: int, is_admiral: bool, games: int) -> int:
    if games < MIN_GAMES:
        return 0
    tier = tier_index(points, is_admiral)
    destination = tier if tier < 3 else tier - 1 if tier < 6 else 5
    return destination * len(ranks.SUBS) * ranks.SUB_POINTS


def season_rewards(peak_tier: int) -> list[dict]:
    group = min(2, max(0, peak_tier) // 3)
    cosmetics = [('card_bg', 'season_deep_1'), ('card_bg', 'abyssal_grid'), ('pointer', 'eclipse')]
    kind, reward_id = cosmetics[group]
    return [
        {'kind': 'tide_ash', 'amount': (1000, 2500, 5000)[group]},
        {'kind': kind, 'reward_id': reward_id},
        {'kind': 'title', 'reward_id': ('ranked_voyager', 'ranked_navigator', 'ranked_overlord')[group]},
    ]
