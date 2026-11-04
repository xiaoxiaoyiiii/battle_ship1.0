"""添加可撤销登录会话；旧版无会话标识的 Cookie 须重新登录。"""
import sqlalchemy as sa
from alembic import op

revision = '0010_auth_sessions'
down_revision = '0009_support_prompt'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_sessions',
                    sa.Column('id', sa.Text(), primary_key=True),
                    sa.Column('user_id', sa.Text(), nullable=False),
                    sa.Column('credential_fingerprint', sa.Text(), nullable=False),
                    sa.Column('created_at', sa.Integer(), nullable=False),
                    sa.Column('expires_at', sa.Integer(), nullable=False),
                    sa.Column('revoked_at', sa.Integer(), nullable=True))
    op.create_index('idx_auth_sessions_user', 'auth_sessions', ['user_id'])


def downgrade():
    op.drop_index('idx_auth_sessions_user', table_name='auth_sessions')
    op.drop_table('auth_sessions')
