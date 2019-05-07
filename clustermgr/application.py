# -*- coding: utf-8 -*-
import os
import re

from flask import Flask
from flask import url_for
from flask import request

from clustermgr.extensions import db, csrf, migrate, wlogger, \
    login_manager, mailer
from .core.license import license_manager
from clustermgr.models import AppConfiguration
from . import __version__


def init_celery(app, celery):
    celery.conf.update(app.config)
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)

    celery.Task = ContextTask


def create_app():
    app = Flask(__name__)

    # Configure the flask application
    cfg = "clustermgr.config.DevelopmentConfig"  # default
    app_mode = os.environ.get("APP_MODE")        # override using env var
    if app_mode == "prod":
        cfg = "clustermgr.config.ProductionConfig"
    elif app_mode == "test":
        cfg = "clustermgr.config.TestConfig"
    app.config.from_object(cfg)
    app.instance_path = app.config["APP_INSTANCE_DIR"]
    # allow custom config
    app.config.from_pyfile(
        os.path.join(app.instance_path, "config.py"),
        silent=True,
    )

    # Initialize the extensions
    db.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(__file__),
                                                     "migrations"))
    wlogger.init_app(app)
    license_manager.init_app(app, "license.index")
    login_manager.init_app(app)
    mailer.init_app(app)

    # setup the instance's working directories
    if not os.path.isdir(app.config['SCHEMA_DIR']):
        os.makedirs(app.config['SCHEMA_DIR'])
    if not os.path.isdir(app.config['SLAPDCONF_DIR']):
        os.makedirs(app.config['SLAPDCONF_DIR'])
    if not os.path.isdir(app.config['LDIF_DIR']):
        os.makedirs(app.config['LDIF_DIR'])
    if not os.path.isdir(app.config['CERTS_DIR']):
        os.makedirs(app.config['CERTS_DIR'])
    if not os.path.isdir(app.instance_path):
        os.makedirs(app.instance_path)
    if not os.path.isdir(app.config['GLUU_REPO']):
        os.makedirs(app.config['GLUU_REPO'])
    

    # register blueprints
    from clustermgr.views.index import index
    from clustermgr.views.server import server_view
    from clustermgr.views.cluster import cluster
    from clustermgr.views.monitoring import monitoring
    from clustermgr.views.cache import cache_mgr
    from clustermgr.views.license import license_bp
    from clustermgr.views.auth import auth_bp
    from clustermgr.views.logserver import log_mgr
    from clustermgr.views.keyrotation import keyrotation_bp
    from clustermgr.views.wizard import wizard
    from clustermgr.views.attributes import attributes
    from clustermgr.views.operations import operations


    

    app.register_blueprint(index, url_prefix="")
    app.register_blueprint(server_view, url_prefix="/server")
    app.register_blueprint(cluster, url_prefix="/cluster")
    app.register_blueprint(log_mgr, url_prefix="/logging")
    app.register_blueprint(cache_mgr, url_prefix="/cache")
    app.register_blueprint(license_bp, url_prefix="/license")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(monitoring, url_prefix="/monitoring")
    app.register_blueprint(keyrotation_bp, url_prefix="/keyrotation")
    app.register_blueprint(wizard, url_prefix="/wizard")
    app.register_blueprint(attributes, url_prefix="/attributes")
    app.register_blueprint(operations, url_prefix="/operations")




    @app.context_processor
    def hash_processor():
        def hashed_url(filepath):
            directory, filename = filepath.rsplit('/')
            name, extension = filename.rsplit(".")
            folder = os.path.join(app.root_path, 'static', directory)
            files = os.listdir(folder)
            for f in files:
                regex = name + "\.[a-z0-9]+\." + extension
                if re.match(regex, f):
                    return os.path.join('/static', directory, f)
            return os.path.join('/static', filepath)
        return dict(hashed_url=hashed_url)

    def url_for_next_page(page):
        args = {k: v for k, v in request.values.iteritems()}

        try:
            page = int(page)
        except ValueError:
            page = 1

        args['page'] = int(page) + 1
        return url_for(request.endpoint, **args)

    def url_for_prev_page(page):
        args = {k: v for k, v in request.values.iteritems()}

        try:
            page = int(page)
        except ValueError:
            page = 1

        if page < 1:
            page = 1
        elif page == 1:
            page = 2
        args['page'] = page - 1
        return url_for(request.endpoint, **args)

    app.jinja_env.globals['url_for_next_page'] = url_for_next_page
    app.jinja_env.globals['url_for_prev_page'] = url_for_prev_page
    app.jinja_env.globals['version'] = __version__
    app.jinja_env.globals['latest_version'] = ''
    app.jinja_env.globals['SUPPORTED_OS'] = app.config['SUPPORTED_OS']

    @app.before_request
    def before_request():
        appconfig = AppConfiguration.query.first()

        use_ldap_cache = False

        if appconfig:
            if appconfig.gluu_version >= '3.1.4':
                use_ldap_cache = appconfig.use_ldap_cache
                
            app.jinja_env.globals['latest_version'] = appconfig.latest_version

        app.jinja_env.globals['use_ldap_cache'] = use_ldap_cache

    return app
