"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
from flask import Blueprint, render_template, url_for, flash, redirect, \
    request, session, jsonify

from clustermgr.models import Server
from clustermgr.tasks.cache import get_cache_methods


cache_mgr = Blueprint('cache_mgr', __name__, template_folder='templates')


@cache_mgr.route('/')
def index():
    servers = Server.query.all()
    return render_template('cache_index.html', servers=servers)


@cache_mgr.route('/refresh_methods')
def refresh_methods():
    task = get_cache_methods.delay()
    return jsonify({'task_id': task.id})
