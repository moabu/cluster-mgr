import glob
import os
import jinja2

try:
    from flask_wtf import FlaskForm
except ImportError:
    from flask_wtf import Form as FlaskForm
try:
    from markupsafe import Markup
except ImportError:
    from jinja2 import Markup

from wtforms import StringField, SelectField, BooleanField, IntegerField, \
    PasswordField, RadioField, SubmitField, validators, TextAreaField, \
    HiddenField
from wtforms.validators import DataRequired, AnyOf, \
    ValidationError, URL, IPAddress, Email, Length, Optional
from flask_wtf.file import FileField, FileRequired, FileAllowed

from clustermgr.config import Config

from clustermgr.core.utils import is_hostname_resolved

class AppConfigForm(FlaskForm):
    versions = [
                '4.4.0',
                'nochroot-4.4.0',
                '4.3.1',
                'nochroot-4.3.1',
                ]
    gluu_version = SelectField('Gluu Server Version',
                               choices=[(v, v) for v in versions])

    replication_pw = PasswordField('Replication Manager Password', validators=[
        DataRequired(), validators.EqualTo(
            'replication_pw_confirm', message='Passwords must match')])

    replication_pw_confirm = PasswordField('Re-enter Password', validators=[DataRequired()])
        
    nginx_host = StringField('Load Balancer Hostname', validators=[DataRequired()])
    nginx_ip = StringField('Load Balancer IP Address', validators=[DataRequired()])
    nginx_ssh_port = StringField('Load Balancer SSH Port', default=22)

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

    external_load_balancer = BooleanField('This is external load balancer')
    #cache_host = StringField('Cache Proxy Hostname', validators=[DataRequired()])
    #cache_ip = StringField('Cache Proxy IP Address', validators=[DataRequired()])
    use_ldap_cache = BooleanField('Use LDAP Cache')
    update = SubmitField("Update Configuration")
    offline = BooleanField('Offline installation')
    gluu_archive = SelectField('Gluu archive', choices = [])
    
    ldap_cache_clean_period = SelectField('LDAP Cache Entries Cleanup Period', 
            choices = [("1","1 min"),("5", "5 mins"), ("10", "10 mins"), ("30", "30 mins")]
            )

    def validate_nginx_host(form, field):
        is_resolved = is_hostname_resolved(field.data)
        if is_resolved:
            raise ValidationError(is_resolved)

    def validate_replication_pw(form, field):
        for c in '\\\'"':
            if c in field.data:
                raise ValidationError("Use of {} prohibited".format(c))

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


class KeyRotationForm(FlaskForm):
    interval = IntegerField("Rotation Interval", validators=[DataRequired()])
    enabled = RadioField(
        "Enable Rotation",
        choices=[("true", "Yes"), ("false", "No")],
    )
    backup =  BooleanField('Backup old keys', default=True)
    
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

    ssh_port = IntegerField("SSH Port *", default=22)

    def validate_hostname(form, field):
        is_resolved = is_hostname_resolved(field.data)
        if is_resolved:
            raise ValidationError(is_resolved)

    def validate_ldap_password(form, field):
        for c in '\\\'"':
            if c in field.data:
                raise ValidationError("Use of {} prohibited".format(c))

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

    installLdap = BooleanField('Install LDAP', default=True)
    installOxAuth = BooleanField('Install oxAuth', default=True)
    installOxTrust = BooleanField('Install oxTrust', default=True)
    installHTTPD = BooleanField('Install Apache 2 web server', default=True)
    #installJce = BooleanField('Install Amazon-Corretto Java')
    installSaml = BooleanField('Install Shibboleth SAML IDP')
    installOxAuthRP = BooleanField('Install oxAuth RP')
    installPassport = BooleanField('Install Passport')
    installOxd = BooleanField('Install Oxd')
    oxd_use_gluu_storage = BooleanField('Use Gluu Storage for Oxd')
    installCasa = BooleanField('Install Casa')
    
    gluu_licence = SelectField(
        "Do you acknowledge that use of the Gluu Server is under the MIT license?",
        choices=[('no', "No"), ('yes', "Yes")]
    )

    def validate_gluu_licence(form, field):
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
    public_key = TextAreaField("Public Key", validators=[DataRequired()],
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
    
    license_confirm = BooleanField(Markup('Check here to indicate that you have read and agree to the terms of the <a target="_blank" href="https://github.com/GluuFederation/cluster-mgr/blob/master/LICENSE">GLUU-SUPPORT license</a>') , validators=[DataRequired()])

    login = SubmitField("Sign up")

class WizardStep1(FlaskForm):
    current_hostname = StringField('Current Hostname of Standalone System *', validators=[DataRequired()])
    new_hostname = StringField('New Hostname *', validators=[DataRequired()])
    ip = StringField(
        'Current IP Address of Standalone System *', validators=[DataRequired(), IPAddress()])
    ssh_port = IntegerField("SSH Port of Server", default="22", validators=[DataRequired()])
    nginx_ip = StringField(
        'Load Balancer IP Address *', validators=[DataRequired(), IPAddress()])
    nginx_ssh_port = IntegerField("SSH Port of load balancer", default="22", validators=[DataRequired()])
    
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
    redis_password = StringField("Redis Password")
    stunnel_port = IntegerField("Stunnel Port", validators=[DataRequired()])
    ssh_port = IntegerField("SSH Port", default="22", validators=[DataRequired()])


class OxdConfigForm(FlaskForm):
    oxd_server = StringField("Oxd Server", validators=[DataRequired()])
    op_host = StringField("OP Host", validators=[DataRequired()])
    oxd_id = StringField("Oxd ID", validators=[DataRequired()])
    client_id = StringField("Client ID", validators=[DataRequired()])
    client_secret = StringField("Client Secret", validators=[DataRequired()])
        
