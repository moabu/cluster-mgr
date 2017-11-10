"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
from flask import Blueprint, render_template, url_for, flash, redirect, \
    request, session, jsonify

from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cache import get_cache_methods, install_cache_components, \
    configure_cache_cluster, restart_services


cache_mgr = Blueprint('cache_mgr', __name__, template_folder='templates')


@cache_mgr.route('/')
def index():
    servers = Server.query.all()
    appconf = AppConfiguration.query.first()
    if not appconf:
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    if not servers:
        flash("Add servers to the cluster before attempting to manage cache",
              "warning")
        return redirect(url_for('index.home'))

    version = int(appconf.gluu_version.replace(".", ""))
    if version < 311:
        flash("Cache Management is available only for clusters configured with"
              " Gluu Server version 3.1.1 and above", "danger")
        return redirect(url_for('index.home'))

    return render_template('cache_index.html', servers=servers)


@cache_mgr.route('/refresh_methods')
def refresh_methods():
    task = get_cache_methods.delay()
    return jsonify({'task_id': task.id})


@cache_mgr.route('/change/', methods=['GET', 'POST'])
def change():
    servers = Server.query.all()
    method = 'STANDALONE'
    task = install_cache_components.delay(method)
    return render_template('cache_logger.html', method=method, step=1,
                           task_id=task.id, servers=servers)


@cache_mgr.route('/configure/<method>/')
def configure(method):
    task = configure_cache_cluster.delay(method)
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    return render_template('cache_logger.html', method=method, servers=servers,
                           step=2, task_id=task.id)


@cache_mgr.route('/finish_clustering/<method>/')
def finish_clustering(method):
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    task = restart_services.delay(method)
    return render_template('cache_logger.html', servers=servers, step=3,
                           task_id=task.id)
