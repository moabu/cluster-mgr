import os
import uuid
from datetime import timedelta

class Config(object):
    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = ''
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    #SQLALCHEMY_ECHO = True
    #SQLALCHEMY_RECORD_QUERIES = True
    SECRET_KEY = 'prettysecret'
    BASE_DN = 'o=gluu'

    DATA_DIR = os.environ.get(
        "DATA_DIR",
        os.path.join(os.path.expanduser("~"), ".clustermgr4"),
    )

    # The celery broker string to use our redislite server

    OX11_PORT = '8190'
    
    LOGS_DIR = os.path.join(DATA_DIR, 'logs')
    
    if not os.path.exists(DATA_DIR):
        os.mkdir(DATA_DIR)

    if not os.path.exists(LOGS_DIR):
        os.mkdir(LOGS_DIR)
    
    
    LOG_FILE = os.path.join(LOGS_DIR, 'clustermgr.log')
    SSH_LOG_FILE = os.path.join(LOGS_DIR, 'ssh.log')
    SQL_LOG_FILE = os.path.join(LOGS_DIR, 'sql.log')
    WEBLOGGER_LOG_FILE = os.path.join(LOGS_DIR, 'weblogger.log')
    JAVALIBS_DIR = os.path.join(DATA_DIR, "javalibs")
    APP_INSTANCE_DIR = os.path.join(DATA_DIR, "instance")
    SCHEMA_DIR = os.path.join(DATA_DIR, "schema")
    CERTS_DIR = os.path.join(DATA_DIR, "certs")
    JKS_PATH = os.path.join(CERTS_DIR, "oxauth-keys.jks")
    LDIF_DIR = os.path.join(DATA_DIR, "ldif")
    GLUU_REPO = os.path.join(DATA_DIR, "gluu_repo")

    LICENSE_CONFIG_FILE = os.path.join(DATA_DIR, "license.ini")
    LICENSE_SIGNED_FILE = os.path.join(DATA_DIR, "signed_license")
    LICENSE_VALIDATOR = os.path.join(JAVALIBS_DIR, "oxlicense-validator.jar")
    LICENSE_EMAIL_THRESHOLD_FILE = os.path.join(DATA_DIR, ".license_email")
    LICENSE_ENFORCEMENT_ENABLED = True
    AUTH_CONFIG_FILE = os.path.join(DATA_DIR, "auth.ini")

    beat_schedule = CELERYBEAT_SCHEDULE = {

        'send_reminder_email': {
            'task': 'clustermgr.tasks.license.send_reminder_email',
            'schedule': 60 * 60 * 24,
            'args': (),
        },

        'schedule_key_rotation': {
            'task': 'clustermgr.tasks.keyrotation.schedule_key_rotation',
            'schedule': 60 * 60 * 1,
            'args': (),
        },

        'get_remote_stats': {
            'task': 'clustermgr.tasks.get_remote_stats.get_remote_stats',
            'schedule': 60 * 5,
            'args': (),
        },

        'check_latest_version': {
            'task': 'clustermgr.tasks.cluster.check_latest_version',
            'schedule': 60 * 60 * 6,
            'args': (),
        },


    }

    MAIL_SERVER = "localhost"
    MAIL_PORT = 25
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    MAIL_USERNAME = None
    MAIL_PASSWORD = None
    MAIL_DEFAULT_SENDER = ("Cluster Manager", "no-reply@localhost")
    MAIL_DEFAULT_RECIPIENT_NAME = "Admin"
    MAIL_DEFAULT_RECIPIENT_ADDRESS = ["admin@localhost"]

    INFLUXDB_LOGGING_DB = "gluu_logs"
    SUPPORTED_OS = ['CentOS 8','CentOS 7', 'RHEL 7', 'RHEL 8', 'Ubuntu 18', 'Ubuntu 20']

class ProductionConfig(Config):
    SECRET_KEY = ''
    SQLALCHEMY_DATABASE_URI = "sqlite:///{}/clustermgr.db".format(Config.DATA_DIR)


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///{}/clustermgr.dev.db".format(Config.DATA_DIR)
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    LICENSE_ENFORCEMENT_ENABLED = False
    INFLUXDB_LOGGING_DB = "gluu_logs_dev"


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    LICENSE_ENFORCEMENT_ENABLED = False
    INFLUXDB_LOGGING_DB = "gluu_logs_test"
