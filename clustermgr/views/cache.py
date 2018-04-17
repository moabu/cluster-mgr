"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
import os

from flask import Blueprint, render_template, url_for, flash, redirect, \
    jsonify, request, session

from flask_login import login_required

from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cache import get_cache_methods, install_cache_components, \
    configure_cache_cluster, restart_services
from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.license import license_required
from clustermgr.core.remote import RemoteClient


cache_mgr = Blueprint('cache_mgr', __name__, template_folder='templates')
cache_mgr.before_request(prompt_license)
cache_mgr.before_request(license_required)
cache_mgr.before_request(license_reminder)


def get_redis_config(f):
    addr_list = []

    for l in f:
        ls=l.strip()
        if ls:
            if ls.startswith('connect'):
                n = ls.find('=')
                addr_port = ls[n+1:].strip()
                addr_port_s = addr_port.split(':')
                addr_list.append(addr_port_s[0])

    return addr_list

@cache_mgr.route('/')
@login_required
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

    c = RemoteClient(host=appconf.nginx_host, ip=appconf.nginx_ip)
    
    try:
        c.startup()
    except:
        flash("SSH connection can't be established to load balancer", "warning")

    result = c.get_file('/etc/stunnel/stunnel.conf')
    
    installed_servers = []

    if result[0]:
        installed_servers = get_redis_config(result[1])
    
    for server in servers:
        if server.ip in installed_servers:
            server.redis = True
        else:
            server.redis = False

    version = int(appconf.gluu_version.replace(".", ""))
    if version < 311:
        flash("Cache Management is available only for clusters configured with"
              " Gluu Server version 3.1.1 and above", "danger")
        return redirect(url_for('index.home'))

    return render_template('cache_index.html', servers=servers)


@cache_mgr.route('/refresh_methods')
@login_required
def refresh_methods():
    task = get_cache_methods.delay()
    return jsonify({'task_id': task.id})



@cache_mgr.route('/change/', methods=['GET', 'POST'])
@login_required
def change():
    
    servers = Server.query.all()

    method = 'STANDALONE'

    if not servers:
        return redirect(url_for('cache_mgr.index'))
    
    task = install_cache_components.delay(method)
    return render_template('cache_logger.html', method=method, step=1,
                           task_id=task.id, servers=servers,
                           )


@cache_mgr.route('/configure/<method>/')
@login_required
def configure(method):

    task = configure_cache_cluster.delay(method)
    servers = Server.query.all()

    return render_template('cache_logger.html', method=method, servers=servers,
                           step=2, task_id=task.id)


@cache_mgr.route('/finish_clustering/<method>/')
@login_required
def finish_clustering(method):
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    task = restart_services.delay(method)
    return render_template('cache_logger.html', servers=servers, step=3,
                           task_id=task.id)


@cache_mgr.route('/status/')
@login_required
def get_status():
    status={'redis':{}, 'stunnel':{}}
    servers = Server.query.all()
    
    check_cmd = 'python -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);print s.connect_ex((\'{0}\', {1}))"'
    
    for server in servers:
        r = os.popen3(check_cmd.format(server.ip, 7777))
        stat = r[1].read().strip()
        if stat == '0':
            status['stunnel'][server.id]=True
        else:
            status['stunnel'][server.id]=False
            
        c = RemoteClient(host=server.hostname, ip=server.ip)
        try:
            c.startup()
        except:
            status['stunnel'][server.id] = False
            
        r = c.run(check_cmd.format('localhost', 6379))
        stat = r[1].strip()

        if stat == '0':
            status['redis'][server.id]=True
        else:
            status['redis'][server.id]=False
        
            
    return jsonify(status)

