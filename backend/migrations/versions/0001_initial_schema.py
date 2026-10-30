"""Create the legacy 21-table schema, 19 indexes and the match_history view.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-20

This revision is a frozen transcription of the old stack's `db.init_db()` DDL. It is
deliberately NOT generated from `repositories.models` so history cannot change when
models change; the outside-repo parity gate pins model/revision/legacy agreement.

Dual-path behaviour (empty database vs. an existing legacy database with no
`alembic_version`): every table is created only when missing; for an existing table
only missing columns are appended with `ALTER TABLE`, in the same order the old
stack appended them. Indexes and the view are created `IF NOT EXISTS`, so running
this revision repeatedly (or against a database the old stack already initialised)
is idempotent. Downgrade drops all of it -- use the migration runner's file backup
for a non-destructive rollback.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        'users',
        (
            'id             TEXT PRIMARY KEY',
            'username       TEXT UNIQUE',
            'password_hash  TEXT',
            'wins           INTEGER DEFAULT 0',
            'losses         INTEGER DEFAULT 0',
            'current_streak INTEGER DEFAULT 0',
            'longest_streak INTEGER DEFAULT 0',
            'created_at     INTEGER',
            "signature      TEXT    DEFAULT ''",
            "avatar         TEXT    DEFAULT ''",
            "token          TEXT    DEFAULT ''",
        ),
    ),
    (
        'matches',
        (
            'id        TEXT PRIMARY KEY',
            'winner_id TEXT',
            'loser_id  TEXT',
            'timestamp INTEGER',
            'mode      TEXT',
        ),
    ),
    (
        'chat_messages',
        (
            'id        INTEGER PRIMARY KEY AUTOINCREMENT',
            'user_id   TEXT',
            'username  TEXT',
            'content   TEXT',
            'timestamp INTEGER',
        ),
    ),
    (
        'active_games',
        (
            'user_id    TEXT PRIMARY KEY',
            'room_id    TEXT',
            'updated_at INTEGER',
        ),
    ),
    (
        'match_logs',
        (
            'match_id TEXT PRIMARY KEY',
            'logs     TEXT',
        ),
    ),
    (
        'match_replays',
        (
            'match_id        TEXT PRIMARY KEY',
            'winner_user_id  TEXT',
            'loser_user_id   TEXT',
            'created_at      INTEGER NOT NULL',
            'bytes           INTEGER NOT NULL',
            'version         INTEGER NOT NULL',
            'replay          TEXT NOT NULL',
        ),
    ),
    (
        'card_usage',
        (
            'card_name  TEXT PRIMARY KEY',
            'uses       INTEGER NOT NULL DEFAULT 0',
            'updated_at INTEGER',
        ),
    ),
    (
        'user_profile',
        (
            'user_id         TEXT PRIMARY KEY',
            "title_id        TEXT    DEFAULT ''",
            "tags            TEXT    DEFAULT '[]'",
            "status_text     TEXT    DEFAULT ''",
            "frame_id        TEXT    DEFAULT 'none'",
            "card_bg_id      TEXT    DEFAULT 'deep'",
            'show_stats      INTEGER DEFAULT 1',
            'show_fav_cards  INTEGER DEFAULT 1',
            'show_history    INTEGER DEFAULT 0',
            'updated_at      INTEGER',
            'show_guestbook      INTEGER DEFAULT 1',
            'show_rank           INTEGER DEFAULT 1',
            'friend_requests_open INTEGER DEFAULT 1',
            'allow_spectate      INTEGER DEFAULT 1',
            'allow_replay        INTEGER DEFAULT 1',
        ),
    ),
    (
        'user_card_usage',
        (
            'user_id    TEXT',
            'card_name  TEXT',
            'uses       INTEGER NOT NULL DEFAULT 0',
            'updated_at INTEGER',
            'PRIMARY KEY (user_id, card_name)',
        ),
    ),
    (
        'user_counters',
        (
            'user_id          TEXT PRIMARY KEY',
            'sunk_total       INTEGER DEFAULT 0',
            'matches_played   INTEGER DEFAULT 0',
            'flawless_wins    INTEGER DEFAULT 0',
            'fastest_win_sec  INTEGER DEFAULT 0',
            'updated_at       INTEGER',
        ),
    ),
    (
        'user_achievements',
        (
            'user_id     TEXT',
            'badge_id    TEXT',
            'unlocked_at INTEGER',
            'PRIMARY KEY (user_id, badge_id)',
        ),
    ),
    (
        'user_xp',
        (
            'user_id    TEXT PRIMARY KEY',
            'xp         INTEGER NOT NULL DEFAULT 0',
            'updated_at INTEGER',
        ),
    ),
    (
        'user_perks',
        (
            'user_id    TEXT',
            'perk       TEXT',
            'granted_at INTEGER',
            'PRIMARY KEY (user_id, perk)',
        ),
    ),
    (
        'profile_likes',
        (
            'from_user_id TEXT',
            'to_user_id   TEXT',
            'kind         TEXT',
            'created_at   INTEGER',
            'PRIMARY KEY (from_user_id, to_user_id, kind)',
        ),
    ),
    (
        'profile_messages',
        (
            'id           INTEGER PRIMARY KEY AUTOINCREMENT',
            'to_user_id   TEXT',
            'from_user_id TEXT',
            'from_name    TEXT',
            'content      TEXT',
            'created_at   INTEGER',
            'deleted      INTEGER DEFAULT 0',
        ),
    ),
    (
        'user_rank',
        (
            'user_id       TEXT PRIMARY KEY',
            'points        INTEGER NOT NULL DEFAULT 0',
            'is_admiral    INTEGER NOT NULL DEFAULT 0',
            'ranked_wins   INTEGER NOT NULL DEFAULT 0',
            'ranked_losses INTEGER NOT NULL DEFAULT 0',
            'updated_at    INTEGER',
        ),
    ),
    (
        'user_friends',
        (
            'user_id    TEXT',
            'friend_id  TEXT',
            'status     TEXT',
            'created_at INTEGER',
            'updated_at INTEGER',
            'PRIMARY KEY (user_id, friend_id)',
        ),
    ),
    (
        'friend_messages',
        (
            'id         INTEGER PRIMARY KEY AUTOINCREMENT',
            'from_uid   TEXT    NOT NULL',
            'to_uid     TEXT    NOT NULL',
            'body       TEXT    NOT NULL',
            'created_at INTEGER NOT NULL',
            'read_at    INTEGER DEFAULT 0',
        ),
    ),
    (
        'anticheat_flags',
        (
            'match_id   TEXT PRIMARY KEY',
            'rule       TEXT',
            'severity   TEXT',
            'detail     TEXT',
            'created_at INTEGER',
        ),
    ),
    (
        'match_suspicion',
        (
            'match_id   TEXT PRIMARY KEY',
            'user_id    TEXT',
            'score      INTEGER NOT NULL DEFAULT 0',
            'level      TEXT',
            'created_at INTEGER',
        ),
    ),
    (
        'anticheat_overrides',
        (
            'id          INTEGER PRIMARY KEY AUTOINCREMENT',
            'user_id     TEXT',
            'level       INTEGER',
            'cleared     INTEGER DEFAULT 0',
            'reason      TEXT',
            'actor       TEXT',
            'created_at  INTEGER',
        ),
    ),
)

INDEXES: tuple[str, ...] = (
    'CREATE INDEX IF NOT EXISTS idx_matches_winner ON matches(winner_id)',
    'CREATE INDEX IF NOT EXISTS idx_matches_loser ON matches(loser_id)',
    'CREATE INDEX IF NOT EXISTS idx_matches_ts ON matches(timestamp)',
    'CREATE INDEX IF NOT EXISTS idx_users_token ON users(token)',
    'CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages(timestamp)',
    'CREATE INDEX IF NOT EXISTS idx_card_usage_uses ON card_usage(uses DESC)',
    'CREATE INDEX IF NOT EXISTS idx_user_card_usage_uses ON user_card_usage(user_id, uses DESC)',
    'CREATE INDEX IF NOT EXISTS idx_profile_messages_box ON profile_messages(to_user_id, deleted, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_profile_messages_pair ON profile_messages(from_user_id, to_user_id, created_at)',
    'CREATE INDEX IF NOT EXISTS idx_profile_likes_to ON profile_likes(to_user_id, kind)',
    'CREATE INDEX IF NOT EXISTS idx_user_rank_points ON user_rank(points DESC, updated_at)',
    'CREATE INDEX IF NOT EXISTS idx_user_rank_points_asc ON user_rank(points)',
    'CREATE INDEX IF NOT EXISTS idx_user_friends_user ON user_friends(user_id, status)',
    'CREATE INDEX IF NOT EXISTS idx_friend_messages_pair ON friend_messages(from_uid, to_uid, id)',
    'CREATE INDEX IF NOT EXISTS idx_friend_messages_unread ON friend_messages(to_uid, read_at)',
    'CREATE INDEX IF NOT EXISTS idx_replay_winner ON match_replays (winner_user_id, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_replay_loser ON match_replays (loser_user_id, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_match_suspicion_uid ON match_suspicion(user_id, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_anticheat_overrides_uid ON anticheat_overrides(user_id, id DESC)',
)

VIEW_SQL: str = 'CREATE VIEW IF NOT EXISTS match_history AS\nSELECT m.id AS match_id,\n       m.winner_id,\n       m.loser_id,\n       m.timestamp,\n       w.username AS winner_name,\n       l.username AS loser_name,\n       ml.logs\nFROM matches m\nLEFT JOIN users w ON m.winner_id = w.id\nLEFT JOIN users l ON m.loser_id = l.id\nLEFT JOIN match_logs ml ON ml.match_id = m.id'


CONSTRAINT_PREFIXES = ("PRIMARY ", "UNIQUE ", "FOREIGN ", "CHECK ", "CONSTRAINT ")


def _column_name(definition: str) -> str:
    return definition.split()[0]


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    for table_name, definitions in TABLES:
        if table_name not in existing:
            body = ",\n  ".join(definitions)
            op.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (\n  {body}\n)")
            continue

        # Existing (legacy) table: CREATE TABLE IF NOT EXISTS is a no-op, so missing
        # columns must be appended exactly like the old stack's _add_column_if_missing.
        present = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        for definition in definitions:
            if definition.upper().startswith(CONSTRAINT_PREFIXES):
                continue
            column = _column_name(definition)
            if column not in present:
                op.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")

    for statement in INDEXES:
        op.execute(statement)

    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS match_history")
    for table_name, _definitions in reversed(TABLES):
        op.drop_table(table_name)