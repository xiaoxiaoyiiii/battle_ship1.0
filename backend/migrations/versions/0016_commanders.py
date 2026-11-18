"""新增指挥官角色系统四张业务表（拥有、出战选择、等级领奖、经验流水）。"""
import sqlalchemy as sa
from alembic import op

revision = "0016_commanders"
down_revision = "0015_card_skins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_commanders_owned",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("commander_id", sa.Text(), nullable=False),
        sa.Column("unlock_source", sa.Text(), nullable=False),
        sa.Column("cost_paid", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("xp", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("equipped_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("unlocked_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "commander_id"),
    )
    op.create_index(
        "idx_user_commanders_owned_user",
        "user_commanders_owned",
        ["user_id"],
    )

    op.create_table(
        "user_commander_selections",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("selected_commander_id", sa.Text(), nullable=False),
        sa.Column("free_claimed", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_commander_claims",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("commander_id", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "commander_id", "level"),
    )
    op.create_index(
        "idx_user_commander_claims_user",
        "user_commander_claims",
        ["user_id", "commander_id"],
    )

    op.create_table(
        "commander_xp_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("commander_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("is_ai", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("day_cst", sa.Text(), nullable=False),
        sa.Column("raw_xp", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("granted_xp", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("before_xp", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("after_xp", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("before_level", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("after_level", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("reason", sa.Text(), nullable=False, server_default=sa.text("'settled'")),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "match_id", name="uq_commander_xp_user_match"),
    )
    op.create_index(
        "idx_commander_xp_user_day_ai",
        "commander_xp_events",
        ["user_id", "day_cst", "is_ai"],
    )


def downgrade() -> None:
    op.drop_index("idx_commander_xp_user_day_ai", table_name="commander_xp_events")
    op.drop_table("commander_xp_events")
    op.drop_index("idx_user_commander_claims_user", table_name="user_commander_claims")
    op.drop_table("user_commander_claims")
    op.drop_table("user_commander_selections")
    op.drop_index("idx_user_commanders_owned_user", table_name="user_commanders_owned")
    op.drop_table("user_commanders_owned")
