"""应用的持久化入口；默认委托现有 SQLite DAO。

替换 backend 可让应用在测试或迁移时使用同一组仓储操作，而无需导入 SQLite。
"""
from __future__ import annotations

import db as sqlite_dao

# 仅暴露 HTTP/Socket 层实际使用的仓储操作。新调用需要先在这里明确登记。
REPOSITORY_OPERATIONS = frozenset('''
accept_friend_request add_friend_message add_profile_message add_rank_points
add_user_xp block_user bump_user_counters captains_ordered
consecutive_losses count_friend_messages_since count_friends
count_profile_messages_since count_rank_at_least count_requests_since
count_unread_messages create_user delete_match_replay get_achievement_stats
get_all_suspicion_totals get_allow_replay get_allow_spectate
get_anticheat_flags get_anticheat_override get_anticheat_override_history
get_card_usage get_distinct_cards_used get_friend_relation get_leaderboard get_match_history
get_match_replay get_match_suspicion get_my_reactions get_perks_map
get_profile_message get_profile_reaction_counts get_rank_map get_rank_position
get_token_by_password get_user get_user_achievements get_user_card_usage
get_user_card_uses_total get_user_counters get_user_profile_extra get_user_rank
get_user_rank_row get_user_xp get_xp_map grant_user_achievements
has_more_friend_messages has_user_perk init_db list_friend_messages
list_friends list_incoming_requests list_outgoing_requests list_profile_messages
mark_friend_messages_read public_user_cards ranked_leaderboard recent_foes
record_anticheat_flag record_card_use record_match record_match_suspicion
record_user_card_use remove_friend remove_friend_request save_user_profile_extra
send_friend_request set_allow_replay set_allow_spectate set_anticheat_override
set_profile_reaction soft_delete_profile_message unread_by_friend
update_user_avatar update_user_password update_user_signature
'''.split())


class Repository:
    def __init__(self, backend=sqlite_dao):
        object.__setattr__(self, '_backend', backend)

    def __getattr__(self, name):
        if name not in REPOSITORY_OPERATIONS:
            raise AttributeError(name)
        return getattr(self._backend, name)

    def __setattr__(self, name, value):
        if name == '_backend':
            object.__setattr__(self, name, value)
        elif name in REPOSITORY_OPERATIONS:
            setattr(self._backend, name, value)
        else:
            raise AttributeError(name)

    def __delattr__(self, name):
        if name not in REPOSITORY_OPERATIONS:
            raise AttributeError(name)
        delattr(self._backend, name)

    def use_backend(self, backend):
        """仅供显式配置和测试替换；返回旧 backend 便于恢复。"""
        old = self._backend
        self._backend = backend
        return old

    def recent_foes(self, uid: str, limit: int) -> set[str]:
        return self._backend.recent_foes(uid, limit)

    def consecutive_losses(self, uid: str, limit: int = 50) -> int:
        return self._backend.consecutive_losses(uid, limit)

    def public_user_cards(self, uids) -> dict:
        return self._backend.public_user_cards(uids)


repository = Repository()
