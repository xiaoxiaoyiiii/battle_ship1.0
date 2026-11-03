"""新增每日挑战唯一尝试与私有行动点来源；不改动已有对局数据。"""
import sqlalchemy as sa
from alembic import op

revision = '0007_daily_challenge'
down_revision = '0006_tide_ash_shop'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('daily_challenge_attempts',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('day', sa.Text(), nullable=False),
        sa.Column('puzzle_id', sa.Text(), nullable=False),
        sa.Column('snapshot_hash', sa.Text(), nullable=False),
        sa.Column('room_id', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('started_at', sa.Integer(), nullable=False),
        sa.Column('finished_at', sa.Integer()),
        sa.Column('xp_granted', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('user_id', 'day'))
    op.create_table('daily_challenge_sources',
        sa.Column('match_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Integer(), nullable=False),
        sa.Column('snapshots', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('match_id'))


def downgrade():
    op.drop_table('daily_challenge_sources')
    op.drop_table('daily_challenge_attempts')
