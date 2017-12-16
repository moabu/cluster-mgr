import os

import click
from flask.cli import FlaskGroup
from celery.bin import beat

from clustermgr.application import create_app, init_celery

app = create_app()
celery = init_celery(app)

def create_cluster_app(info):
    return create_app()


@click.group(cls=FlaskGroup, create_app=create_cluster_app)
def cli():
    """This is a management script for the wiki application"""
    pass


def run_celerybeat():
    runner = beat.beat(app=celery)
    config = {
        "loglevel": "INFO",
        "schedule": os.path.join(celery.conf["DATA_DIR"], "celerybeat-schedule"),
    }
    runner.run(**config)


if __name__ == "__main__":
    cli()
