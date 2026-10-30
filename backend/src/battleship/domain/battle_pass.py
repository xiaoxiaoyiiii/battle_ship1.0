"""赛季通行证纯规则。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

SeasonState = Literal['upcoming', 'active', 'claim_only', 'closed']

@dataclass(frozen=True)
class SeasonConfig:
    id: str
    starts_at: int
    ends_at: int
    claim_ends_at: int
    level_cap: int
    total_xp: int
    rules_version: int

    def __post_init__(self) -> None:
        if not self.id or self.starts_at >= self.ends_at or self.ends_at >= self.claim_ends_at:
            raise ValueError('赛季时间范围无效')
        if self.level_cap < 1 or self.total_xp < 0 or self.rules_version < 1:
            raise ValueError('赛季规则参数无效')

def _bounded_xp(xp: int) -> int:
    try:
        return max(0, int(xp))
    except (TypeError, ValueError):
        return 0

def level_xp(level: int, config: SeasonConfig) -> int:
    level = min(config.level_cap, max(1, int(level)))
    if config.level_cap == 1:
        return config.total_xp
    return (config.total_xp * (level - 1)) // (config.level_cap - 1)

def current_level(xp: int, config: SeasonConfig) -> int:
    xp = min(config.total_xp, _bounded_xp(xp))
    for level in range(config.level_cap, 0, -1):
        if xp >= level_xp(level, config):
            return level
    return 1

def pass_segments(before_xp: int, after_xp: int, config: SeasonConfig) -> list[dict[str, int | bool]]:
    before = min(config.total_xp, _bounded_xp(before_xp))
    after = min(config.total_xp, max(before, _bounded_xp(after_xp)))
    level = current_level(before, config)
    if before == after:
        return [{'level': level, 'from': before - level_xp(level, config), 'to': before - level_xp(level, config),
                 'need': level_xp(level + 1, config) - level_xp(level, config) if level < config.level_cap else 0,
                 'level_up': False}]
    out: list[dict[str, int | bool]] = []
    cursor = before
    while cursor < after:
        level = current_level(cursor, config)
        base = level_xp(level, config)
        boundary = level_xp(level + 1, config) if level < config.level_cap else config.total_xp
        target = min(after, boundary)
        out.append({'level': level, 'from': cursor - base, 'to': target - base,
                    'need': boundary - base, 'level_up': target >= boundary and level < config.level_cap})
        cursor = target
    return out

def task_reward_xp(period: str, completed_count: int) -> int:
    if int(completed_count or 0) < 2:
        return 0
    return {'daily': 200, 'weekly': 800}.get(period, 0)

def season_state(now: int, config: SeasonConfig) -> SeasonState:
    now = int(now)
    if now < config.starts_at:
        return 'upcoming'
    if now < config.ends_at:
        return 'active'
    if now < config.claim_ends_at:
        return 'claim_only'
    return 'closed'

def season_challenges(season_id: str) -> list[dict[str, int | str]]:
    return [
        {'id': f'{season_id}:voyage', 'metric': 'matches', 'target': 20, 'xp': 800,
         'title': '远洋航线', 'description': '完成 20 场有效排位或休闲真人对局'},
        {'id': f'{season_id}:cards', 'metric': 'cards', 'target': 50, 'xp': 800,
         'title': '万法试航', 'description': '在有效真人对局中打出 50 张魔法卡'},
        {'id': f'{season_id}:victories', 'metric': 'wins', 'target': 10, 'xp': 1000,
         'title': '深海凯旋', 'description': '赢得 10 场排位或休闲真人对局'},
    ]

__all__ = ['SeasonConfig', 'current_level', 'level_xp', 'pass_segments', 'season_state',
           'task_reward_xp', 'season_challenges']
