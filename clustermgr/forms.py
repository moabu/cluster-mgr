try:
    from flask_wtf import FlaskForm
except ImportError:
    from flask_wtf import Form as FlaskForm
from wtforms import StringField, SelectField, BooleanField, IntegerField, \
    PasswordField, RadioField, SubmitField
from wtforms.validators import DataRequired, Regexp, AnyOf, \
    ValidationError, URL, IPAddress, Email, Length
from flask_wtf.file import FileField, FileRequired, FileAllowed


class AppConfigForm(FlaskForm):
    gluu_version = SelectField('Gluu Server Version', choices=[
        ('3.1.1', '3.1.1'), ('3.1.0', '3.1.0'), ('3.0.2', '3.0.2'),
        ('3.0.1', '3.0.1')])
    use_ip = BooleanField('Use IP for replication')
    replication_dn = StringField('Replication Manager DN', validators=[
        DataRequired(), Regexp(
            '^[a-zA-Z][a-zA-Z ]*[a-zA-Z]$',
            message="Only alphabets and space allowed; cannot end with space.")])  # noqa
    replication_pw = StringField('Replication Manager Password',
                                 validators=[DataRequired()])
    update = SubmitField("Update Configuration")


class SchemaForm(FlaskForm):
    schema = FileField(validators=[
        FileRequired(),
        FileAllowed(
            ['schema'],
            'Upload only Openldap Schema files with .schema extension.')
    ])
    upload = SubmitField("Upload Schema")


class LDIFForm(FlaskForm):
    ldif = FileField(validators=[
        FileRequired(),
        FileAllowed(
            ['ldif'], 'Upload OpenLDAP slapcat exported ldif files only!')
    ])


class KeyRotationForm(FlaskForm):
    interval = IntegerField("Rotation Interval", validators=[DataRequired()])
    type = RadioField(
        "Rotation Type",
        choices=[("oxeleven", "oxEleven",), ("jks", "JKS")],
        validators=[AnyOf(["oxeleven", "jks"])],
    )
    oxeleven_url = StringField("oxEleven URL")
    oxeleven_token = PasswordField("oxEleven Token")
    inum_appliance = StringField("Inum Appliance", validators=[DataRequired()])
    gluu_server = BooleanField(
        'Installed inside chroot-ed Gluu Server', default=True)
    gluu_version = SelectField('Gluu Server Version', choices=[
        ('3.0.1', '3.0.1'),
        ('3.0.2', '3.0.2'),
    ])

    def validate_oxeleven_url(form, field):
        if not field.data and form.type.data == "oxeleven":
            raise ValidationError("This field is required if oxEleven is "
                                  "selected as rotation type")

    def validate_oxeleven_token(form, field):
        if not field.data and form.type.data == "oxeleven":
            raise ValidationError("This field is required if oxEleven is "
                                  "selected as rotation type")


class LoggingServerForm(FlaskForm):
    # mq_host = StringField("Hostname", validators=[DataRequired()])
    # mq_port = IntegerField("Port", validators=[DataRequired()])
    # mq_user = StringField("User", validators=[DataRequired()])
    # mq_password = PasswordField("Password", validators=[DataRequired()])
    # db_host = StringField("Hostname", validators=[DataRequired()])
    # db_port = IntegerField("Port", validators=[DataRequired()])
    # db_user = StringField("User", validators=[DataRequired()])
    # db_password = PasswordField("Password", validators=[DataRequired()])
    url = StringField("URL", validators=[DataRequired(),
                                         URL(require_tld=False)])


class ServerForm(FlaskForm):
    hostname = StringField('Hostname *', validators=[DataRequired()])
    ip = StringField(
        'IP Address *', validators=[DataRequired(), IPAddress()])
    ldap_password = StringField(
        'LDAP Admin Password *', validators=[DataRequired()])
    primary_server = BooleanField('This is primary LDAP Server')


class TestUser(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    email = StringField('Email', validators=[
        DataRequired(), Email("Please enter valid email address.")])


class InstallServerForm(FlaskForm):
    hostname = StringField('Hostname *', validators=[DataRequired()])
    ip = StringField(
        'IP Address *', validators=[DataRequired(), IPAddress()])
    ldap_password = StringField(
        'LDAP Admin Password *', validators=[DataRequired()])

    countryCode = StringField(
        'Two Letter Country Code *', validators=[Length(min=2, max=2),
                                                 DataRequired()])
    state = StringField('Two Letter State Code *',
                        validators=[Length(min=2, max=2), DataRequired()])
    city = StringField('City *', validators=[DataRequired()])
    orgName = StringField('Organization Name *', validators=[DataRequired()])
    admin_email = StringField('Admin E-mail *', validators=[DataRequired()])
