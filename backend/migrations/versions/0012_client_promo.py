"""客户端登录记录与下载提示每日去重，不改动既有玩家数据。"""
import sqlalchemy as sa
from alembic import op

revision = '0012_client_promo'
down_revision = '0011_match_eligibility'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('client_logins',
                    sa.Column('user_id', sa.Text(), primary_key=True),
                    sa.Column('platform', sa.Text(), nullable=False),
                    sa.Column('logged_at', sa.Integer(), nullable=False))
    op.create_table('client_promo_days',
                    sa.Column('user_id', sa.Text(), primary_key=True),
                    sa.Column('day_key', sa.Text(), nullable=False))


def downgrade():
    op.drop_table('client_promo_days')
    op.drop_table('client_logins')
