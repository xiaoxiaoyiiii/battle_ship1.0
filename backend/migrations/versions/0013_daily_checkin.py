"""每日签到按人和沪时自然日唯一，不改动已有徽记流水。"""
import sqlalchemy as sa
from alembic import op

revision = "0013_daily_checkin"
down_revision = "0012_client_promo"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_checkins",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "day"),
    )


def downgrade():
    op.drop_table("daily_checkins")
