"""SQLAlchemy 2.x models for the legacy database schema.

The old stack reported "22 tables"; that count includes SQLite's internal
`sqlite_sequence` table. This module models the **21 application tables** (the
four AUTOINCREMENT tables make SQLite create `sqlite_sequence` implicitly), plus
the unused-but-present `match_history` view, which the first Alembic revision
creates so that a fresh database is byte-for-byte comparable with a legacy one.

Deliberate parity decisions:

* **No DDL foreign keys.** The legacy schema declares none, and legacy rows carry
  non-user ids (guest socket ids, `ai-*`) in `matches.winner_id`/`loser_id`.
  Adding constraints would make an existing database unmigratable. Intended
  references are recorded in :data:`SEMANTIC_REFERENCES` and enforced by the
  repositories' write paths, not by SQLite.
* **Types are TEXT/INTEGER** (not VARCHAR), because the legacy DDL used those
  names and `PRAGMA table_info` reports them verbatim.
* **Server defaults are written as SQL text** so the migrated schema keeps the
  legacy default literals (`''`, `'[]'`, `'none'`, `0`, `1`).
* **Primary keys are NOT NULL in metadata.** SQLAlchemy always marks PK columns
  NOT NULL while the legacy `TEXT PRIMARY KEY` quirk reported `notnull=0`; the
  schema checker normalizes that difference for PK columns only.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import Index, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by every repository model."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    username: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    password_hash: Mapped[str | None] = mapped_column(sa.Text)
    wins: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    losses: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    current_streak: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    longest_streak: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    created_at: Mapped[int | None] = mapped_column(sa.Integer)
    signature: Mapped[str | None] = mapped_column(sa.Text, server_default=text("''"))
    avatar: Mapped[str | None] = mapped_column(sa.Text, server_default=text("''"))
    token: Mapped[str | None] = mapped_column(sa.Text, server_default=text("''"))

    __table_args__ = (Index("idx_users_token", "token"),)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    winner_id: Mapped[str | None] = mapped_column(sa.Text)
    loser_id: Mapped[str | None] = mapped_column(sa.Text)
    timestamp: Mapped[int | None] = mapped_column(sa.Integer)
    # NULL means "legacy match, mode unknown" -- never backfill to 'casual'.
    mode: Mapped[str | None] = mapped_column(sa.Text)

    __table_args__ = (
        Index("idx_matches_winner", "winner_id"),
        Index("idx_matches_loser", "loser_id"),
        Index("idx_matches_ts", "timestamp"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(sa.Text)
    username: Mapped[str | None] = mapped_column(sa.Text)
    content: Mapped[str | None] = mapped_column(sa.Text)
    timestamp: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (
        Index("idx_chat_ts", "timestamp"),
        {"sqlite_autoincrement": True},
    )


class ActiveGame(Base):
    __tablename__ = "active_games"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    room_id: Mapped[str | None] = mapped_column(sa.Text)
    updated_at: Mapped[int | None] = mapped_column(sa.Integer)


class MatchLog(Base):
    __tablename__ = "match_logs"

    match_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    logs: Mapped[str | None] = mapped_column(sa.Text)


class MatchReplay(Base):
    __tablename__ = "match_replays"

    match_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    winner_user_id: Mapped[str | None] = mapped_column(sa.Text)
    loser_user_id: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    bytes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    replay: Mapped[str] = mapped_column(sa.Text, nullable=False)

    __table_args__ = (
        Index("idx_replay_winner", "winner_user_id", text("created_at DESC")),
        Index("idx_replay_loser", "loser_user_id", text("created_at DESC")),
    )


class CardUsage(Base):
    __tablename__ = "card_usage"

    card_name: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    uses: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (Index("idx_card_usage_uses", text("uses DESC")),)


class UserProfile(Base):
    __tablename__ = "user_profile"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    title_id: Mapped[str | None] = mapped_column(sa.Text, server_default=text("''"))
    tags: Mapped[str | None] = mapped_column(sa.Text, server_default=text("'[]'"))
    status_text: Mapped[str | None] = mapped_column(sa.Text, server_default=text("''"))
    frame_id: Mapped[str | None] = mapped_column(sa.Text, server_default=text("'none'"))
    card_bg_id: Mapped[str | None] = mapped_column(sa.Text, server_default=text("'deep'"))
    show_stats: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("1"))
    show_fav_cards: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("1"))
    show_history: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    updated_at: Mapped[int | None] = mapped_column(sa.Integer)
    # The five columns the old stack appended with PRAGMA + ALTER TABLE. Declared
    # in the same order so a migrated old database and a fresh one agree.
    show_guestbook: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("1"))
    show_rank: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("1"))
    friend_requests_open: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("1"))
    allow_spectate: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("1"))
    allow_replay: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("1"))
    avatar_alt: Mapped[str | None] = mapped_column(sa.Text, server_default=text("''"))
    profile_bg_id: Mapped[str | None] = mapped_column(sa.Text, server_default=text("'deep_ocean'"))
    pointer_effect_id: Mapped[str | None] = mapped_column(sa.Text, server_default=text("'none'"))
    title_effect_id: Mapped[str | None] = mapped_column(sa.Text, server_default=text("'glint'"))


class UserCardUsage(Base):
    __tablename__ = "user_card_usage"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    card_name: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    uses: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (Index("idx_user_card_usage_uses", "user_id", text("uses DESC")),)


class UserCounters(Base):
    __tablename__ = "user_counters"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    sunk_total: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    matches_played: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    flawless_wins: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    fastest_win_sec: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    updated_at: Mapped[int | None] = mapped_column(sa.Integer)


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    badge_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    unlocked_at: Mapped[int | None] = mapped_column(sa.Integer)


class UserXp(Base):
    __tablename__ = "user_xp"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    xp: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[int | None] = mapped_column(sa.Integer)


class UserPerk(Base):
    __tablename__ = "user_perks"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    perk: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    granted_at: Mapped[int | None] = mapped_column(sa.Integer)


class BattlePassSeason(Base):
    __tablename__ = "battle_pass_seasons"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    starts_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    ends_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    claim_ends_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    level_cap: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    total_xp: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    rules_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default=text("'draft'"))
    created_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)


class BattlePassLevel(Base):
    __tablename__ = "battle_pass_levels"

    season_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    level: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    xp_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    free_kind: Mapped[str | None] = mapped_column(sa.Text)
    free_reward_id: Mapped[str | None] = mapped_column(sa.Text)
    premium_kind: Mapped[str | None] = mapped_column(sa.Text)
    premium_reward_id: Mapped[str | None] = mapped_column(sa.Text)


class UserBattlePass(Base):
    __tablename__ = "user_battle_pass"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    season_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    xp: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    premium_unlocked: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)


class BattlePassClaim(Base):
    __tablename__ = "battle_pass_claims"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    season_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    level: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    track: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    reward_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reward_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    grant_key: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    claimed_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)


class BattlePassEvent(Base):
    __tablename__ = "battle_pass_events"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    season_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    xp_delta: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("user_id", "season_id", "source_kind", "source_id",
                            name="uq_battle_pass_event_source"),
        Index("idx_battle_pass_events_user", "user_id", "season_id", "created_at"),
    )


class BattlePassChallengeProgress(Base):
    """按赛季记录挑战累计进度；完成标记用于保证奖励只发一次。"""

    __tablename__ = "battle_pass_challenge_progress"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    season_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    challenge_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    progress: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    completed_at: Mapped[int | None] = mapped_column(sa.Integer)
    updated_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)


class UserCosmeticReward(Base):
    __tablename__ = "user_cosmetic_rewards"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    kind: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    reward_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    source_season_id: Mapped[str | None] = mapped_column(sa.Text)
    source_level: Mapped[int | None] = mapped_column(sa.Integer)
    source_track: Mapped[str | None] = mapped_column(sa.Text)
    granted_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)


class ProfileLike(Base):
    __tablename__ = "profile_likes"

    from_user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    to_user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    kind: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    created_at: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (Index("idx_profile_likes_to", "to_user_id", "kind"),)


class ProfileMessage(Base):
    __tablename__ = "profile_messages"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    to_user_id: Mapped[str | None] = mapped_column(sa.Text)
    from_user_id: Mapped[str | None] = mapped_column(sa.Text)
    from_name: Mapped[str | None] = mapped_column(sa.Text)
    content: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[int | None] = mapped_column(sa.Integer)
    deleted: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))

    __table_args__ = (
        Index("idx_profile_messages_box", "to_user_id", "deleted", text("id DESC")),
        Index("idx_profile_messages_pair", "from_user_id", "to_user_id", "created_at"),
        {"sqlite_autoincrement": True},
    )


class UserRank(Base):
    __tablename__ = "user_rank"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    points: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    is_admiral: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    ranked_wins: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    ranked_losses: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (
        Index("idx_user_rank_points", text("points DESC"), "updated_at"),
        Index("idx_user_rank_points_asc", "points"),
    )


class UserFriend(Base):
    __tablename__ = "user_friends"

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    friend_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    status: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[int | None] = mapped_column(sa.Integer)
    updated_at: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (Index("idx_user_friends_user", "user_id", "status"),)


class FriendMessage(Base):
    __tablename__ = "friend_messages"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    from_uid: Mapped[str] = mapped_column(sa.Text, nullable=False)
    to_uid: Mapped[str] = mapped_column(sa.Text, nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    read_at: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))

    __table_args__ = (
        Index("idx_friend_messages_pair", "from_uid", "to_uid", "id"),
        Index("idx_friend_messages_unread", "to_uid", "read_at"),
        {"sqlite_autoincrement": True},
    )


class AnticheatFlag(Base):
    __tablename__ = "anticheat_flags"

    match_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    rule: Mapped[str | None] = mapped_column(sa.Text)
    severity: Mapped[str | None] = mapped_column(sa.Text)
    detail: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[int | None] = mapped_column(sa.Integer)


class MatchSuspicion(Base):
    __tablename__ = "match_suspicion"

    match_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(sa.Text)
    score: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text("0"))
    level: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (Index("idx_match_suspicion_uid", "user_id", text("created_at DESC")),)


class AnticheatOverride(Base):
    __tablename__ = "anticheat_overrides"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(sa.Text)
    level: Mapped[int | None] = mapped_column(sa.Integer)
    cleared: Mapped[int | None] = mapped_column(sa.Integer, server_default=text("0"))
    reason: Mapped[str | None] = mapped_column(sa.Text)
    actor: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (
        Index("idx_anticheat_overrides_uid", "user_id", text("id DESC")),
        {"sqlite_autoincrement": True},
    )


#: Intended, non-enforced references (the legacy schema has no FOREIGN KEY DDL).
#: Repositories must treat these as consistency requirements when writing.
SEMANTIC_REFERENCES: dict[tuple[str, str], tuple[str, str]] = {
    ("match_logs", "match_id"): ("matches", "id"),
    ("match_replays", "match_id"): ("matches", "id"),
    ("match_replays", "winner_user_id"): ("users", "id"),
    ("match_replays", "loser_user_id"): ("users", "id"),
    ("user_profile", "user_id"): ("users", "id"),
    ("user_card_usage", "user_id"): ("users", "id"),
    ("user_counters", "user_id"): ("users", "id"),
    ("user_achievements", "user_id"): ("users", "id"),
    ("user_xp", "user_id"): ("users", "id"),
    ("user_perks", "user_id"): ("users", "id"),
    ("user_rank", "user_id"): ("users", "id"),
    ("user_friends", "user_id"): ("users", "id"),
    ("user_friends", "friend_id"): ("users", "id"),
    ("profile_likes", "from_user_id"): ("users", "id"),
    ("profile_likes", "to_user_id"): ("users", "id"),
    ("profile_messages", "to_user_id"): ("users", "id"),
    ("profile_messages", "from_user_id"): ("users", "id"),
    ("friend_messages", "from_uid"): ("users", "id"),
    ("friend_messages", "to_uid"): ("users", "id"),
    ("anticheat_overrides", "user_id"): ("users", "id"),
    ("match_suspicion", "user_id"): ("users", "id"),
    ("anticheat_flags", "match_id"): ("matches", "id"),
    ("chat_messages", "user_id"): ("users", "id"),
    ("active_games", "user_id"): ("users", "id"),
}


class UserTaskCounter(Base):
    """按账户、北京时间日期和任务指标累计的持久进度。"""
    __tablename__ = 'user_task_counters'
    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    day: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    metric: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    value: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=text('0'))
