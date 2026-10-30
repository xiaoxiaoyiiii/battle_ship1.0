"""为个人资料增加整体背景、全局指针特效和称号动效槽位。"""

import sqlalchemy as sa
from alembic import op


revision = "0005_profile_effects"
down_revision = "0004_avatar_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("profile_bg_id", sa.Text(), nullable=True, server_default=sa.text("'deep_ocean'")),
    )
    op.add_column(
        "user_profile",
        sa.Column("pointer_effect_id", sa.Text(), nullable=True, server_default=sa.text("'none'")),
    )
    op.add_column(
        "user_profile",
        sa.Column("title_effect_id", sa.Text(), nullable=True, server_default=sa.text("'glint'")),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "title_effect_id")
    op.drop_column("user_profile", "pointer_effect_id")
    op.drop_column("user_profile", "profile_bg_id")
