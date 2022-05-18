#!/usr/bin/python3

#logging credit: ivanleoncz <https://gist.github.com/ivanlmj/dbf29670761cbaed4c5c787d9c9c006b>

import os
import traceback
import click
import multiprocessing as mp
import gunicorn.app.base

from flask.cli import FlaskGroup
from celery.apps import beat
from celery.apps import worker

from clustermgr.application import create_app, init_celery
from clustermgr.extensions import celery

from time import strftime
from clustermgr.models import AppConfiguration

from flask import request, render_template
from flask_migrate import upgrade as db_upgrade
from clustermgr.core.clustermgr_logging import sys_logger as logger

os.environ['NEW_UUID'] = os.urandom(16).hex()

app = create_app()

init_celery(app, celery)

def create_cluster_app(info=None):
    return create_app()


@click.group(cls=FlaskGroup, create_app=create_cluster_app)
def cli():
    """This is a management script for the wiki application"""
    pass


def run_celerybeat():
    """Function that starts the scheduled tasks in celery using celery.beat"""
    print("Starting Celery Beat")
    config = {
        "app": celery,
        "loglevel": "INFO",
        "schedule": os.path.join(celery.conf["DATA_DIR"], "celerybeat-schedule"),
    }
    runner = beat.Beat(**config)
    runner.run()


def run_celery_worker():
    print("Starting Celery Worker")
    """Function that starts the celery worker to run all the tasks"""
    config = {
        "loglevel": "DEBUG",
        "logfile": os.path.join(app.config['LOGS_DIR'], 'celery.log'),
        "app": celery,
    }

    celery_worker = worker.Worker(**config)
    celery_worker.setup_logging()
    celery_worker.start()

def run_gunicorn_web_server():
    print("Starting Gunicorn Web Server")

    options = {
        'bind': '%s:%s' % ('127.0.0.1', '5000'),
        'workers': 2,
        'loglevel': 'debug',
        'capture_output': True,
        'accesslog': os.path.join(app.config['LOGS_DIR'], 'gunicorn-access.log'),
        'errorlog': os.path.join(app.config['LOGS_DIR'], 'gunicorn-debug.log'),
    }

    StandaloneApplication(app, options).run()

class StandaloneApplication(gunicorn.app.base.BaseApplication):

    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items()
                  if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


@cli.command()
def run_clustermgr():

    db_upgrade()

    p_cb = mp.Process(target=run_celerybeat, args=())
    p_cb.start()
    
    p_cw = mp.Process(target=run_celery_worker, args=())
    p_cw.start()

    p_ga = mp.Process(target=run_gunicorn_web_server, args=())
    p_ga.start()
    p_ga.join()


@app.before_request
def before_request():
    try:
        appconf = AppConfiguration.query.first()
        if appconf:
            app.jinja_env.globals['external_load_balancer'] = appconf.external_load_balancer
    except:
        print("Database is not ready")


@app.after_request
def after_request(response):
    """ Logging after every request. """
    # This avoids the duplication of registry in the log,
    # since that 500 is already logged via @app.errorhandler.
    if response.status_code != 500:
        
        if not request.full_path.startswith('/log/'):
            ts = strftime('[%Y-%b-%d %H:%M]')
            logger.info('%s %s %s %s %s %s',
                          ts,
                          request.remote_addr,
                          request.method,
                          request.scheme,
                          request.full_path,
                          response.status)
    return response


@app.errorhandler(Exception)
def exceptions(e):
    
    """ Logging after every Exception. """
    ts = strftime('[%Y-%b-%d %H:%M]')
    tb = traceback.format_exc()

    logger.error('%s %s %s %s %s 5xx INTERNAL SERVER ERROR\n%s',
                  ts,
                  request.remote_addr,
                  request.method,
                  request.scheme,
                  request.full_path,
                  tb)

    return render_template('exception.html', tb=tb)



if __name__ == "__main__":
    cli()
