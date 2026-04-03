"""add order payment method and otp order link

Revision ID: 7c1f3b2d4e5f
Revises: 02fb11049ee8
Create Date: 2026-04-03 20:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c1f3b2d4e5f'
down_revision = '02fb11049ee8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'order',
        sa.Column(
            'payment_method',
            sa.Enum('cod', 'card', 'upi', 'netbanking', name='paymentmethod'),
            nullable=True
        )
    )
    op.add_column('otp', sa.Column('order_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_otp_order_id_order', 'otp', 'order', ['order_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_otp_order_id_order', 'otp', type_='foreignkey')
    op.drop_column('otp', 'order_id')
    op.drop_column('order', 'payment_method')
