"""Ban名额、选择与牌堆过滤的唯一纯规则入口。"""
from functools import lru_cache
import json
from pathlib import Path

from ..magic.cards import UNIQUE_CARD_NAMES
from ..progression import ranks


@lru_cache(maxsize=1)
def configuration() -> dict:
    return json.loads((Path(__file__).with_name('data') / 'rules.json').read_text(encoding='utf-8'))


def ban_pool() -> list[str]:
    return sorted(set(UNIQUE_CARD_NAMES) - set(configuration()['protected_names']))


def quota_for_points(points: int) -> int:
    return min(2, ranks.points_tier_index(points) // 3)


def match_quota(first_points: int, second_points: int) -> int:
    return max(quota_for_points(first_points), quota_for_points(second_points))


def validate_selection(names, quota: int) -> str | None:
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        return '请选择有效的Ban卡列表'
    if len(names) > quota or len(names) != len(set(names)):
        return 'Ban卡不能重复或超过本局名额'
    if any(name not in ban_pool() for name in names):
        return '失灵！不可Ban，且只能选择可Ban卡池中的卡'
    return None


def timeout_selection(names: list[str], quota: int) -> list[str]:
    result = list(names)
    for name in configuration()['timeout_defaults']:
        if len(result) >= quota:
            break
        if name not in result:
            result.append(name)
    return result


def merge_selections(selections: dict[str, list[str]]) -> set[str]:
    return {name for names in selections.values() for name in names}


def custom_error(enabled, quota) -> str | None:
    if type(enabled) is not bool:
        return 'Ban卡开关必须是开启或关闭'
    if enabled and (type(quota) is not int or not 1 <= quota <= 10):
        return '开启Ban卡后每人名额必须是1至10的整数'
    return None


def pending(room) -> bool:
    return room.ban_enabled and room.ban_phase != 'revealed'


def escape_eligible(room) -> bool:
    return bool(room.ranked and room.ban_enabled and room.ban_phase == 'revealed'
                and not room.ban_initial_placement_complete
                and getattr(room.state, 'value', room.state) == 'placing_ships')


def filter_cards(room, cards):
    return [card for card in cards if card.name not in room.banned_names]


def prune_piles(room) -> None:
    room.magic_deck[:] = filter_cards(room, room.magic_deck)
    room.magic_discard[:] = filter_cards(room, room.magic_discard)


def payload(room, player_id: str) -> dict | None:
    if not room.ban_enabled or room.ban_phase == 'off':
        return None
    public = room.ban_phase == 'revealed'
    return {
        'enabled': True, 'quota': room.ban_quota, 'phase': room.ban_phase,
        'countdown_deadline': room.ban_countdown_deadline,
        'selection_deadline': room.ban_selection_deadline,
        'own_selection': list(room.ban_selections.get(player_id, [])),
        'confirmed': player_id in room.ban_confirmed,
        'opponent_confirmed': room.opponent_of(player_id) in room.ban_confirmed,
        'revealed': {pid: list(names) for pid, names in room.ban_selections.items()} if public else None,
        'banned_names': sorted(room.banned_names) if public else [],
        'pool': ban_pool(), 'ranked': bool(room.ranked),
    }
