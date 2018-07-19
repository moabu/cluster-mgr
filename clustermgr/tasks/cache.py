import json
import os
import re
import socket


from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import LdapOLC
from clustermgr.tasks.cluster import run_command
from clustermgr.core.utils import parse_setup_properties, \
        get_redis_config, make_proxy_stunnel_conf, make_twem_proxy_conf

from clustermgr.core.clustermgr_installer import Installer
from clustermgr.config import Config

from ldap3.core.exceptions import LDAPSocketOpenError
from flask import current_app as app


def install_redis(installer):

    redis_installed = False

    if installer.conn.exists('/usr/bin/redis-server') or \
                                installer.conn.exists('/bin/redis-server'):
        wlogger.log(installer.logger_task_id, 
                "Redis was already installed on this server", 
                "info", server_id=installer.server_id)
        redis_installed = True
    else:
        wlogger.log(installer.logger_task_id, 
                    "Installing Redis in server",
                    "info", server_id=installer.server_id)
        
        if installer.clone_type == 'deb':
            installer.install('software-properties-common', inside=False)
            installer.run('add-apt-repository ppa:chris-lea/redis-server -y',
                            error_exception='gpg: keyring', inside=False)
            installer.repo_updated = False
            installer.install('redis-server', inside=False)
        else:
            installer.epel_release()
            installer.install('redis', inside=False)
            if installer.server_os[-1] == '6':
                installer.run('chkconfig --add redis', inside=False)
                installer.run('chkconfig --level 345 redis on', inside=False)
            else:
                installer.run('systemctl enable redis', 
                            error_exception='Created symlink from',
                            inside=False)
                
        if installer.conn.exists('/usr/bin/redis-server') or \
                                installer.conn.exists('/bin/redis-server'):
            redis_installed = True
            wlogger.log(installer.logger_task_id, 
                        "Redis install successful", "success",
                        server_id=installer.server_id)
        else:
            wlogger.log(installer.logger_task_id, 
                        "Redis install failed", "fail",
                        server_id=installer.server_id)

    return redis_installed

def install_stunnel(installer):
    
    stunnel_installed = False
    
    if installer.conn.exists('/usr/bin/stunnel') or \
                                installer.conn.exists('/bin/stunnel'):
        wlogger.log(installer.logger_task_id, 
                    "Stunnel was allready installed", 
                    "info", server_id=installer.server_id)
        stunnel_installed = True
    else:
        wlogger.log(installer.logger_task_id, 
                    "Installing Stunnel", "info", 
                    server_id=installer.server_id)
        if installer.clone_type == 'deb':
            installer.install('stunnel4', inside=False)
        else:
            installer.install('stunnel', inside=False)

        if installer.conn.exists('/usr/bin/stunnel') or \
                            installer.conn.exists('/bin/stunnel'):
            stunnel_installed = True
            wlogger.log(installer.logger_task_id, 
                        "Stunnel install successful", "success",
                        server_id=installer.server_id)
        else:
            wlogger.log(installer.logger_task_id, 
                        "Stunnel install failed", "fail",
                        server_id=installer.server_id)

    return stunnel_installed

@celery.task(bind=True)
def install_cache_components(self, method, server_id_list):
    """Celery task that installs the redis, stunnel and twemproxy applications
    in the required servers.

    Redis and stunnel are installed in all the servers in the cluster.
    Twemproxy is installed in the load-balancer/proxy server

    :param self: the celery task
    :param method: either STANDALONE, SHARDED

    :return: the number of servers where both stunnel and redis were installed
        successfully
    """
    
    task_id = self.request.id
    installed = 0
    
    app_conf = AppConfiguration.query.first()
    
    servers = []

    """

    for server_id in server_id_list:
        
        server = Server.query.get(server_id)
        
        installer = Installer(
            server,
            app_conf.gluu_version,
            logger_task_id=task_id,
            )
    
        server.redis = install_redis(installer)
        server.stunnel = install_stunnel(installer)
        
        # Save the redis and stunnel install situation to the db    
        if server.redis and server.stunnel:
            installed += 1
        db.session.commit()


    if method != 'STANDALONE':
        # No need to install twemproxy for "SHARDED" configuration
        return True

    """

    #If we are using external load balancer no need to proceed.
    if app_conf.external_load_balancer:
        return True

    # Install twemproxy in the Nginx load balancing proxy server
    mock_nginx = Server(
                hostname=app_conf.nginx_host,
                ip=app_conf.nginx_ip,
                os = app_conf.nginx_os,
                id=9999
                )

    nginx_installer = Installer(
        mock_nginx,
        app_conf.gluu_version,
        logger_task_id=task_id,
        )

    install_redis(nginx_installer)
    install_stunnel(nginx_installer)

    if not nginx_installer.conn.exists('/usr/sbin/nutcracker'):

        wlogger.log(task_id, "Installing Twemproxy", server_id=9999)
        # 1. Setup the development tools for installation

        if nginx_installer.server_os == "Ubuntu 14":
            nginx_installer.run(
                    'wget http://ftp.debian.org/debian/pool/main/n/nutcracker/'
                    'nutcracker_0.4.0+dfsg-1_amd64.deb -O /tmp/'
                    'nutcracker_0.4.0+dfsg-1_amd64.deb', inside=False)
            nginx_installer.run(
                'dpkg -i /tmp/nutcracker_0.4.0+dfsg-1_amd64.deb', inside=False)
        elif nginx_installer.server_os == "Ubuntu 16":
            nginx_installer.install('nutcracker', inside=False)
        else:
            nginx_package = ('https://raw.githubusercontent.com/mbaser/gluu/'
                'master/nutcracker-0.4.1-1.gluu.centos{0}.x86_64.rpm').format(
                    nginx_installer.server_os[-1])
            nginx_installer.install(nginx_package, inside=False)
            nginx_installer.run('chkconfig nutcracker on', inside=False)

        # 5. Create the default configuration file referenced in the init scripts
        #run_and_log(rc, "mkdir -p /etc/nutcracker", tid)
        nginx_installer.run("touch /etc/nutcracker/nutcracker.yml", inside=False)
    else:
        wlogger.log(task_id, 
                "Twemproxy was already installed on cache server",
                server_id=9999)
                
    return installed


@celery.task(bind=True)
def configure_cache_cluster(self, method, server_id_list):
    if method == 'SHARDED':
        return setup_sharded(self.request.id)
    elif method == 'STANDALONE':
        return setup_proxied(self.request.id, server_id_list)
    elif method == 'CLUSTER':
        return setup_redis_cluster(self.request.id)


def setup_sharded(tid):
    """Function that adds the stunnel configuration to all the servers and
    maps the ports in the LDAP configuration.
    """
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    appconf = AppConfiguration.query.first()
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    # Store the redis server info in the LDA
    for server in servers:
        redis_instances = []
        stunnel_conf = [
            "cert = /etc/stunnel/cert.pem",
            "pid = /var/run/stunnel.pid",
            "output = /var/log/stunnel4/stunnel.log",
            "[redis-server]",
            "client = no",
            "accept = {0}:7777".format(server.ip),
            "connect = 127.0.0.1:6379"
        ]

        for s in servers:
            port = 7000 + s.id
            redis_instances.append('localhost:{0}'.format(port))
            stunnel_conf.append("[client{0}]".format(s.id))
            stunnel_conf.append("client = yes")
            stunnel_conf.append("accept = 127.0.0.1:{0}".format(port))
            stunnel_conf.append("connect = {0}:7777".format(s.ip))

        connect_to = ",".join(redis_instances)
        __update_LDAP_cache_method(tid, server, connect_to, 'SHARDED')
        stat = __configure_stunnel(tid, server, stunnel_conf, chdir)
        if not stat:
            continue


def __configure_stunnel(task_id, server, stunnel_conf, setup_props=None):
    """Sets up Stunnel with given configuration, init or service scripts,
    SSL certificate ...etc., for use in a server

    :param task_id: task id for log identification
    :param server: :object:`clustermgr.models.Server` where stunnel needs to be
        setup
    :param stunnel_conf: list of lines for the stunnel config file
    :param chdir: chroot directory to find out the setup.properties file and
        extract the required values to generate a SSL certificate
    :param setup_props: Optional - location of setup.properties file to get the
        details for SSL Cert generation for Stunnel
    :return: boolean status fo the operation
    """
    wlogger.log(task_id, "Setting up stunnel",'info', server_id=server.id)
    app_conf = AppConfiguration.query.first()
    installer = Installer(
            server,
            app_conf.gluu_version,
            logger_task_id=task_id,
            )
    if not installer.conn:
        return False
    
    wlogger.log(task_id, "Adding init/service scripts of boot time startup",
                "info", server_id=server.id)
    # replace the /etc/default/stunnel4 to enable start on system startup
    local = os.path.join(app.root_path, 'templates', 'stunnel',
                         'stunnel4.default')
    remote = '/etc/default/stunnel4'
    installer.upload_file(local, remote)

    if 'CentOS 6' == server.os:
        local = os.path.join(app.root_path, 'templates', 'stunnel',
                             'centos.init')
        remote = '/etc/rc.d/init.d/stunnel4'
        installer.upload_file(local, remote)
        installer.run("chmod +x {0}".format(remote), inside=False)

    if server.os in ('CentOS 7', 'RHEL 7'):
        local = os.path.join(app.root_path, 'templates', 'stunnel',
                             'stunnel.service')
        remote = '/lib/systemd/system/stunnel.service'
        installer.upload_file(local, remote)
        installer.run("mkdir -p /var/log/stunnel4", inside=False)
        wlogger.log(task_id, "Setup auto-start on system boot", "info",
                    server_id=server.id)
        installer.run('systemctl enable redis', inside=False)
        installer.run('systemctl enable stunnel', inside=False)

    #if certificate of stunnel does not exists, create it
    if not installer.conn.exists("/etc/stunnel/cert.pem"):
        # setup the certificate file
        wlogger.log(task_id, "Generating certificate for stunnel ...", 'debug',
                    server_id=server.id)
        
        if setup_props:
            propsfile = setup_props
        else:
            propsfile = os.path.join(Config.DATA_DIR, 'setup.properties')

        props = parse_setup_properties(open(propsfile))

        print props

        subject = "'/C={countryCode}/ST={state}/L={city}/O={orgName}/CN={hostname}" \
                  "/emailAddress={admin_email}'".format(**props)
        cert_path = "/etc/stunnel/server.crt"
        key_path = "/etc/stunnel/server.key"
        pem_path = "/etc/stunnel/cert.pem"
        cmd = ('/usr/bin/openssl req -subj {0} -new -newkey rsa:2048 -sha256 '
               '-days 365 -nodes -x509 -keyout {1} -out {2}').format(
               subject, key_path, cert_path)

        installer.run(cmd, 
                    error_exception='Generating a 2048 bit RSA private key',
                    inside=False)
        installer.run("cat {cert} {key} > {pem}".format(cert=cert_path, key=key_path,
                                                 pem=pem_path), inside=False)
        # verify certificate
        cin, cout, cerr = installer.run("/usr/bin/openssl verify " + pem_path, inside=False)
        if props['hostname'] in cout and props['orgName'] in cout:
            wlogger.log(task_id, "Certificate generated successfully", "success",
                        server_id=server.id)
        else:
            wlogger.log(task_id, "/usr/bin/openssl verify " + pem_path, 
                        "debug", server_id=server.id)
            wlogger.log(task_id, cerr, "cerror")
            wlogger.log(task_id, "Certificate generation failed. Add a SSL "
                             "certificate at /etc/stunnel/cert.pem", "error",
                        server_id=server.id)

    # Generate stunnel config
    wlogger.log(task_id, "Setup stunnel listening and forwarding", "debug",
                server_id=server.id)
    installer.put_file("/etc/stunnel/stunnel.conf", "\n".join(stunnel_conf))
    
    
    # Setup Twemproxy if this is cache server, id of cache server is 9999
    if server.id == 9999:
        wlogger.log(task_id, "Writing Twemproxy configuration", 
                        server_id=server.id)
        twemproxy_conf = make_twem_proxy_conf()
        remote = "/etc/nutcracker/nutcracker.yml"
        installer.put_file(remote, twemproxy_conf)
        installer.run('service nutcracker restart')

    return True


def __update_LDAP_cache_method(task_id, server, server_string, method):
    """Connects to LDAP and updathe cache method and the cache servers

    :param tid: task id for log identification
    :param server: :object:`clustermgr.models.Server` to connect to
    :param server_string: the server string pointing to the redis servers
    :param method: STANDALONE for proxied and SHARDED for client sharding
    :return: boolean status of the LDAP update operation
    """
    wlogger.log(task_id, "Updating oxCacheConfiguration", "debug",
                server_id=server.id)
                
    try:
        wlogger.log(task_id, "Connecting LDAP Server ...", "debug",
                server_id=server.id)

        dbm = LdapOLC('ldaps://{}:1636'.format(server.hostname), 
                        'cn=Directory Manager', server.ldap_password)
        dbm.connect()
    except Exception as e:
        wlogger.log(task_id, "Couldn't connect to LDAP. Error: {0}".format(e),
                    "error", server_id=server.id)
        wlogger.log(task_id, "Make sure your LDAP server is listening to "
                         "connections from outside", "debug",
                    server_id=server.id)
        return
    entry = dbm.get_appliance_attributes('oxCacheConfiguration')
    cache_conf = json.loads(entry.oxCacheConfiguration.value)
    cache_conf['cacheProviderType'] = 'REDIS'
    cache_conf['redisConfiguration']['redisProviderType'] = method
    cache_conf['redisConfiguration']['servers'] = server_string

    result = dbm.set_applicance_attribute('oxCacheConfiguration',
                                          [json.dumps(cache_conf)])
    
    if not result:
        wlogger.log(task_id, "oxCacheConfigutaion update failed", "fail",
                    server_id=server.id)
    else:
        wlogger.log(task_id, "oxCacheConfigutaion updated", "success",
                    server_id=server.id)

def setup_proxied(task_id, server_id_list):
    """Configures the servers to use the Twemproxy installed in proxy server
    for Redis caching securely via stunnel.

    :param tid: task id for log identification
    :return: None
    """
    
    servers = []
    
    primary_ready = False
    
    for server_id in server_id_list:
        qserver = Server.query.filter(
                                Server.redis.is_(True)
                            ).filter(
                                Server.stunnel.is_(True)
                            ).filter(
                                Server.id.is_(server_id)
                            ).first()
        if qserver:
            servers.append(qserver)
            if qserver.primary_server:
                primary_ready = True

    app_conf = AppConfiguration.query.first()

    if app_conf.external_load_balancer:
        cache_ip = app_conf.cache_ip
    else:
        cache_ip = app_conf.nginx_ip
    
    if not primary_ready :
        wlogger.log(task_id, "Primary Server is not setup yet. Cannot setup "
                    "clustered caching.", "error", server_id=servers[0].id)

        return False

    # Configure Stunnel and Redis in each server
    for server in servers:
        #Since replication is active, we only need to update on primary server
        #if server.primary_server:
        #    print "UPDATING CACHE METHOD"
        #    __update_LDAP_cache_method(task_id, server, 'localhost:7000', 'STANDALONE')
       
        stunnel_conf = [
            "cert = /etc/stunnel/cert.pem",
            "pid = /var/run/stunnel.pid",
            "output = /var/log/stunnel4/stunnel.log",
            "[redis-server]",
            "client = no",
            "accept = {0}:7777".format(server.ip),
            "connect = 127.0.0.1:6379",
            "[twemproxy]",
            "client = yes",
            "accept = 127.0.0.1:7000",
            "connect = {0}:8888".format(cache_ip)
        ]
     
        status = __configure_stunnel(task_id, server, stunnel_conf)

        if not status:
            continue
    
    if not app_conf.external_load_balancer:
        # Setup Stunnel in the proxy server
        mock_nginx = Server(
                    hostname=app_conf.nginx_host,
                    ip=app_conf.nginx_ip,
                    os = app_conf.nginx_os,
                    id=9999
                    )

        proxy_stunnel_conf = make_proxy_stunnel_conf()
        
        status = __configure_stunnel(task_id, mock_nginx, proxy_stunnel_conf)

        if not status:
            return False

        return True

def setup_redis_cluster(tid):
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()

    master_conf = ["port 7000", "cluster-enabled yes",
                   "daemonize yes",
                   "dir /var/lib/redis",
                   "dbfilename dump_7000.rdb",
                   "cluster-config-file nodes_7000.conf",
                   "cluster-node-timeout 5000",
                   "appendonly yes", "appendfilename node_7000.aof",
                   "logfile /var/log/redis/redis-7000.log",
                   "save 900 1", "save 300 10", "save 60 10000",
                   ]
    slave_conf = ["port 7001", "cluster-enabled yes",
                  "daemonize yes",
                  "dir /var/lib/redis",
                  "dbfilename dump_7001.rdb",
                  "cluster-config-file nodes_7001.conf",
                  "cluster-node-timeout 5000",
                  "appendonly yes", "appendfilename node_7001.aof",
                  "logfile /var/log/redis/redis-7001.log",
                  "save 900 1", "save 300 10", "save 60 10000",
                  ]
    for server in servers:
        rc = __get_remote_client(server, tid)
        if not rc:
            continue

        # upload the conf files
        wlogger.log(tid, "Uploading redis conf files...", "debug",
                    server_id=server.id)
        rc.put_file("/etc/redis/redis_7000.conf", "\n".join(master_conf))
        rc.put_file("/etc/redis/redis_7001.conf", "\n".join(slave_conf))
        # upload the modified init.d file
        rc.upload(os.path.join(
            app.root_path, "templates", "redis", "redis-server"),
            "/etc/init.d/redis-server")
        wlogger.log(tid, "Configuration upload complete.", "success",
                    server_id=server.id)

        wlogger.log(tid, "Updating the oxCacheConfiguration in LDAP", "debug",
                    server_id=server.id)
        try:
            dbm = DBManager(server.hostname, 1636, server.ldap_password,
                            ssl=True, ip=server.ip)
        except Exception as e:
            wlogger.log(tid, "Failed to connect to LDAP server. Error: \n"
                             "{0}".format(e), "error")
            continue
        entry = dbm.get_appliance_attributes('oxCacheConfiguration')
        cache_conf = json.loads(entry.oxCacheConfiguration.value)
        cache_conf['cacheProviderType'] = 'REDIS'
        cache_conf['redisConfiguration']['redisProviderType'] = 'CLUSTER'
        result = dbm.set_applicance_attribute('oxCacheConfiguration',
                                              [json.dumps(cache_conf)])
        if not result:
            wlogger.log(tid, "oxCacheConfiguration update failed", "error",
                        server_id=server.id)
        else:
            wlogger.log(tid, "Cache configuration update successful in LDAP",
                        "success", server_id=server.id)

    return True


def __get_remote_client(server, tid):
    rc = RemoteClient(server.hostname, ip=server.ip)
    try:
        rc.startup()
        wlogger.log(tid, "Connecting to server: {0}".format(server.hostname),
                    "success", server_id=server.id)
    except Exception as e:
        wlogger.log(tid, "Could not connect to the server over SSH. Error:"
                         "\n{0}".format(e), "error", server_id=server.id)
        return None
    return rc


def run_and_log(rc, cmd, tid, server_id=None):
    """Runs a command using the provided RemoteClient instance and logs the
    cout and cerr to the wlogger using the task id and server id

    :param rc: the remote client to run the command
    :param cmd: command that has to be executed
    :param tid: the task id of the celery task for logging
    :param server_id: OPTIONAL id of the server in which the cmd is executed
    :return: nothing
    """
    wlogger.log(tid, cmd, "debug", server_id=server_id)
    _, cout, cerr = rc.run(cmd)
    if cout:
        wlogger.log(tid, cout, "debug", server_id=server_id)
    if cerr:
        wlogger.log(tid, cerr, "cerror", server_id=server_id)


@celery.task(bind=True)
def restart_services(self, method, server_id_list):
    tid = self.request.id

    appconf = AppConfiguration.query.first()
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    ips = []

    for server_id in server_id_list:
        server = Server.query.get(server_id)
        ips.append(server.ip)
        wlogger.log(tid, "(Re)Starting services ... ", "info",
                    server_id=server.id)
        rc = __get_remote_client(server, tid)
        if not rc:
            continue

        def get_cmd(cmd):
            if server.gluu_server and not server.os == "CentOS 7":
                return 'chroot {0} /bin/bash -c "{1}"'.format(chdir, cmd)
            elif "CentOS 7" == server.os:
                parts = ["ssh", "-o IdentityFile=/etc/gluu/keys/gluu-console",
                         "-o Port=60022", "-o LogLevel=QUIET",
                         "-o StrictHostKeyChecking=no",
                         "-o UserKnownHostsFile=/dev/null",
                         "-o PubkeyAuthentication=yes",
                         "root@localhost", "'{0}'".format(cmd)]
                return " ".join(parts)
            return cmd

        # Common restarts for all
        if server.os == 'CentOS 6':
            run_and_log(rc, 'service redis restart', tid, server.id)
            run_and_log(rc, 'service stunnel4 restart', tid, server.id)
        elif server.os == 'CentOS 7' or server.os == 'RHEL 7':
            run_and_log(rc, 'systemctl restart redis', tid, server.id)
            run_and_log(rc, 'systemctl restart stunnel', tid, server.id)
        else:
            run_and_log(rc, 'service redis-server restart', tid, server.id)
            run_and_log(rc, 'service stunnel4 restart', tid, server.id)
            # sometime apache service is stopped (happened in Ubuntu 16)
            # when install_cache_components task is executed; hence we also need to
            # restart the service
            run_and_log(rc, get_cmd('service apache2 restart'), tid, server.id)



        restart_command  = 'service gluu-server-{0} restart'.format(
                                                        appconf.gluu_version)

        if 'CentOS' in server.os or 'RHEL' in server.os:
            restart_command   = '/sbin/gluu-serverd-{0} restart'.format(
                                                        appconf.gluu_version)
         
        wlogger.log(tid, "(Re)Starting Gluu Server", "info", server_id=server.id)

        run_and_log(rc, restart_command, tid, server.id)


        #wlogger.log(tid, "(Re)Starting oxauth", "info", server_id=server.id)

        #run_and_log(rc, get_cmd('service oxauth restart'), tid, server.id)
        
        #wlogger.log(tid, "(Re)Starting identity", "info", server_id=server.id)
        
        #run_and_log(rc, get_cmd('service identity restart'), tid, server.id)
        
        rc.close()

    if method != 'STANDALONE':
        wlogger.log(tid, "All services restarted.", "success")
        return

    
    mock_server = Server()
    
    if appconf.external_load_balancer:
        host = appconf.cache_host
    else:
        host = appconf.nginx_host
        
    
    mock_server.hostname = host
    rc = __get_remote_client(mock_server, tid)
    if not rc:
        wlogger.log(tid, "Couldn't connect to proxy server to restart services"
                    "fail")
        return
    mock_server.os = get_os_type(rc)
    if mock_server.os in ['Ubuntu 14', 'Ubuntu 16', 'CentOS 6']:
        run_and_log(rc, "service stunnel4 restart", tid, None)
        run_and_log(rc, "service nutcracker restart", tid, None)
    if mock_server.os in ["CentOS 7", "RHEL 7"]:
        run_and_log(rc, "systemctl restart stunnel", tid, None)
        run_and_log(rc, "systemctl restart nutcracker", tid, None)
    rc.close()


@celery.task(bind=True)
def get_cache_methods(self):
    tid = self.request.id
    servers = Server.query.all()
    methods = []
    for server in servers:
        try:
            dbm = DBManager(server.hostname, 1636, server.ldap_password,
                            ssl=True, ip=server.ip)
        except LDAPSocketOpenError as e:
            wlogger.log(tid, "Couldn't connect to server {0}. Error: "
                             "{1}".format(server.hostname, e), "error")
            continue

        entry = dbm.get_appliance_attributes('oxCacheConfiguration')
        cache_conf = json.loads(entry.oxCacheConfiguration.value)
        server.cache_method = cache_conf['cacheProviderType']
        if server.cache_method == 'REDIS':
            method = cache_conf['redisConfiguration']['redisProviderType']
            server.cache_method += " - " + method
        db.session.commit()
        methods.append({"id": server.id, "method": server.cache_method})
    wlogger.log(tid, "Cache Methods of servers have been updated.", "success")
    return methods
