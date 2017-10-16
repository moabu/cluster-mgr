"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
from flask import Blueprint, render_template, url_for, flash, redirect, \
    request, session, jsonify

from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cache import get_cache_methods, install_redis_stunnel, \
    configure_cache_cluster, finish_cluster_setup


cache_mgr = Blueprint('cache_mgr', __name__, template_folder='templates')


@cache_mgr.route('/')
def index():
    servers = Server.query.all()
    appconf = AppConfiguration.query.first()
    if not appconf:
        flash("The application needs to be configured first. Kindly set the ",
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))
    version = int(appconf.gluu_version.replace(".", ""))
    return render_template('cache_index.html', servers=servers,
                           version=version)


@cache_mgr.route('/refresh_methods')
def refresh_methods():
    task = get_cache_methods.delay()
    return jsonify({'task_id': task.id})


@cache_mgr.route('/change/', methods=['GET', 'POST'])
def change():
    servers = Server.query.all()
    if request.method == 'POST':
        method = request.form.get('method')
        server_list = request.form.getlist('servers')

        # Validate form input
        if not method:
            flash("No clustering method has been selected. Kindly select a "
                  "clustering method", "danger")
        if not server_list:
            flash("No servers have been selected. Kindly select the servers "
                  "to form the cluster", "danger")
        if not method or not server_list:
            return render_template('cache_change.html', servers=servers)

        # assert the clustering conditions
        if len(server_list) < 3 and method == 'CLUSTER':
            flash("Redis cluster cannot be setup with less than 3 hosts. "
                  "Select SHARDED instead.", "warning")
            return render_template('cache_change.html', servers=servers)

        session["cache_method"] = method
        server_list = [int(sid) for sid in server_list]
        task = install_redis_stunnel.delay(server_list)
        selected_servers = Server.query.filter(Server.id.in_(server_list)).all()
        return render_template('cache_logger.html', method=method, step=2,
                               task_id=task.id, servers=selected_servers)
    return render_template('cache_change.html', servers=servers)

@cache_mgr.route('/configure/<method>/')
def configure(method):
    task = configure_cache_cluster.delay(method)
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    return render_template('cache_logger.html', method=method, servers=servers,
                           step=3, task_id=task.id)


@cache_mgr.route('/finish_clustering/<method>/')
def finish_clustering(method):
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    task = finish_cluster_setup.delay(method)
    return render_template('cache_logger.html', servers=servers, step=4,
                           task_id=task.id)
