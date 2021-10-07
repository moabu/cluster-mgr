"""empty message

Revision ID: 86b22e4bf65d
Revises: 325c760b3ec7
Create Date: 2020-06-19 17:26:33.678482

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '86b22e4bf65d'
down_revision = '325c760b3ec7'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('cache_server', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ssh_port', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('cache_server', schema=None) as batch_op:
        batch_op.drop_column('ssh_port')

    # ### end Alembic commands ###