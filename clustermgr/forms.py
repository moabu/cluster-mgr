import os
import glob

try:
    from flask_wtf import FlaskForm
except ImportError:
    from flask_wtf import Form as FlaskForm
from wtforms import StringField, SelectField, BooleanField, IntegerField, \
    PasswordField, RadioField, SubmitField, validators, TextAreaField, \
    HiddenField
from wtforms.validators import DataRequired, AnyOf, \
    ValidationError, URL, IPAddress, Email, Length, Optional
from flask_wtf.file import FileField, FileRequired, FileAllowed

from clustermgr.config import Config

class AppConfigForm(FlaskForm):
    versions = [
                '3.1.6',
                '3.1.5', 
                #'3.1.4', 
                #'3.1.3.1',
                #'3.1.3', 
                #'3.1.2',
                ]
    gluu_version = SelectField('Gluu Server Version',
                               choices=[(v, v) for v in versions])
    # use_ip = BooleanField('Use IP Address in place of Hostname for replication')
    # replication_dn = StringField('Replication Manager DN', validators=[
    #    DataRequired(),
    #    Regexp('^[a-zA-Z][a-zA-Z ]*[a-zA-Z]$',
    #           message="Only alphabets and space allowed; cannot end with space.")])  # noqa
    replication_pw = PasswordField('Replication Manager Password', validators=[
        DataRequired(), validators.EqualTo(
            'replication_pw_confirm', message='Passwords must match')])
    replication_pw_confirm = PasswordField(
        'Re-enter Password', validators=[DataRequired()])
    nginx_host = StringField('Load Balancer Hostname', validators=[DataRequired()])

    nginx_ip = StringField('Load Balancer IP Address', validators=[DataRequired()])
    

    ldap_update_period = SelectField('Service Liveness Status Polling Period',
            choices=[
            
                ('5', '5 secs'), ('10', '10 secs'), 
                ('20', '20 secs'), ('30', '30 secs'),
                ('60', '1 min'), ('120', '2 mins'),
                ('300', '5 mins'), ('600', '10 mins'),
                ('900', '15 mins'), ('1200', '20 mins'),
                
            ],
            default = '300',
            )

    modify_hosts =  BooleanField('Add IP Addresses and hostnames to '
                                '/etc/hosts file on each server')

    external_load_balancer = BooleanField('This is an external load balancer')
    use_ldap_cache = BooleanField('Use LDAP Cache')
    update = SubmitField("Update Configuration")
    offline = BooleanField('Offline installation')
    gluu_archive = SelectField('Gluu archive',
            choices = []
            )

class SchemaForm(FlaskForm):
    schema = FileField(validators=[
        FileRequired(),
        FileAllowed(
            ['schema', 'ldif'],
            'Upload only schema files with .schema or .lidf extension.')
    ])
    upload = SubmitField("Upload Schema")


class SetupPropertiesLastForm(FlaskForm):
    setup_properties = FileField(validators=[FileRequired()])
    upload = SubmitField("Upload Setup Properties")


class LDIFForm(FlaskForm):
    ldif = FileField(validators=[
        FileRequired(),
        FileAllowed(
            ['ldif'], 'Upload OpenLDAP slapcat exported ldif files only!')
    ])


class KeyRotationForm(FlaskForm):
    interval = IntegerField("Rotation Interval", validators=[DataRequired()])
    enabled = RadioField(
        "Enable Rotation",
        choices=[("true", "Yes"), ("false", "No")],
    )
    # type = RadioField(
    #     "Backend Type",
    #     choices=[("jks", "JKS")],
    #     validators=[AnyOf(["jks"])],
    # )
    # inum_appliance = StringField("Inum Appliance", validators=[DataRequired()])
    # gluu_server = BooleanField(
    #     'Installed inside chroot-ed Gluu Server', default=True)
    # gluu_version = SelectField('Gluu Server Version', choices=[
    #     ('3.0.1', '3.0.1'),
    #     ('3.0.2', '3.0.2'),
    # ])

    # def validate_oxeleven_url(form, field):
    #     if not field.data and form.type.data == "oxeleven":
    #         raise ValidationError("This field is required if oxEleven is "
    #                               "selected as rotation type")

    # def validate_oxeleven_token(form, field):
    #     if not field.data and form.type.data == "oxeleven":
    #         raise ValidationError("This field is required if oxEleven is "
    #                               "selected as rotation type")


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
    ldap_password = PasswordField(
        'LDAP Admin Password *', validators=[
            DataRequired(),
            validators.EqualTo('ldap_password_confirm',
                               message='Passwords must match')
        ])
    ldap_password_confirm = PasswordField(
        'Re-enter LDAP Admin Password *', validators=[DataRequired()])


class TestUser(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    email = StringField('Email', validators=[
        DataRequired(), Email("Please enter valid email address.")])


class InstallServerForm(FlaskForm):
    hostname = StringField('Hostname *', validators=[DataRequired()])
    ip_address = StringField(
        'IP Address *', validators=[DataRequired(), IPAddress()])
    ldap_password = StringField(
        'LDAP Admin Password *', validators=[DataRequired()])
    application_max_ram = IntegerField("Max RAM to be used by Gluu Server (MB)", default=3072)
    countryCode = StringField(
        'Two Letter Country Code *', validators=[Length(min=2, max=2),
                                                 DataRequired()])
    state = StringField('State Code')
    city = StringField('City *', validators=[DataRequired()])
    orgName = StringField('Organization Name *', validators=[DataRequired()])
    admin_email = StringField('Admin E-mail *', validators=[DataRequired()])
    #inumOrg = StringField("inumOrg * (Please don't change this unless you know what you do)", validators=[DataRequired()])
    #inumAppliance = StringField("inumAppliance * (Please don't change this unless you know what you do)", validators=[DataRequired()])

    installOxAuth = BooleanField('Install oxAuth', default=True)
    installOxTrust = BooleanField('Install oxTrust', default=True)
    installLDAP = BooleanField('Install LDAP', default=True)
    installHTTPD = BooleanField('Install Apache 2 web server', default=True)
    installJce = BooleanField('Install JCE 1.8')
    installSaml = BooleanField('Install Shibboleth SAML IDP')
    installOxAuthRP = BooleanField('Install oxAuth RP')
    installPassport = BooleanField('Install Passport')

    ldap_type = RadioField(
        "Ldap Type",
        choices=[
            ("opendj", "OpenDJ",),
            ("wrends", "Gluu WrenDS")
        ],
        validators=[AnyOf(["opendj", "wrends"])],
        default='opendj'
    )

    gluu_licence = SelectField(
        "Do you acknowledge that use of the Gluu Server is under the MIT license?",
        choices=[('no', "No"), ('yes', "Yes")]
    )
    oracle_licence = SelectField(
        "You must accept the Oracle Binary Code "
        "License Agreement for the Java SE Platform Products to "
        "download this software. Accept License Agreement?",
        choices=[('no', "No"), ('yes', "Yes")]
    )

    def validate_gluu_licence(form, field):
        if not field.data == 'yes':
            raise ValidationError("Can't proceed without accepting licence.")

    def validate_oracle_licence(form, field):
        if not field.data == 'yes':
            raise ValidationError("Can't proceed without accepting licence.")


def replace_pubkey_whitespace(value):
    if value is not None and hasattr(value, "replace"):
        return value.replace(" ", "")
    return value


class LicenseSettingsForm(FlaskForm):
    license_id = StringField("License ID", validators=[DataRequired()])
    license_password = StringField("License Password", validators=[DataRequired()])
    public_password = StringField("Public Password", validators=[DataRequired()])
    public_key = StringField("Public Key", validators=[DataRequired()],
                             filters=[replace_pubkey_whitespace])
    update = SubmitField("Update")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    login = SubmitField("Login")


class LicenseAckForm(FlaskForm):
    accept = SubmitField("Accept")
    decline = SubmitField("Decline")


class FSReplicationPathsForm(FlaskForm):
    fs_paths = TextAreaField()
    update = SubmitField("Install File System Replication")


class LogSearchForm(FlaskForm):
    type = SelectField("Type", choices=[
        ("", ""),  # all types
        ("opendj", "OpenDJ"),
        ("oxauth", "oxAuth"),
        ("oxtrust", "oxTrust"),
        ("httpd", "HTTPD"),
        ("redis", "Redis"),
    ])
    message = StringField("Message")
    host = SelectField("Host", choices=[])
    search = SubmitField("Search")

class SignUpForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[
                                DataRequired(),
                                    validators.EqualTo('passwordconfirm',
                               message='Passwords must match')
                ])
    passwordconfirm = PasswordField("Re-enter Password", validators=[DataRequired()])
    
    license_confirm = BooleanField('Check here to indicate that you have read and agree to the terms of the <a target="_blank" href="https://github.com/GluuFederation/cluster-mgr/blob/master/LICENSE">GLUU-SUPPORT license</a>' , validators=[DataRequired()])
    
    
    
    login = SubmitField("Sign up")

class WizardStep1(FlaskForm):
    current_hostname = StringField('Current Hostname of primary Gluu Server *', validators=[DataRequired()])
    new_hostname = StringField('Load Balancer Hostname *', validators=[DataRequired()])
    ip = StringField(
        'Current IP Address of primary Gluu Server *', validators=[DataRequired(), IPAddress()])
    nginx_ip = StringField('Load Balancer IP Address')
        
    next = SubmitField("Next")

class CacheSettingsForm(FlaskForm):
    redis_port = IntegerField("Redis Port", validators=[DataRequired()], default="6379")
    stunnel_port = IntegerField("Stunnel Port", validators=[DataRequired()], default="8888")
    save = SubmitField("Save Settings")



class LdapSchema(FlaskForm):
    oid = HiddenField('OID')
    names = StringField('Name', validators=[DataRequired()])
    desc = StringField("Description")
    usage = StringField("Usage")
    syntax_len = IntegerField("Maximum Length", validators=[Optional()])
    syntax = SelectField("Syntax", choices=[])
    substr = SelectField("Substring Rule",
                        choices = (('',''),
                          ('caseExactSubstringsMatch', 'caseExactSubstringsMatch'),
                                ('caseIgnoreIA5SubstringsMatch', 'caseIgnoreIA5SubstringsMatch'),
                                ('caseIgnoreListSubstringsMatch', 'caseIgnoreListSubstringsMatch'),
                                ('caseIgnoreSubstringsMatch', 'caseIgnoreSubstringsMatch'),
                                ('numericStringSubstringsMatch', 'numericStringSubstringsMatch'),
                                ('telephoneNumberSubstringsMatch', 'telephoneNumberSubstringsMatch'),
                            ))
            
    equality = SelectField("Equality", choices=(('',''),
                                ('bitStringMatch', 'bitStringMatch'),
                                ('booleanMatch', 'booleanMatch'),
                                ('caseExactIA5Match', 'caseExactIA5Match'),
                                ('caseExactMatch', 'caseExactMatch'),
                                ('caseIgnoreIA5Match', 'caseIgnoreIA5Match'),
                                ('caseIgnoreListMatch', 'caseIgnoreListMatch'),
                                ('caseIgnoreMatch', 'caseIgnoreMatch'),
                                ('directoryStringFirstComponentMatch', 'directoryStringFirstComponentMatch'),
                                ('distinguishedNameMatch', 'distinguishedNameMatch'),
                                ('generalizedTimeMatch', 'generalizedTimeMatch'),
                                ('integerFirstComponentMatch', 'integerFirstComponentMatch'),
                                ('integerMatch', 'integerMatch'),
                                ('keywordMatch', 'keywordMatch'),
                                ('numericStringMatch', 'numericStringMatch'),
                                ('objectIdentifierFirstComponentMatch', 'objectIdentifierFirstComponentMatch'),
                                ('objectIdentifierMatch', 'objectIdentifierMatch'),
                                ('octetStringMatch', 'octetStringMatch'),
                                ('telephoneNumberMatch', 'telephoneNumberMatch'),
                                ('uniqueMemberMatch', 'uniqueMemberMatch'),
                                ))
                                
    ordering = SelectField("Ordering", choices=(('',''),
                            ('caseExactOrderingMatch', 'caseExactOrderingMatch'),
                            ('caseIgnoreOrderingMatch', 'caseIgnoreOrderingMatch'),
                            ('generalizedTimeOrderingMatch', 'generalizedTimeOrderingMatch'),
                            ('integerOrderingMatch', 'integerOrderingMatch'),
                            ('numericStringOrderingMatch', 'numericStringOrderingMatch'),
                            ('octetStringOrderingMatch', 'octetStringOrderingMatch'),
                                ))
    
    
    single_value = BooleanField("Single Valued")
    #obsolete = BooleanField("Obsolete")
    collective = BooleanField("Collective")

class httpdCertificatesForm(FlaskForm):
    httpd_key = TextAreaField('Key')
    httpd_crt = TextAreaField('Crt')
    submit = SubmitField("Submit")


class cacheServerForm(FlaskForm):
    hostname = StringField("Cache Server Hostname", validators=[DataRequired()])
    ip = StringField("Cache Server IP Address", validators=[DataRequired(), IPAddress()])
    install_redis = BooleanField("Install Redis and stunnel", default=True)
