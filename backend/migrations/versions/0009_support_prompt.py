"""记录账号每日推广提醒，不改动既有玩家数据。"""
import sqlalchemy as sa
from alembic import op

revision = '0009_support_prompt'
down_revision = '0008_season_mailbox'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_support_prompts',
                    sa.Column('user_id', sa.Text(), primary_key=True),
                    sa.Column('day_key', sa.Text(), nullable=False))


def downgrade():
    op.drop_table('user_support_prompts')
