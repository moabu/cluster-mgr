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
from clustermgr.core.utils import get_redis_config
from clustermgr.forms import CacheSettingsForm

cache_mgr = Blueprint('cache_mgr', __name__, template_folder='templates')
cache_mgr.before_request(prompt_license)
cache_mgr.before_request(license_required)
cache_mgr.before_request(license_reminder)


cache_steps = ["Install Components", "Configure Components", "Restart Services"]


@cache_mgr.route('/')
@login_required
def index():
    servers = Server.query.all()
    app_conf = AppConfiguration.query.first()
    

    
    if not app_conf:
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    if not servers:
        flash("Add servers to the cluster before attempting to manage cache",
              "warning")
        return redirect(url_for('index.home'))


    if app_conf.external_load_balancer:
        c_host = app_conf.cache_host
        c_ip = app_conf.cache_ip
    else:
        c_host = app_conf.nginx_host
        c_ip = app_conf.nginx_ip
        


    c = RemoteClient(host=c_host, ip=c_ip)
    
    try:
        c.startup()
    except:
        flash("SSH connection can't be established to cache server", "warning")

    result = c.get_file('/etc/stunnel/stunnel.conf')
    
    installed_servers = []

    if result[0]:
        installed_servers = get_redis_config(result[1])
    
    for server in servers:
        if server.ip in installed_servers:
            server.redis = True
        else:
            server.redis = False

    version = int(app_conf.gluu_version.replace(".", ""))
    if version < 311:
        flash("Cache Management is available only for clusters configured with"
              " Gluu Server version 3.1.1 and above", "danger")
        return redirect(url_for('index.home'))

    form = CacheSettingsForm()

    return render_template('cache_index.html', servers=servers, form=form)


@cache_mgr.route('/refresh_methods')
@login_required
def refresh_methods():
    task = get_cache_methods.delay()
    return jsonify({'task_id': task.id})


def get_servers_and_list():
    server_id = request.args.get('id')
    
    if server_id:
        servers = [ Server.query.get(int(server_id)) ]
    else:
        servers = Server.query.all()

    server_id_list = [ s.id for s in servers ]
    
    return servers, server_id_list, server_id

@cache_mgr.route('/change/', methods=['GET', 'POST'])
@login_required
def change():

    app_conf = AppConfiguration.query.first()
    servers, server_id_list, server_id = get_servers_and_list()
    
    method = 'STANDALONE'

    if not servers:
        return redirect(url_for('cache_mgr.index'))
    
    task = install_cache_components.delay(method, server_id_list)

    nextpage = url_for('cache_mgr.configure', method=method)
    whatNext = cache_steps[1]
    title = "Cache Clustering"

    if not app_conf.external_load_balancer:
        #mock server for cache
        mock_nginx = Server(
                    hostname="Nginx Proxy [{0}]".format(app_conf.nginx_host),
                    id=9999)
    
        servers.append(mock_nginx)

    return render_template('logger_single.html',
                           title=title,
                           steps=cache_steps,
                           task=task,
                           cur_step=1,
                           auto_next=False,
                           multiserver=servers,
                           nextpage=nextpage,
                           whatNext=whatNext
                           )


@cache_mgr.route('/configure/<method>/')
@login_required
def configure(method):

    app_conf = AppConfiguration.query.first()
    servers, server_id_list, server_id = get_servers_and_list()

    task = configure_cache_cluster.delay(method, server_id_list)

    nextpage = url_for('cache_mgr.configure', method=method)
    whatNext = cache_steps[2]
    title = "Cache Clustering"

    if not app_conf.external_load_balancer:
        #mock server for cache
        mock_nginx = Server(
                    hostname="Nginx Proxy [{0}]".format(app_conf.nginx_host),
                    id=9999)
    
        servers.append(mock_nginx)

    return render_template('logger_single.html',
                           title=title,
                           steps=cache_steps,
                           task=task,
                           cur_step=2,
                           auto_next=False,
                           multiserver=servers,
                           nextpage=nextpage,
                           whatNext=whatNext
                           )


@cache_mgr.route('/finish_clustering/<method>/')
@login_required
def finish_clustering(method):
    
    server_id = request.args.get('id')

    if server_id:
        servers = []
        qserver = Server.query.filter(
                                    Server.redis.is_(True)
                                ).filter(
                                    Server.stunnel.is_(True)
                                ).filter(
                                    Server.id.is_(int(server_id))
                                ).first()
        
        if qserver:
            servers.append(qserver)
    else:

        servers = Server.query.filter(
                                    Server.redis.is_(True)
                                ).filter(
                                    Server.stunnel.is_(True)
                                ).all()


    server_id_list = [ s.id for s in servers ]
    
    
    task = restart_services.delay(method, server_id_list)
    
    return render_template( 'cache_logger.html', 
                            servers=servers, 
                            step=3,
                            server_id=server_id,
                            task_id=task.id
                           )

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

