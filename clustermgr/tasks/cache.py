import json
import os
import re
import socket


from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import DBManager
from clustermgr.tasks.cluster import get_os_type, run_command
from clustermgr.core.utils import parse_setup_properties, \
        get_redis_config, make_proxy_stunnel_conf, make_twem_proxy_conf

from ldap3.core.exceptions import LDAPSocketOpenError
from flask import current_app as app


class BaseInstaller(object):
    """Base class for component installers.

    Args:
        server (class:`clustermgr.models.Server`): the server object denoting
            the server where server should be installed
        tid (string): the task id of the celery task to add logs
    """

    def __init__(self, server, tid):
        self.server = server
        self.tid = tid
        self.rc = RemoteClient(server.hostname, ip=server.ip)

    def install(self):
        """install() detects the os of the server and calls the appropriate
        function to install redis on that server.

        Returns:
            boolean status of the install process
        """
        try:
            self.rc.startup()
        except Exception as e:
            wlogger.log(self.tid, "Could not connect to {0}".format(e),
                        "error", server_id=self.server.id)
            return False

        cin, cout, cerr = self.rc.run("ls /etc/*release")
        files = cout.split()
        cin, cout, cerr = self.rc.run("cat " + files[0])

        status = False
        if "Ubuntu" in cout:
            status = self.install_in_ubuntu()
        elif "CentOS" in cout or 'Red Hat' in cout:
            status = self.install_in_centos()
        else:
            wlogger.log(self.tid, "Server OS is not supported. {0}".format(
                cout), "error", server_id=self.server.id)
        self.rc.close()
        return status

    def install_in_ubuntu(self):
        """This method should be overridden by the sub classes. Run the
        commands needed to install your component.

        Returns:
            boolean status of success of the install
        """
        pass

    def install_in_centos(self):
        """This method should be overridden by the sub classes. Run the
        commands needed to install your component.

        Returns:
            boolean status of success of the install
        """
        pass

    def run_command(self, cmd):
        wlogger.log(self.tid, cmd, "debug", server_id=self.server.id)
        return self.rc.run(cmd)


class RedisInstaller(BaseInstaller):
    """RedisInstaller installs redis-server in the provided server. Refer to
    `BaseInstaller` for docs.
    """

    def install_in_ubuntu(self):
        self.run_command("apt-get update")

        if self.server.os in ('Ubuntu 14','Debian 8'):
            version_number = 14
        else:
            version_number = 16

        cmd_list = [
            'wget https://github.com/mbaser/gluu/raw/master/redis/ubuntu{}/redis-tools_4.0.11-1_amd64.deb -O /tmp/redis-tools_4.0.11-1_amd64.deb'.format(version_number),
            'wget https://github.com/mbaser/gluu/raw/master/redis/ubuntu{}/redis-server_4.0.11-1_amd64.deb -O /tmp/redis-server_4.0.11-1_amd64.deb'.format(version_number),
            'DEBIAN_FRONTEND=noninteractive dpkg -i /tmp/redis*.deb',
            ]

        for cmd in cmd_list:
            cin, cout, cerr = self.run_command(cmd)
            if cerr and not 'Saving to:' in cerr:
                wlogger.log(self.tid, cerr, "cerror", server_id=self.server.id)
                return False
            else:
                wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        
        return True

    def install_in_centos(self):
        # To automatically start redis on boot
        # systemctl enable redis
        # MB: Do we need to update ?
        #self.run_command("yum update -y")
        self.run_command("yum install epel-release -y")
        #self.run_command("yum update -y")

        if self.server.os in ('CentOS 6','RHEL 6'):
            cmd_list = ('yum install -y https://github.com/mbaser/gluu/raw/master/redis/centos6/redis-4.0.11-1.centos6.x86_64.rpm',
                        'yum install -y http://dl.fedoraproject.org/pub/epel/6/x86_64/Packages/j/jemalloc-3.6.0-1.el6.x86_64.rpm',
                        )

        else:
            cmd_list = ('yum install -y https://github.com/mbaser/gluu/raw/master/redis/centos7/redis-4.0.11-1.centos7.x86_64.rpm',
                        'yum install -y http://dl.fedoraproject.org/pub/epel/7/x86_64/Packages/j/jemalloc-3.6.0-1.el7.x86_64.rpm',
                        )

        for install_cmd in cmd_list:

            cin, cout, cerr = self.run_command(install_cmd)
            wlogger.log(self.tid, cout, "debug", server_id=self.server.id)

            if cerr:
                wlogger.log(self.tid, cerr, "cerror", server_id=self.server.id)
                return False


        if self.server.os in ('CentOS 6','RHEL 6'):
            cin, cout, cerr = self.run_command("chkconfig --add redis")
            wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
            
            cin, cout, cerr = self.run_command("chkconfig --level 345 redis on")
            wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        else:
            cin, cout, cerr = self.run_command("systemctl enable redis")
            wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        
        return True

class StunnelInstaller(BaseInstaller):
    def install_in_ubuntu(self):
        self.run_command("apt-get update")
        cin, cout, cerr = self.run_command("DEBIAN_FRONTEND=noninteractive apt-get install stunnel4 -y")
        wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        if cerr:
            wlogger.log(self.tid, cerr, "cerror", server_id=self.server.id)

        # Verifying installation by trying to reinstall
        cin, cout, cerr = self.rc.run("DEBIAN_FRONTEND=noninteractive apt-get install stunnel4 -y")
        if "stunnel4 is already the newest version" in cout:
            return True
        else:
            return False

    def install_in_centos(self):
        #self.run_command("yum update -y")
        cin, cout, cerr = self.run_command("yum install stunnel -y")
        wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        if cerr:
            wlogger.log(self.tid, cerr, "cerror", server_id=self.server.id)
        # verifying installation
        cin, cout, cerr = self.rc.run("yum install stunnel -y")
        if "already installed" in cout:
            return True
        else:
            return False


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
    
    tid = self.request.id
    installed = 0
    
    servers = []

    for server_id in server_id_list:
        
        server = Server.query.get(server_id)
        
        ri = RedisInstaller(server, tid)
        ri.rc.startup()
        if ri.rc.exists('/usr/bin/redis-server') or ri.rc.exists('/bin/redis-server'):
            server.redis = True
            redis_installed = 1
            wlogger.log(tid, "Redis was already installed on server {0}".format(
                server.hostname), "info", server_id=server.id)
        else:
            wlogger.log(tid, "Installing Redis in server {0}".format(
                server.hostname), "info", server_id=server.id)
            redis_installed = ri.install()
            if redis_installed:
                server.redis = True
                wlogger.log(tid, "Redis install successful", "success",
                            server_id=server.id)
            else:
                server.redis = False
                wlogger.log(tid, "Redis install failed", "fail",
                            server_id=server.id)

        si = StunnelInstaller(server, tid)
        si.rc.startup()
        if si.rc.exists('/usr/bin/stunnel') or si.rc.exists('/bin/stunnel'):
            wlogger.log(tid, "Stunnel was allready installed", "info", server_id=server.id)
            server.stunnel = True
            stunnel_installed = 1
        else:
            wlogger.log(tid, "Installing Stunnel", "info", server_id=server.id)
            
            stunnel_installed = si.install()
            if stunnel_installed:
                server.stunnel = True
                wlogger.log(tid, "Stunnel install successful", "success",
                            server_id=server.id)
            else:
                server.stunnel = False
                wlogger.log(tid, "Stunnel install failed", "fail",
                            server_id=server.id)
            # Save the redis and stunnel install situation to the db
            

        if redis_installed and stunnel_installed:
            installed += 1

        db.session.commit()
    if method != 'STANDALONE':
        # No need to install twemproxy for "SHARDED" configuration
        return True

    # Install twemproxy in the Nginx load balancing proxy server
    app_conf = AppConfiguration.query.first()
    
    mock_server = Server()
    
    if app_conf.external_load_balancer:
        mock_server.hostname = app_conf.cache_host
        mock_server.ip = app_conf.cache_ip
    else:
        mock_server.hostname = app_conf.nginx_host
        mock_server.ip = app_conf.nginx_ip


    rc = RemoteClient(mock_server.hostname)

    try:
        rc.startup()
    except Exception as e:
        wlogger.log(tid, "Could not connect to {0}".format(e), "error")
        return False

    server_os = get_os_type(rc)

    
    si = StunnelInstaller(mock_server, tid)
    si.rc.startup()
    stunnel_installed = 0
    if si.rc.exists('/usr/bin/stunnel') or si.rc.exists('/bin/stunnel'):
        wlogger.log(tid, "Stunnel was already installed on cache server")
        stunnel_installed = 1
    else:
        wlogger.log(tid, "Installing Stunnel in cache server")    
        stunnel_installed = si.install()
        if stunnel_installed:
            wlogger.log(tid, "Stunnel install successful", "success")
        else:
            wlogger.log(tid, "Stunnel install failed", "fail")

    print rc.exists('/usr/sbin/nutcracker')

    if not rc.exists('/usr/sbin/nutcracker'):

        wlogger.log(tid, "Installing Twemproxy")
        # 1. Setup the development tools for installation
        if server_os == "Ubuntu 14":
            run_and_log(rc, "apt-get update", tid)
            run_and_log(rc, 'wget http://ftp.debian.org/debian/pool/main/n/nutcracker/nutcracker_0.4.0+dfsg-1_amd64.deb -O /tmp/nutcracker_0.4.0+dfsg-1_amd64.deb', tid)
            run_and_log(rc, "dpkg -i /tmp/nutcracker_0.4.0+dfsg-1_amd64.deb", tid)
        elif server_os == "Ubuntu 16":
            run_and_log(rc, "apt-get update", tid)
            run_and_log(rc, "DEBIAN_FRONTEND=noninteractive apt-get install -y nutcracker", tid)
        elif server_os in ["CentOS 7", "RHEL 7"]:
            run_and_log(rc, 'yum install -y https://raw.githubusercontent.com/mbaser/gluu/master/nutcracker-0.4.1-1.gluu.centos7.x86_64.rpm', tid)
            run_and_log(rc, 'chkconfig nutcracker on', tid)
        elif server_os in ['CentOS 6', 'RHEL 6']:
            run_and_log(rc, 'yum install -y https://raw.githubusercontent.com/mbaser/gluu/master/nutcracker-0.4.1-1.gluu.centos6.x86_64.rpm', tid)
            run_and_log(rc, 'chkconfig nutcracker on', tid)

        # 5. Create the default configuration file referenced in the init scripts
        #run_and_log(rc, "mkdir -p /etc/nutcracker", tid)
        run_and_log(rc, "touch /etc/nutcracker/nutcracker.yml", tid)
    else:
        wlogger.log(tid, "Twemproxy was already installed on cache server")
    rc.close()
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


def __configure_stunnel(tid, server, stunnel_conf, chdir, setup_props=None):
    """Sets up Stunnel with given configuration, init or service scripts,
    SSL certificate ...etc., for use in a server

    :param tid: task id for log identification
    :param server: :object:`clustermgr.models.Server` where stunnel needs to be
        setup
    :param stunnel_conf: list of lines for the stunnel config file
    :param chdir: chroot directory to find out the setup.properties file and
        extract the required values to generate a SSL certificate
    :param setup_props: Optional - location of setup.properties file to get the
        details for SSL Cert generation for Stunnel
    :return: boolean status fo the operation
    """
    wlogger.log(tid, "Setting up stunnel on " + server.hostname, "info", server_id=server.id)
    rc = __get_remote_client(server, tid)
    if not rc:
        wlogger.log(tid, "Stunnel setup failed on " + server.hostname, "error", server_id=server.id)
        return False

    if not server.os:
        server.os = get_os_type(rc)

    wlogger.log(tid, "Adding init/service scripts of boot time startup",
                "info", server_id=server.id)
    # replace the /etc/default/stunnel4 to enable start on system startup
    local = os.path.join(app.root_path, 'templates', 'stunnel',
                         'stunnel4.default')
    remote = '/etc/default/stunnel4'
    rc.upload(local, remote)

    if 'CentOS 6' == server.os:
        local = os.path.join(app.root_path, 'templates', 'stunnel',
                             'centos.init')
        remote = '/etc/rc.d/init.d/stunnel4'
        rc.upload(local, remote)
        rc.run("chmod +x {0}".format(remote))

    if 'CentOS 7' == server.os or 'RHEL 7' == server.os:
        local = os.path.join(app.root_path, 'templates', 'stunnel',
                             'stunnel.service')
        remote = '/lib/systemd/system/stunnel.service'
        rc.upload(local, remote)
        rc.run("mkdir -p /var/log/stunnel4")
        wlogger.log(tid, "Setup auto-start on system boot", "info",
                    server_id=server.id)
        run_and_log(rc, 'systemctl enable redis', tid, server.id)
        run_and_log(rc, 'systemctl enable stunnel', tid, server.id)

    #if certificate of stunnel does not exists, create it
    if not rc.exists("/etc/stunnel/cert.pem"):
        # setup the certificate file
        wlogger.log(tid, "Generating certificate for stunnel ...", "debug",
                    server_id=server.id)
        
        if setup_props:
            propsfile = setup_props
        else:
            propsfile = os.path.join(chdir, "install", "community-edition-setup",
                                     "setup.properties.last")

        prop_buffer = rc.get_file(propsfile)[1]

        props = parse_setup_properties(prop_buffer.readlines())

        subject = "'/C={countryCode}/ST={state}/L={city}/O={orgName}/CN={hostname}" \
                  "/emailAddress={admin_email}'".format(**props)
        cert_path = "/etc/stunnel/server.crt"
        key_path = "/etc/stunnel/server.key"
        pem_path = "/etc/stunnel/cert.pem"
        cmd = ["/usr/bin/openssl", "req", "-subj", subject, "-new", "-newkey",
               "rsa:2048", "-sha256", "-days", "365", "-nodes", "-x509",
               "-keyout", key_path, "-out", cert_path]
        rc.run(" ".join(cmd))
        rc.run("cat {cert} {key} > {pem}".format(cert=cert_path, key=key_path,
                                                 pem=pem_path))
        # verify certificate
        cin, cout, cerr = rc.run("/usr/bin/openssl verify " + pem_path)
        if props['hostname'] in cout and props['orgName'] in cout:
            wlogger.log(tid, "Certificate generated successfully", "success",
                        server_id=server.id)
        else:
            wlogger.log(tid, "/usr/bin/openssl verify " + pem_path, "debug")
            wlogger.log(tid, cerr, "cerror")
            wlogger.log(tid, "Certificate generation failed. Add a SSL "
                             "certificate at /etc/stunnel/cert.pem", "error",
                        server_id=server.id)

    # Generate stunnel config
    wlogger.log(tid, "Setup stunnel listening and forwarding", "debug",
                server_id=server.id)
    rc.put_file("/etc/stunnel/stunnel.conf", "\n".join(stunnel_conf))
    return True


def __update_LDAP_cache_method(tid, server, server_string, method):
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
        dbm = DBManager(server.hostname, 1636, server.ldap_password,
                        ssl=True, ip=server.ip, )
    except Exception as e:
        wlogger.log(tid, "Couldn't connect to LDAP. Error: {0}".format(e),
                    "error", server_id=server.id)
        wlogger.log(tid, "Make sure your LDAP server is listening to "
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
        wlogger.log(tid, "oxCacheConfigutaion update failed", "fail",
                    server_id=server.id)


def setup_proxied(tid, server_id_list):
    """Configures the servers to use the Twemproxy installed in proxy server
    for Redis caching securely via stunnel.

    :param tid: task id for log identification
    :return: None
    """
    
    servers = []
    
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

    appconf = AppConfiguration.query.first()
    chdir = "/opt/gluu-server-" + appconf.gluu_version


    if appconf.external_load_balancer:
        cache_ip = appconf.cache_ip
    else:
        cache_ip = appconf.nginx_ip
    
    primary = Server.query.filter(Server.primary_server.is_(True)).first()

    if not primary:
        wlogger.log(tid, "Primary Server is not setup yet. Cannot setup "
                    "clustered caching.", "error")


    # Setup Stunnel and Redis in each server
    for server in servers:
        #Since replication is active, we only need to update on primary server
        if server.primary_server:
            __update_LDAP_cache_method(tid, server, 'localhost:7000', 'STANDALONE')
       
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
     
        status = __configure_stunnel(tid, server, stunnel_conf, chdir)

        if not status:
            continue

    wlogger.log(tid, "Configuring the cahce server ...")
    
    # Setup Stunnel in the proxy server
    mock_server = Server()
    
    if appconf.external_load_balancer:
        mock_server.hostname = appconf.cache_host
        mock_server.ip = appconf.cache_ip
    else:
        mock_server.hostname = appconf.nginx_host
        mock_server.ip = appconf.nginx_ip
    
    rc = __get_remote_client(mock_server, tid)
    
    if not rc:
        wlogger.log(tid, "Couldn't connect to proxy server. Twemproxy setup "
                    "failed.", "error")
        return
    
    mock_server.os = get_os_type(rc)


    if rc.exists('/usr/bin/redis-server') or rc.exists('/bin/redis-server'):
        wlogger.log(tid, "Redis was already installed on server {0}".format(
                mock_server.hostname), "info")
    else:
        wlogger.log(tid, "Installing Redis in server {0}".format(
        mock_server.hostname), "info")
        ri = RedisInstaller(mock_server, tid)
        redis_installed = ri.install()
        if redis_installed:
            mock_server.redis = True
            wlogger.log(tid, "Redis install successful", "success")
        else:
            mock_server.redis = False
            wlogger.log(tid, "Redis install failed", "fail")


    # Download the setup.properties file from the primary server
    local = os.path.join(app.instance_path, "setup.properties")
    remote = os.path.join("/opt/gluu-server-"+appconf.gluu_version,
                          "install", "community-edition-setup",
                          "setup.properties.last")
    prc = __get_remote_client(primary, tid)
    prc.download(remote, local)
    prc.close()
    rc.upload(local, "/tmp/setup.properties")

    proxy_stunnel_conf = make_proxy_stunnel_conf()
    
    status = __configure_stunnel(tid, mock_server, proxy_stunnel_conf, None,
                                 "/tmp/setup.properties")
    if not status:
        return False

    # Setup Twemproxy
    wlogger.log(tid, "Writing Twemproxy configuration")
    twemproxy_conf = make_twem_proxy_conf()
    remote = "/etc/nutcracker/nutcracker.yml"
    rc.put_file(remote, twemproxy_conf)
    run_command(tid, rc, 'service nutcracker restart')

    wlogger.log(tid, "Configuration complete", "success")


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

        if 'CentOS 7' == server.os or 'RHEL 7' == server.os:
            restart_command   = '/sbin/gluu-serverd-{0} restart'.format(
                                                        appconf.gluu_version)
         
        wlogger.log(tid, "(Re)Starting Gluu Server", "info", server_id=server.id)

        run_and_log(rc, restart_command, tid, server.id)

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
    
    print mock_server.os
    
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
