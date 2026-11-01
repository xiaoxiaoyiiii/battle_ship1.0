"""新增潮汐徽记钱包与幂等流水，购买记录复用扣款流水。"""
import sqlalchemy as sa
from alembic import op

revision = "0006_tide_ash_shop"
down_revision = "0005_profile_effects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tide_ash_wallets",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint("balance >= 0", name="ck_tide_ash_balance"),
    )
    op.create_table(
        "tide_ash_ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_kind", "source_id", name="uq_tide_ash_source"),
    )
    op.create_index("idx_tide_ash_user_source_time", "tide_ash_ledger",
                    ["user_id", "source_kind", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_tide_ash_user_source_time", table_name="tide_ash_ledger")
    op.drop_table("tide_ash_ledger")
    op.drop_table("tide_ash_wallets")
