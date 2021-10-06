import json
import os
import re
import socket

from clustermgr.models import Server, AppConfiguration, CacheServer
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import LdapOLC
from clustermgr.core.utils import parse_setup_properties, \
        get_redis_config, get_cache_servers

from clustermgr.core.clustermgr_installer import Installer

from ldap3.core.exceptions import LDAPSocketOpenError
from flask import current_app as app


def install_stunnel(installer, app_conf, is_cache):
    
    primary_cache_server = CacheServer.query.first()
    stunnel_installed = installer.conn.exists('/usr/bin/stunnel') or installer.conn.exists('/bin/stunnel')
    stunnel_package = 'stunnel4' if installer.clone_type == 'deb' else 'stunnel'  

    if app_conf.offline:
        if not stunnel_installed:
            wlogger.log(
                installer.logger_task_id, 
                'Stunnel was not installed. Please install stunnel '
                'and retry.', 
                'error',
                server_id=installer.server_id
                )
            return False
         
    if not stunnel_installed:
        wlogger.log(installer.logger_task_id, "Installing Stunnel", "info", server_id=installer.server_id)
        installer.install(stunnel_package, inside=False)

        if installer.conn.exists('/usr/bin/stunnel') or installer.conn.exists('/bin/stunnel'):
            wlogger.log(installer.logger_task_id, "Stunnel install successful", "success",
                                server_id=installer.server_id)
        else:
            wlogger.log(installer.logger_task_id, "Stunnel installation failed", "fail",
                                server_id=installer.server_id)
            return False
            
    if installer.clone_type == 'rpm':
        local_service_file = os.path.join(app.root_path, 'templates', 
                        'stunnel', 'stunnel.service')
        remote_service_file = '/lib/systemd/system/stunnel.service'
        wlogger.log(installer.logger_task_id, "Uploading systemd file", "info",
                server_id=installer.server_id)
        installer.upload_file(local_service_file, remote_service_file)
        installer.run("mkdir -p /var/log/stunnel4", inside=False)

    if installer.clone_type == 'deb':
        wlogger.log(installer.logger_task_id, "Enabling stunnel", "debug", server_id=installer.server_id)
        installer.run("sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/stunnel4", inside=False)

    stunnel_pem_fn = '/etc/stunnel/redis-server.pem'
    stunnel_pem_local_fn = '/tmp/{}.pem'.format(primary_cache_server.ip.replace('.','_'))

    if installer.ip == primary_cache_server.ip:
        if not installer.conn.exists(stunnel_pem_fn):
            r = installer.run('which openssl', inside=False)
            if not r[1]:
                wlogger.log(installer.logger_task_id, 
                    "openssl command not found. Please install openssl on {} host system and retry.".format(installer.hostname),
                    "error", server_id=installer.server_id)
                return False

            wlogger.log(installer.logger_task_id, "Creating SSL certificate for stunnel", "info",
                            server_id=installer.server_id)
            installer.run(
                    'openssl req -x509 -nodes -days 3650 -newkey rsa:2048 '
                    '-batch -keyout /etc/stunnel/redis-server.key '
                    '-out /etc/stunnel/redis-server.crt',
                    inside=False,
                    error_exception='Generating'
                    )
            installer.run('cat /etc/stunnel/redis-server.key /etc/stunnel/redis-server.crt > {}'.format(stunnel_pem_fn), inside=False)
            installer.run('chmod 600 /etc/stunnel/redis-server.key',inside=False)
            installer.run('chmod 600 '+stunnel_pem_fn, inside=False)
        
        # retreive stunnel certificate
        wlogger.log(installer.logger_task_id, "Retreiving server certificate", "info",
                            server_id=installer.server_id)
        installer.download_file(stunnel_pem_fn, stunnel_pem_local_fn)
            
    else:
        wlogger.log(installer.logger_task_id, "Uploading server certificate", "info",
                            server_id=installer.server_id)
        installer.upload_file(stunnel_pem_local_fn, stunnel_pem_fn)
        installer.run('chmod 600 '+stunnel_pem_fn, inside=False)
 
    if is_cache:
        stunnel_redis_conf = (
                            'pid = /run/stunnel-redis.pid\n'
                            'cert = /etc/stunnel/redis-server.pem\n'
                            '[redis-server]\n'
                            'accept = {0}:{1}\n'
                            'connect = 127.0.0.1:6379\n'
                            ).format(installer.ip, primary_cache_server.stunnel_port)
    else:
        stunnel_redis_conf = ( 
                    'pid = /run/stunnel-redis.pid\n'
                    'cert = /etc/stunnel/redis-server.pem\n'
                    '[redis-client]\n'
                    'client = yes\n'
                    'accept = 127.0.0.1:6379\n'
                    'connect = {0}:{1}\n'
                    ).format(primary_cache_server.ip, primary_cache_server.stunnel_port)
    
    wlogger.log(installer.logger_task_id, "Writing redis stunnel configurations", "info",
                        server_id=installer.server_id)

    installer.put_file('/etc/stunnel/stunnel.conf', stunnel_redis_conf)
    
    if installer.clone_type == 'rpm':
        local = os.path.join(app.root_path, 'templates', 'stunnel',
                             'stunnel.service')
        remote = '/lib/systemd/system/stunnel.service'
        wlogger.log(installer.logger_task_id, "Uploading systemd file", "info",
                    server_id=installer.server_id)
        installer.upload_file(local, remote)
        installer.run("mkdir -p /var/log/stunnel4", inside=False)
        installer.run("systemctl daemon-reload", inside=False)        

    installer.enable_service(stunnel_package, inside=False)
    installer.restart_service(stunnel_package, inside=False)

    return True

@celery.task(bind=True)
def install_cache_cluster(self, servers_id_list, cache_servers_id_list):

    task_id = self.request.id

    servers = [ Server.query.get(id) for id in servers_id_list ]
    cache_servers = [ CacheServer.query.get(id) for id in cache_servers_id_list ]
    primary_cache_server = CacheServer.query.first()
    app_conf = AppConfiguration.query.first()

    for server in cache_servers:

        server.os = None
        installer =  Installer(
                        server,
                        app_conf.gluu_version,
                        ssh_port=server.ssh_port,
                        logger_task_id=task_id
                    )

        if not installer.conn:
            wlogger.log(task_id, "SSH connection to server failed", "error", server_id=server.id)
            return False

        redis_installed = installer.conn.exists('/usr/bin/redis-server')
        
        if app_conf.offline:
            if not redis_installed:
                wlogger.log(
                    task_id, 
                    'Redis Server was not installed. Please install Redis '
                    ' Server and retry.', 
                    'error',
                    server_id=server.id
                    )
                return False

        redis_package = 'redis-server' if installer.clone_type == 'deb' else 'redis'  
        if not redis_installed:            

            if installer.clone_type == 'rpm':
                installer.epel_release()
            
            wlogger.log(task_id, "Installing Redis Server", "info", server_id=server.id)
            
            
            installer.install(redis_package, inside=False)
            
        if not installer.conn.exists('/usr/bin/redis-server'):
                wlogger.log(
                    task_id, 
                    'Redis Server was not installed. Please check log files', 
                    'error',
                    server_id=server.id
                    )
                return False

        wlogger.log(
                    task_id, 
                    'Setting Redis password',
                    'info',
                    server_id=server.id
                    )

        redis_config_file = '/etc/redis/redis.conf' if installer.clone_type == 'deb' else '/etc/redis.conf'
        redis_config = installer.get_file(redis_config_file)

        if redis_config:
            redis_config = redis_config.split('\n')
            for i, l in enumerate(redis_config[:]):
                if l.startswith('requirepass'):
                    if not server.redis_password:
                        del redis_config[i]
                    else:
                        redis_config[i] = 'requirepass ' + server.redis_password
                    break
                if l.replace(' ','').startswith('#requirepass') and server.redis_password:
                    redis_config[i] = 'requirepass ' + server.redis_password
                    break

            else:
                if server.redis_password:
                    redis_config.append('requirepass ' + server.redis_password)
            filecontent = '\n'.join(redis_config)

            installer.put_file(redis_config_file, filecontent)

        installer.enable_service(redis_package, inside=False)
        installer.restart_service(redis_package, inside=False)

        si_result = install_stunnel(installer, app_conf, is_cache=True)

        if not si_result:
            return False

        server.installed = True
        db.session.commit()
        
        if primary_cache_server.id == server.id:
            wlogger.log(installer.logger_task_id, "Retreiving server certificate", "info",
                                server_id=installer.server_id)
            
            # retreive stunnel certificate
            stunnel_cert = installer.get_file('/etc/stunnel/redis-server.crt')

            if not stunnel_cert:
                print("Can't retreive server certificate from primary cache server")
                return False

    wlogger.log(task_id, "2", "setstep")

    for server in servers:
        installer =  Installer(
                        server,
                        app_conf.gluu_version,
                        ssh_port=server.ssh_port,
                        logger_task_id=task_id
                    )

        si_result = install_stunnel(installer, app_conf, is_cache=False)
        if not si_result:
            return False

        if server.primary_server:
            
            server_string = 'localhost:6379'
            __update_LDAP_cache_method(task_id, server, server_string, redis_password=primary_cache_server.redis_password)

        wlogger.log(task_id, "Restarting Gluu Server", "info",
                                server_id=server.id)

        installer.restart_gluu()

    wlogger.log(task_id, "3", "setstep")
    return True

@celery.task(bind=True)
def remove_cache_server_task(self, cache_servers_id_list):

    task_id = self.request.id
    servers = Server.get_all()

    cache_servers = [ CacheServer.query.get(id) for id in cache_servers_id_list ]
    primary_cache_server = CacheServer.query.first()
    app_conf = AppConfiguration.query.first()

    

    for server in cache_servers:

        server.os = None
        installer =  Installer(
                        server,
                        app_conf.gluu_version,
                        ssh_port=server.ssh_port,
                        logger_task_id=task_id
                    )

        if not installer.conn:
            wlogger.log(task_id, "SSH connection to server failed", "error", server_id=server.id)
            return False

        if installer.clone_type == 'deb':
            stunnel_package = 'stunnel4'
            redis_package = 'redis-server'
        else:
            stunnel_package = 'stunnel'
            redis_package = 'redis'
            

        installer.enable_service(stunnel_package, enable=False, inside=False)
        installer.enable_service(redis_package, enable=False, inside=False)


    wlogger.log(task_id, "2", "setstep")

    for server in servers:
        installer =  Installer(
                        server,
                        app_conf.gluu_version,
                        ssh_port=server.ssh_port,
                        logger_task_id=task_id
                    )
        stunnel_package = 'stunnel4' if installer.clone_type == 'deb' else 'stunnel'
        installer.enable_service(stunnel_package, enable=False, inside=False)
        
        if server.primary_server:
            __update_LDAP_cache_method(task_id, server, use_ldap=True)
            
        installer.restart_gluu()

    for server in cache_servers:
        db.session.delete(server)

    app_conf.use_ldap_cache = True
    db.session.commit()

    wlogger.log(task_id, "3", "setstep")

def __update_LDAP_cache_method(tid, server, server_string='', method='STANDALONE', redis_password='', use_ldap=False):
    """Connects to LDAP and updathe cache method and the cache servers

    :param tid: task id for log identification
    :param server: :object:`clustermgr.models.Server` to connect to
    :param server_string: the server string pointing to the redis servers
    :param method: STANDALONE for proxied and SHARDED for client sharding
    :return: boolean status of the LDAP update operation
    """
    wlogger.log(tid, "Updating oxCacheConfiguration ...", "debug",
                server_id=server.id)
    try:
        adminOlc = LdapOLC('ldaps://{}:1636'.format(server.hostname), 
                        'cn=directory manager',
                        server.ldap_password)
        adminOlc.connect()
    except Exception as e:
        wlogger.log(tid, "Couldn't connect to LDAP. Error: {0}".format(e),
                    "error", server_id=server.id)
        wlogger.log(tid, "Make sure your LDAP server is listening to "
                         "connections from outside", "debug",
                    server_id=server.id)
        return

    if use_ldap:
        adminOlc.changeOxCacheConfiguration('NATIVE_PERSISTENCE')
        wlogger.log(tid,
                'cacheProviderType entry is set to NATIVE_PERSISTENCE',
                'success', server_id=server.id)
    else:
        result = adminOlc.changeOxCacheConfiguration('REDIS', server_string, redis_password)

        if not result:
            wlogger.log(tid, "oxCacheConfigutaion update failed", "fail",
                    server_id=server.id)



