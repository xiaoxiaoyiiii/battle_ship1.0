"""为头像保存可选的替代文本，便于无障碍展示和后续缩略图元数据扩展。"""

import sqlalchemy as sa
from alembic import op


revision = "0004_avatar_metadata"
down_revision = "0003_battle_pass"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("avatar_alt", sa.Text(), nullable=True, server_default=sa.text("''")),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "avatar_alt")
