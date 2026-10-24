"""新增每日与每周任务计数，不改动既有账号和战绩。"""
import sqlalchemy as sa
from alembic import op
revision = '0002_task_progress'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('user_task_counters',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('day', sa.Text(), nullable=False),
        sa.Column('metric', sa.Text(), nullable=False),
        sa.Column('value', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('user_id', 'day', 'metric'))

def downgrade():
    op.drop_table('user_task_counters')
