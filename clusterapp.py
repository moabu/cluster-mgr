import click

from clustermgr.application import create_app, init_celery
from clustermgr.extensions import celery
from flask.cli import FlaskGroup


def create_cluster_app(info):
    return create_app()


@click.group(cls=FlaskGroup, create_app=create_cluster_app)
def cli():
    """This is a management script for the wiki application"""
    pass

def run_celery():
    from celery.bin import worker
    app = create_app()
    init_celery(app, celery)
    runner = worker.worker(app=celery)
    config = {"loglevel": "INFO"}
    runner.run(**config)


if __name__ == "__main__":
    cli()
