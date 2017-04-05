"""create tables

Revision ID: 2c3888be67c0
Revises: 
Create Date: 2017-04-05 17:30:18.855010

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2c3888be67c0'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('appconfig',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('replication_dn', sa.String(length=200), nullable=True),
    sa.Column('replication_pw', sa.String(length=200), nullable=True),
    sa.Column('certificate_folder', sa.String(length=200), nullable=True),
    sa.Column('topology', sa.String(length=30), nullable=True),
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
    sa.Column('oxeleven_kid', sa.String(length=255), nullable=True),
    sa.Column('inum_appliance', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ldap_server',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hostname', sa.String(length=150), nullable=True),
    sa.Column('port', sa.Integer(), nullable=True),
    sa.Column('role', sa.String(length=10), nullable=True),
    sa.Column('starttls', sa.Boolean(), nullable=True),
    sa.Column('tls_cacert', sa.Text(), nullable=True),
    sa.Column('tls_servercert', sa.Text(), nullable=True),
    sa.Column('tls_serverkey', sa.Text(), nullable=True),
    sa.Column('initialized', sa.Boolean(), nullable=True),
    sa.Column('admin_pw', sa.String(length=150), nullable=True),
    sa.Column('provider_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['provider_id'], ['ldap_server.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('oxauth_server',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hostname', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('oxauth_server')
    op.drop_table('ldap_server')
    op.drop_table('keyrotation')
    op.drop_table('appconfig')
    # ### end Alembic commands ###
