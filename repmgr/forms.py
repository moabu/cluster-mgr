from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, BooleanField, IntegerField, \
        PasswordField
from wtforms.validators import DataRequired


class NewServerForm(FlaskForm):
    host = StringField('Hostname', validators=[DataRequired()], description="Hostname of the server")
    port = IntegerField('Port', validators=[DataRequired()], description="LDAP port used for accessing the server")
    starttls = BooleanField('startTLS', default=False)
    role = SelectField('Role', choices=[('master', 'Master'), ('consumer', 'Consumer')])
    server_id = IntegerField('Server ID')
    replication_id = IntegerField('Replication ID')


class NewMasterForm(FlaskForm):
    hostname = StringField('Hostname', validators=[DataRequired()])
    port = IntegerField('Port', validators=[DataRequired()])
    starttls = BooleanField('StartTLS', default=False)
    server_id = IntegerField('Server ID')
    replication_id = IntegerField('Replication ID')
    manager_dn = StringField('Root Manager DN')
    manager_pw = PasswordField('Root Manager Password')


class NewProviderForm(FlaskForm):
    hostname = StringField('Hostname', validators=[DataRequired()])
    port = IntegerField('Port', validators=[DataRequired()])
    starttls = BooleanField('Use StartTLS for communication', default=False)
    admin_pw = StringField('LDAP Admin Password', validators=[DataRequired()])
    replication_pw = StringField('Replication Password',
                                 validators=[DataRequired()])
    tls_cacert = StringField('TLS CA Certificate')
    tls_servercert = StringField('TLS Server Certificate')
    tls_serverkey = StringField('TLS Server Cert Key')


class NewConsumerForm(FlaskForm):
    hostname = StringField('Hostname', validators=[DataRequired()])
    port = IntegerField('Port', validators=[DataRequired()])
    starttls = BooleanField('Use StartTLS for communication', default=False)
    admin_pw = StringField('LDAP Admin Password', validators=[DataRequired()])
    tls_cacert = StringField('TLS CA Certificate')
    tls_servercert = StringField('TLS Server Certificate')
    tls_serverkey = StringField('TLS Server Cert Key')
    provider = SelectField('Provider', coerce=int)
