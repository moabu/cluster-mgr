"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
from flask import Blueprint, render_template, url_for, flash, redirect, \
    request, session, jsonify

from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cache import get_cache_methods, setup_redis


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
    if request.method == 'POST':
        heading = "Setting up redis-cluster"
        nextpage = "cache_mgr.index"
        whatNext = "Cache Management"
        method = request.form.get('method')
        task = setup_redis.delay(method)
        return render_template('logger.html', heading=heading, task=task,
                               nextpage=nextpage, whatNext=whatNext)
    return render_template('cache_change.html')
