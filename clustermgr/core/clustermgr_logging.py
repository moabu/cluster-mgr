import logging
from logging.handlers import RotatingFileHandler
from logging.config import dictConfig

from flask_login import current_user
from clustermgr.config import Config
from flask import has_request_context, request

class ContextFilter(logging.Filter):
    def filter(self, record):
        try:
            username = current_user.username
        except:
            username = 'SYS'
        record.current_user = username
        return True

logging_configuration = dict(
    version=1,
    disable_existing_loggers=False,
    formatters={
        'default': {'format': '%(asctime)s - %(current_user)s - %(levelname)s - %(message)s'},
    },
    filters={'curent_user': {'()': ContextFilter}},
    handlers={
        'console': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': Config.LOG_FILE,
            'maxBytes': 5*1024*1024,
            'backupCount': 3,
            'formatter': 'default',
            'filters': ['curent_user'],
        }
    },
    root={'handlers': ['console'], 'level': 'INFO'},
)

dictConfig(logging_configuration)
sys_logger = logging.getLogger()

formatter = logging.Formatter('%(asctime)s - %(current_user)s - %(levelname)s - %(message)s')

model_handler = RotatingFileHandler(Config.SQL_LOG_FILE, maxBytes= 5*1024*1024, backupCount=3)
model_handler.setFormatter(formatter)
model_logger = logging.getLogger('model_logger')
model_logger.addFilter(ContextFilter())
model_logger.setLevel(logging.DEBUG)
model_logger.addHandler(model_handler)

remote_handler = RotatingFileHandler(Config.SSH_LOG_FILE, maxBytes= 5*1024*1024, backupCount=3)
remote_handler.setFormatter(formatter)
remote_logger = logging.getLogger('remote_logger')
remote_logger.addFilter(ContextFilter())
remote_logger.setLevel(logging.DEBUG)
remote_logger.addHandler(remote_handler)

web_handler = RotatingFileHandler(Config.WEBLOGGER_LOG_FILE, maxBytes= 5*1024*1024, backupCount=3)
web_handler.setFormatter(formatter)
web_logger = logging.getLogger('web_logger')
web_logger.addFilter(ContextFilter())
web_logger.setLevel(logging.DEBUG)
web_logger.addHandler(web_handler)





