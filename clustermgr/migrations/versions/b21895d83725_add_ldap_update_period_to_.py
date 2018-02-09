"""add ldap_update_period to AppConfiguration

Revision ID: b21895d83725
Revises: 4fca7c65b3df
Create Date: 2018-02-09 19:25:07.807805

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b21895d83725'
down_revision = '4fca7c65b3df'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('appconfig', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ldap_update_period', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('appconfig', schema=None) as batch_op:
        batch_op.drop_column('ldap_update_period')

    # ### end Alembic commands ###
