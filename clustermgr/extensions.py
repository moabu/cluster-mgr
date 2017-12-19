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


db = SQLAlchemy()
csrf = CSRFProtect()
migrate = Migrate()
wlogger = WebLogger()
celery = Celery('clustermgr.application', backend=Config.CELERY_RESULT_BACKEND,
                broker=Config.CELERY_BROKER_URL
                )
login_manager = LoginManager()
mailer = Mail()
