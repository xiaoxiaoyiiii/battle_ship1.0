"""独立保存新图鉴、熟练、成就与结算幂等记录，既有计数不回填。"""
import sqlalchemy as sa
from alembic import op

revision = '0014_collection'
down_revision = '0013_daily_checkin'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('collection_cards',
        sa.Column('user_id',sa.Text(),nullable=False),sa.Column('card_name',sa.Text(),nullable=False),
        sa.Column('lit',sa.Integer(),nullable=False,server_default=sa.text('0')),
        sa.Column('uses',sa.Integer(),nullable=False,server_default=sa.text('0')),
        sa.Column('wins',sa.Integer(),nullable=False,server_default=sa.text('0')),
        sa.Column('selected_tier',sa.Integer(),nullable=False,server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('user_id','card_name'))
    op.create_table('collection_progress',sa.Column('user_id',sa.Text(),primary_key=True),
        sa.Column('state',sa.Text(),nullable=False,server_default=sa.text("'{}'")))
    op.create_table('collection_settlements',sa.Column('user_id',sa.Text(),nullable=False),
        sa.Column('source_id',sa.Text(),nullable=False),sa.PrimaryKeyConstraint('user_id','source_id'))


def downgrade():
    op.drop_table('collection_settlements')
    op.drop_table('collection_progress')
    op.drop_table('collection_cards')
