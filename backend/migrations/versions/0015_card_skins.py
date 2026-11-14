"""新增皮肤拥有、碎片账本、每卡选用与抽卡幂等表。"""
import sqlalchemy as sa
from alembic import op

revision = "0015_card_skins"
down_revision = "0014_collection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_skins_owned",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("skin_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "skin_id"),
    )
    op.create_table(
        "card_skin_shard_wallets",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint("balance >= 0", name="ck_card_skin_shard_balance"),
    )
    op.create_table(
        "card_skin_shard_ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_kind", "source_id", name="uq_card_skin_shard_source"),
    )
    op.create_index(
        "idx_card_skin_shard_user_source_time",
        "card_skin_shard_ledger",
        ["user_id", "source_kind", "created_at"],
    )
    op.create_table(
        "card_skin_selections",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("card_name", sa.Text(), nullable=False),
        sa.Column("skin_id", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "card_name"),
    )
    op.create_table(
        "gacha_requests",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("pool_id", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "request_id"),
    )


def downgrade() -> None:
    op.drop_table("gacha_requests")
    op.drop_table("card_skin_selections")
    op.drop_index("idx_card_skin_shard_user_source_time", table_name="card_skin_shard_ledger")
    op.drop_table("card_skin_shard_ledger")
    op.drop_table("card_skin_shard_wallets")
    op.drop_table("card_skins_owned")
