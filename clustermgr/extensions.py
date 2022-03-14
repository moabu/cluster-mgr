import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
from celery import Celery
from flask_login import LoginManager


try:
    from flask_wtf.csrf import CSRFProtect
except ImportError:
    # backward-compatibility
    from flask_wtf.csrf import CsrfProtect as CSRFProtect

from .weblogger import WebLogger
from clustermgr.config import Config
from redislite import Redis

db = SQLAlchemy()
csrf = CSRFProtect()
migrate = Migrate()
wlogger = WebLogger()

Config.CLUSTERMGR_REDIS = Redis(os.path.join(Config.DATA_DIR, 'redis.db'))
Config.CELERY_BROKER_URL = 'redis+socket://' + Config.CLUSTERMGR_REDIS.socket_file

celery = Celery('clustermgr.application', backend=Config.CELERY_BROKER_URL,
                broker=Config.CELERY_BROKER_URL
                )

login_manager = LoginManager()
mailer = Mail()
