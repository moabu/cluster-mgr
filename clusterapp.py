#!/usr/bin/python

#logging credit: ivanleoncz <https://gist.github.com/ivanlmj/dbf29670761cbaed4c5c787d9c9c006b>

import os
import traceback
import click
from flask.cli import FlaskGroup
from celery.bin import beat
from celery.bin import worker

from clustermgr.application import create_app, init_celery
from clustermgr.extensions import celery


from clustermgr.core.utils import logger
from time import strftime
from clustermgr.models import AppConfiguration

from flask import request, render_template

app = create_app()

init_celery(app, celery)

def create_cluster_app(info):
    return create_app()


@click.group(cls=FlaskGroup, create_app=create_cluster_app)
def cli():
    """This is a management script for the wiki application"""
    pass


def run_celerybeat():
    """Function that starts the scheduled tasks in celery using celery.beat"""
    runner = beat.beat(app=celery)
    config = {
        "loglevel": "INFO",
        "schedule": os.path.join(celery.conf["DATA_DIR"], "celerybeat-schedule"),
    }
    runner.run(**config)


def run_celery_worker():
    """Function that starts the celery worker to run all the tasks"""
    runner = worker.worker(app=celery)
    config = {
        "loglevel": "INFO",
    }
    runner.run(**config)

@app.before_request
def before_request():
    try:
        appconf = AppConfiguration.query.first()
        if appconf:
            app.jinja_env.globals['external_load_balancer'] = appconf.external_load_balancer
    except:
        print "Database is not ready"


@app.after_request
def after_request(response):
    """ Logging after every request. """
    # This avoids the duplication of registry in the log,
    # since that 500 is already logged via @app.errorhandler.
    if response.status_code != 500:
        
        if not request.full_path.startswith('/log/'):
            ts = strftime('[%Y-%b-%d %H:%M]')
            logger.error('%s %s %s %s %s %s',
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
