"""记录正式开战的收益资格，保留历史记录为未知。"""
import sqlalchemy as sa
from alembic import op

revision = '0011_match_eligibility'
down_revision = '0010_auth_sessions'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('matches', sa.Column('rewards_eligible', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('matches', 'rewards_eligible')
