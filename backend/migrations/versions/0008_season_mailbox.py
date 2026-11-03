"""新增独立排位季记录与玩家邮件，保留全部旧数据。"""
import sqlalchemy as sa
from alembic import op

revision='0008_season_mailbox'
down_revision='0007_daily_challenge'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('ranked_season_states',
        sa.Column('season_id',sa.Text(),primary_key=True),
        sa.Column('opened_at',sa.Integer(),nullable=False),
        sa.Column('locked_at',sa.Integer()))
    op.create_table('ranked_season_accounts',
        sa.Column('season_id',sa.Text(),primary_key=True),
        sa.Column('user_id',sa.Text(),primary_key=True),
        *[sa.Column(name,sa.Integer(),nullable=False) for name in (
            'points','is_admiral','ranked_wins','ranked_losses','peak_tier','updated_at')])
    op.create_table('ranked_season_results',
        sa.Column('match_id',sa.Text(),primary_key=True),
        sa.Column('user_id',sa.Text(),primary_key=True),
        sa.Column('season_id',sa.Text(),nullable=False))
    op.create_table('mail_dispatches',
        sa.Column('source_key',sa.Text(),primary_key=True),
        sa.Column('actor',sa.Text(),nullable=False),
        sa.Column('payload_hash',sa.Text(),nullable=False),
        sa.Column('created_at',sa.Integer(),nullable=False))
    op.create_table('player_mail',
        sa.Column('id',sa.Text(),primary_key=True),
        *[sa.Column(name,sa.Text(),nullable=False) for name in (
            'user_id','source_key','title','body','attachments')],
        *[sa.Column(name,sa.Integer(),nullable=False) for name in (
            'created_at','expires_at','attachment_expires_at')],
        *[sa.Column(name,sa.Integer()) for name in ('read_at','claimed_at','deleted_at')],
        sa.UniqueConstraint('user_id','source_key',name='uq_player_mail_source'))
    op.create_index('idx_player_mail_user_time','player_mail',['user_id','created_at'])


def downgrade():
    for table in ('player_mail','mail_dispatches','ranked_season_results',
                  'ranked_season_accounts','ranked_season_states'):
        op.drop_table(table)
