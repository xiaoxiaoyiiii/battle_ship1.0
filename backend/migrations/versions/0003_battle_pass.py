"""新增赛季通行证、领取幂等和外观权益表。"""
import sqlalchemy as sa
from alembic import op

revision = '0003_battle_pass'
down_revision = '0002_task_progress'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'battle_pass_seasons',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('starts_at', sa.Integer(), nullable=False),
        sa.Column('ends_at', sa.Integer(), nullable=False),
        sa.Column('claim_ends_at', sa.Integer(), nullable=False),
        sa.Column('level_cap', sa.Integer(), nullable=False),
        sa.Column('total_xp', sa.Integer(), nullable=False),
        sa.Column('rules_version', sa.Integer(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column('created_at', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'battle_pass_levels',
        sa.Column('season_id', sa.Text(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('xp_at', sa.Integer(), nullable=False),
        sa.Column('free_kind', sa.Text()),
        sa.Column('free_reward_id', sa.Text()),
        sa.Column('premium_kind', sa.Text()),
        sa.Column('premium_reward_id', sa.Text()),
        sa.PrimaryKeyConstraint('season_id', 'level'),
    )
    op.create_table(
        'user_battle_pass',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('season_id', sa.Text(), nullable=False),
        sa.Column('xp', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('premium_unlocked', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'season_id'),
    )
    op.create_table(
        'battle_pass_claims',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('season_id', sa.Text(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('track', sa.Text(), nullable=False),
        sa.Column('reward_kind', sa.Text(), nullable=False),
        sa.Column('reward_id', sa.Text(), nullable=False),
        sa.Column('grant_key', sa.Text(), nullable=False),
        sa.Column('claimed_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'season_id', 'level', 'track'),
        sa.UniqueConstraint('grant_key'),
    )
    op.create_table(
        'battle_pass_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('season_id', sa.Text(), nullable=False),
        sa.Column('source_kind', sa.Text(), nullable=False),
        sa.Column('source_id', sa.Text(), nullable=False),
        sa.Column('xp_delta', sa.Integer(), nullable=False),
        sa.Column('payload_hash', sa.Text()),
        sa.Column('created_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'season_id', 'source_kind', 'source_id',
                            name='uq_battle_pass_event_source'),
    )
    op.create_index('idx_battle_pass_events_user', 'battle_pass_events',
                    ['user_id', 'season_id', 'created_at'])
    op.create_table(
        'battle_pass_challenge_progress',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('season_id', sa.Text(), nullable=False),
        sa.Column('challenge_id', sa.Text(), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('completed_at', sa.Integer()),
        sa.Column('updated_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'season_id', 'challenge_id'),
    )
    op.create_table(
        'user_cosmetic_rewards',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('reward_id', sa.Text(), nullable=False),
        sa.Column('source_season_id', sa.Text()),
        sa.Column('source_level', sa.Integer()),
        sa.Column('source_track', sa.Text()),
        sa.Column('granted_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'kind', 'reward_id'),
    )


def downgrade():
    op.drop_table('user_cosmetic_rewards')
    op.drop_table('battle_pass_challenge_progress')
    op.drop_index('idx_battle_pass_events_user', table_name='battle_pass_events')
    op.drop_table('battle_pass_events')
    op.drop_table('battle_pass_claims')
    op.drop_table('user_battle_pass')
    op.drop_table('battle_pass_levels')
    op.drop_table('battle_pass_seasons')
