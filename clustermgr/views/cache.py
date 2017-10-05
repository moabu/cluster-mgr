"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
from flask import Blueprint, render_template, url_for, flash, redirect, \
    request, session, jsonify

from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cache import get_cache_methods, install_redis_stunnel


cache_mgr = Blueprint('cache_mgr', __name__, template_folder='templates')


@cache_mgr.route('/')
def index():
    servers = Server.query.all()
    appconf = AppConfiguration.query.first()
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
                  "Select SHARDING instead.", "warning")
            return render_template('cache_change.html', servers=servers)

        session["cache_method"] = method
        server_list = [int(sid) for sid in server_list]
        task = install_redis_stunnel.delay(server_list)
        return render_template('cache_install.html', method=method,
                               task_id=task.id)
    return render_template('cache_change.html', servers=servers)
