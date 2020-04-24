"""consolidated all server models

Revision ID: 5246a3f7a7e4
Revises: 
Create Date: 2017-09-28 01:07:38.062803

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5246a3f7a7e4'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('appconfig',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('replication_dn', sa.String(length=200), nullable=True),
    sa.Column('replication_pw', sa.String(length=200), nullable=True),
    sa.Column('last_test', sa.Boolean(), nullable=True),
    sa.Column('gluu_version', sa.String(length=10), nullable=True),
    sa.Column('use_ip', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('keyrotation',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('interval', sa.Integer(), nullable=True),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('type', sa.String(length=16), nullable=True),
    sa.Column('oxeleven_url', sa.String(length=255), nullable=True),
    sa.Column('oxeleven_token', sa.LargeBinary(), nullable=True),
    sa.Column('oxeleven_token_key', sa.LargeBinary(), nullable=True),
    sa.Column('oxeleven_token_iv', sa.LargeBinary(), nullable=True),
    sa.Column('inum_appliance', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('logging_server',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('url', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('oxeleven_key_id',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kid', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('server',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hostname', sa.String(length=250), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('ldap_password', sa.String(length=150), nullable=True),
    sa.Column('os', sa.String(length=150), nullable=True),
    sa.Column('cache_method', sa.String(length=50), nullable=True),
    sa.Column('components', sa.Text(), nullable=True),
    sa.Column('mmr', sa.Boolean(), nullable=True),
    sa.Column('gluu_server', sa.Boolean(), nullable=True),
    sa.Column('primary_server', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hostname')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('server')
    op.drop_table('oxeleven_key_id')
    op.drop_table('logging_server')
    op.drop_table('keyrotation')
    op.drop_table('appconfig')
    # ### end Alembic commands ###