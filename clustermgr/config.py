import os
from datetime import timedelta
import uuid

class Config(object):
    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = ''
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'prettysecret'
    BASE_DN = 'o=gluu'
    CELERY_BROKER_URL = 'redis://localhost:6379'
    CELERY_RESULT_BACKEND = 'redis://localhost:6379'
    REDIS_HOST = 'localhost'
    REDIS_PORT = 6379
    REDIS_LOG_DB = 0
    OX11_PORT = '8190'
    DATA_DIR = os.environ.get(
        "DATA_DIR",
        os.path.join(os.path.expanduser("~"), ".clustermgr"),
    )
    
    LOGS_DIR = os.path.join(DATA_DIR, 'logs')
    
    if not os.path.exists(DATA_DIR):
        os.mkdir(DATA_DIR)

    if not os.path.exists(LOGS_DIR):
        os.mkdir(LOGS_DIR)
    
    
    LOG_FILE = os.path.join(LOGS_DIR, 'clustermgr.log')
    JAVALIBS_DIR = os.path.join(DATA_DIR, "javalibs")
    APP_INSTANCE_DIR = os.path.join(DATA_DIR, "instance")
    SCHEMA_DIR = os.path.join(DATA_DIR, "schema")
    SLAPDCONF_DIR = os.path.join(DATA_DIR, "slapdconf")
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
    OXD_CLIENT_CONFIG_FILE = os.path.join(DATA_DIR, "oxd-client.ini")

    CELERYBEAT_SCHEDULE = {

        'send_reminder_email': {
            'task': 'clustermgr.tasks.license.send_reminder_email',
            'schedule': timedelta(seconds=60 * 60 * 24),
            'args': (),
        },

        'schedule_key_rotation': {
            'task': 'clustermgr.tasks.keyrotation.schedule_key_rotation',
            'schedule': timedelta(seconds=60 * 60 * 1),
            'args': (),
        },

        'get_remote_stats': {
            'task': 'clustermgr.tasks.get_remote_stats.get_remote_stats',
            'schedule': timedelta(seconds=60 * 5),
            'args': (),
        },


        'check_latest_version': {
            'task': 'clustermgr.tasks.cluster.check_latest_version',
            'schedule': timedelta(seconds=60 * 60 * 6),
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

    SUPPORTED_OS = ['CentOS 7', 'RHEL 7', 'Ubuntu 16']


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
