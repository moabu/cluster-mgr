import os
from datetime import timedelta


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
    JAVALIBS_DIR = os.path.join(DATA_DIR, "javalibs")
    JKS_PATH = os.path.join(DATA_DIR, "oxauth-keys.jks")
    APP_INSTANCE_DIR = os.path.join(DATA_DIR, "instance")
    SCHEMA_DIR = os.path.join(DATA_DIR, "schema")
    SLAPDCONF_DIR = os.path.join(DATA_DIR, "slapdconf")
    CERTS_DIR = os.path.join(DATA_DIR, "certs")
    LDIF_DIR = os.path.join(DATA_DIR, "ldif")

    LICENSE_CONFIG_FILE = os.path.join(DATA_DIR, "license.ini")
    LICENSE_SIGNED_FILE = os.path.join(DATA_DIR, "signed_license")
    LICENSE_VALIDATOR = os.path.join(JAVALIBS_DIR, "oxlicense-validator-3.1.1.jar")
    LICENSE_EMAIL_THRESHOLD_FILE = os.path.join(DATA_DIR, ".license_email")
    LICENSE_ENFORCEMENT_ENABLED = True

    CELERYBEAT_SCHEDULE = {
        'send_reminder_email': {
            'task': 'clustermgr.tasks.all.send_reminder_email',
            'schedule': timedelta(seconds=30.0),
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


class ProductionConfig(Config):
    SECRET_KEY = ''
    DATA_DIR = os.environ.get("DATA_DIR", "/opt/gluu-cluster-mgr")
    JAVALIBS_DIR = os.path.join(DATA_DIR, "javalibs")
    JKS_PATH = os.path.join(DATA_DIR, "oxauth-keys.jks")
    APP_INSTANCE_DIR = os.path.join(DATA_DIR, "instance")
    SCHEMA_DIR = os.path.join(DATA_DIR, "schema")
    SLAPDCONF_DIR = os.path.join(DATA_DIR, "slapdconf")
    SQLALCHEMY_DATABASE_URI = "sqlite:///{}/clustermgr.db".format(DATA_DIR)


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///{}/clustermgr.dev.db".format(
        Config.DATA_DIR)
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    LICENSE_ENFORCEMENT_ENABLED = False


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    LICENSE_ENFORCEMENT_ENABLED = False
