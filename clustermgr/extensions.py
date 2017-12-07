from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail

try:
    from flask_wtf.csrf import CSRFProtect
except ImportError:
    # backward-compatibility
    from flask_wtf.csrf import CsrfProtect as CSRFProtect

from .weblogger import WebLogger


db = SQLAlchemy()
csrf = CSRFProtect()
migrate = Migrate()
wlogger = WebLogger()
mailer = Mail()
