"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
import os

from flask import Blueprint, render_template, url_for, flash, redirect, \
    jsonify, request, session

from flask_login import login_required
from flask_menu import register_menu

from clustermgr.models import db, ConfigParam
from clustermgr.tasks.cache import uninstall_cache_cluster, install_cache_sentinel

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.license import license_required
from clustermgr.core.remote import RemoteClient
from clustermgr.core.utils import get_redis_config, random_chars
from clustermgr.forms import CacheSettingsForm, cacheServerForm

cache_mgr = Blueprint('cache_mgr', __name__, template_folder='templates')
cache_mgr.before_request(prompt_license)
cache_mgr.before_request(license_required)
cache_mgr.before_request(license_reminder)


@cache_mgr.route('/')
@register_menu(cache_mgr, '.gluuServerCluster.cacheManagement', 'Cache Management', order=4, icon='fa fa-microchip')
@login_required
def index():
    servers = ConfigParam.get_servers()
    settings = ConfigParam.get('settings')
    cache_servers = ConfigParam.get_all('cacheserver')
    cachetype = request.args.get('cachetype')

    if cachetype == 'redis':
        settings.data.use_ldap_cache = False
        settings.save()
    elif cachetype == 'ldap':
        if not cache_servers:
            settings.data.use_ldap_cache = True
            settings.save()

        else:
            steps = ['Disabling Redis Server and Stunnel on Cache Server', 'Disabling stunnel on Gluu Server Nodes']
            title = "Setting Up Cache Management"
            whatNext = "Cache Management Home"
            nextpage = url_for('cache_mgr.index')
            
            task = uninstall_cache_cluster.delay(
                                        [server.id for server in servers],
                                        [server.id for server in cache_servers],
                                        )

            return render_template('logger_single.html',
                                   title=title,
                                   steps=steps,
                                   task=task,
                                   cur_step=1,
                                   auto_next=True,
                                   multistep=True,
                                   multiserver=cache_servers+servers,
                                   nextpage=nextpage,
                                   whatNext=whatNext
                                   )
        
    if not servers:
        flash("Add servers to the cluster before attempting to manage cache",
              "warning")
        return redirect(url_for('index.home'))


    form = CacheSettingsForm()

    return render_template('cache_index.html', 
                           servers=servers, 
                           form=form,
                           cache_servers=cache_servers,
                           use_ldap_cache=settings.data.use_ldap_cache,
                           )


def get_servers_and_list():
    server_id = request.args.get('id')
    
    if server_id:
        servers = [ Server.query.get(int(server_id)) ]
    else:
        servers = Server.query.all()

    server_id_list = [ s.id for s in servers ]
    
    return servers, server_id_list, server_id

@cache_mgr.route('/install', methods=['GET', 'POST'])
@login_required
def install():

    server_id = request.args.get('server')

    if server_id:
        cache_servers = []
        servers = [ ConfigParam.get_by_id(int(server_id)) ]
    else:
        cache_servers = ConfigParam.get_all('cacheserver')
        servers = ConfigParam.get_servers()

    if not servers:
        return redirect(url_for('cache_mgr.index'))

    steps = ['Install Redis Server and Stunnel on Cache Server', 'Setup stunnel on Gluu Server Nodes']

    title = "Setting Up Cache Management"
    whatNext = "Cache Management Home"
    nextpage = url_for('cache_mgr.index')
    
    #if len(cache_servers) == 1:
    
    #    task = install_cache_single.delay(
    #                            [server.id for server in servers],
    #                            [server.id for server in cache_servers],
    #                            )
    #else:

    task = install_cache_sentinel.delay(
                                [server.id for server in servers],
                                [server.id for server in cache_servers],
                                )

    return render_template('logger_single.html',
                           title=title,
                           steps=steps,
                           task=task,
                           cur_step=1,
                           auto_next=True,
                           multistep=True,
                           multiserver=cache_servers+servers,
                           nextpage=nextpage,
                           whatNext=whatNext
                           )

@cache_mgr.route('/addcacheserver/', methods=['GET', 'POST'])
@login_required
def add_cache_server():
    cid = request.args.get('cid', type=int)

    form = cacheServerForm()

    if cid:
        cacheserver = ConfigParam.get_by_id(cid)
        for k in cacheserver.data.keys():
            setattr(cacheserver, k, getattr(cacheserver.data, k))
        form = cacheServerForm(obj=cacheserver)
        if not cacheserver:
            return "<h2>No such Cache Server</h2>"

    if request.method == "POST" and form.validate_on_submit():
        hostname = form.hostname.data
        ip = form.ip.data
        install_redis = form.install_redis.data

        if not cid:
            cacheserver = ConfigParam.new('cacheserver')

        cacheserver.data.hostname = hostname
        cacheserver.data.ip = ip
        cacheserver.data.install_redis = install_redis

        cacheserver.save()
        if cid:
            flash("Cache server was added","success")
        else:
            flash("Cache server was updated","success")

        return jsonify( {"result": True, "message": "Cache server was added"})

    return render_template( 'cache_server.html', form=form)

@cache_mgr.route('/status/')
@login_required
def get_status():

    status={'redis':{}, 'stunnel':{}}
    servers = ConfigParam.get_servers()
    
    check_cmd = 'python -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);print s.connect_ex((\'{0}\', {1}))"'
    
    cache_servers = ConfigParam.get_all('cacheserver')
    

    stunnel_port = cache_servers[0].data.stunnel_port if cache_servers else None
        
    
    for server in servers + cache_servers:
        key = server.data.ip.replace('.','_')

        c = RemoteClient(host=server.data.hostname, ip=server.data.ip)
        try:
            c.startup()
        except:
            status['stunnel'][key] = False
            status['redis'][key] = False
        else:

            status['stunnel'][key]=False
            
            if server in cache_servers:
                r = c.run(check_cmd.format('localhost', 6379))
                stat = r[1].strip()
                
                if stat == '0':
                    status['redis'][key]=True
                else:
                    status['redis'][key]=False

                if stunnel_port:
                    r = c.run(check_cmd.format(server.data.ip, stunnel_port))
                    stat = r[1].strip()

                if stat == '0':
                    status['stunnel'][key]=True

            else:
                if stunnel_port:
                    r = c.run(check_cmd.format('localhost', '6379'))
                    stat = r[1].strip()

                    if stat == '0':
                        status['stunnel'][key]=True

        c.close()
    
    return jsonify(status)
