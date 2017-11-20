import json
import os
import re
import socket

from StringIO import StringIO

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, celery, wlogger
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import DBManager
from clustermgr.tasks.cluster import get_os_type

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
        elif "CentOS" in cout:
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
        self.run_command("apt-get upgrade -y")
        self.run_command("apt-get install software-properties-common -y")
        self.run_command("add-apt-repository ppa:chris-lea/redis-server -y")
        self.run_command("apt-get update")
        cin, cout, cerr = self.run_command("apt-get install redis-server -y")
        wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        if cerr:
            wlogger.log(self.tid, cerr, "cerror", server_id=self.server.id)
        # verifying that redis-server is succesfully installed
        cin, cout, cerr = self.rc.run("apt-get install redis-server -y")

        if "redis-server is already the newest version" in cout:
            return True
        else:
            return False

    def install_in_centos(self):
        # To automatically start redis on boot
        # systemctl enable redis
        self.run_command("yum update -y")
        self.run_command("yum install epel-release -y")
        self.run_command("yum update -y")

        cin, cout, cerr = self.run_command("yum install redis -y")
        wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        if cerr:
            wlogger.log(self.tid, cerr, "cerror", server_id=self.server.id)
        # verifying installation
        cin, cout, cerr = self.rc.run("yum install redis -y")
        if "already installed" in cout:
            return True
        else:
            return False


class StunnelInstaller(BaseInstaller):
    def install_in_ubuntu(self):
        self.run_command("apt-get update")
        cin, cout, cerr = self.run_command("apt-get install stunnel4 -y")
        wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        if cerr:
            wlogger.log(self.tid, cerr, "cerror", server_id=self.server.id)

        # Verifying installation by trying to reinstall
        cin, cout, cerr = self.rc.run("apt-get install stunnel4 -y")
        if "stunnel4 is already the newest version" in cout:
            return True
        else:
            return False

    def install_in_centos(self):
        self.run_command("yum update -y")
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
def install_cache_components(self, method):
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
    servers = Server.query.all()
    for server in servers:
        wlogger.log(tid, "Installing Redis in server {0}".format(
            server.hostname), "info", server_id=server.id)
        ri = RedisInstaller(server, tid)
        redis_installed = ri.install()
        if redis_installed:
            server.redis = True
            wlogger.log(tid, "Redis install successful", "success",
                        server_id=server.id)
        else:
            server.redis = False
            wlogger.log(tid, "Redis install failed", "fail",
                        server_id=server.id)

        wlogger.log(tid, "Installing Stunnel", "info", server_id=server.id)
        si = StunnelInstaller(server, tid)
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
        db.session.commit()

        if redis_installed and stunnel_installed:
            installed += 1

    if method != 'STANDALONE':
        # No need to install twemproxy for "SHARDED" configuration
        return True

    # Install twemproxy in the Nginx load balancing proxy server
    app_conf = AppConfiguration.query.first()
    host = app_conf.nginx_host
    rc = RemoteClient(host)
    try:
        rc.startup()
    except Exception as e:
        wlogger.log(tid, "Could not connect to {0}".format(e), "error")
        return False

    server_os = get_os_type(rc)

    mock_server = Server()
    mock_server.hostname = host
    wlogger.log(tid, "Installing Stunnel in proxy server")
    si = StunnelInstaller(mock_server, tid)
    stunnel_installed = si.install()
    if stunnel_installed:
        wlogger.log(tid, "Stunnel install successful", "success")
    else:
        wlogger.log(tid, "Stunnel install failed", "fail")

    wlogger.log(tid, "Cluster manager will now try to build Twemproxy")
    # 1. Setup the development tools for installation
    if server_os in ["Ubuntu 16", "Ubuntu 14"]:
        run_and_log(rc, "apt-get update", tid)
        run_and_log(rc, "apt-get install -y build-essential autoconf libtool",
                    tid)
    elif server_os in ["CentOS 6", "CentOS 7", "RHEL 7"]:
        run_and_log(rc, "yum install -y wget", tid)
        run_and_log(rc, "yum groupinstall -y 'Development tools'", tid)

    if server_os == "CentOS 6":
        run_and_log(rc, "wget http://ftp.gnu.org/gnu/autoconf/autoconf-2.69.tar.gz",
                    tid)
        run_and_log(rc, "tar xvfvz autoconf-2.69.tar.gz", tid)
        run_and_log(rc, "cd autoconf-2.69 && ./configure", tid)
        run_and_log(rc, "cd autoconf-2.69 && make", tid)
        run_and_log(rc, "cd autoconf-2.69 && make install", tid)

    # 2. Get the source, build & install the nutcracker binaries
    run_and_log(rc, "wget https://github.com/twitter/twemproxy/archive/v0.4.1.tar.gz",
                tid)
    run_and_log(rc, "tar -xf v0.4.1.tar.gz", tid)
    run_and_log(rc, "cd twemproxy-0.4.1", tid)
    run_and_log(rc, "cd twemproxy-0.4.1 && autoreconf -fvi", tid)
    run_and_log(rc, "cd twemproxy-0.4.1 && ./configure --prefix=/usr", tid)
    run_and_log(rc, "cd twemproxy-0.4.1 && make", tid)
    run_and_log(rc, "cd twemproxy-0.4.1 && make install", tid)

    # 3. Post installation - setup user and logging
    run_and_log(rc, "useradd nutcracker", tid)
    run_and_log(rc, "mkdir /var/log/nutcracker", tid)
    run_and_log(rc, "touch /var/log/nutcracker/nutcracker.log", tid)
    run_and_log(rc, "chown -R nutcracker:nutcracker /var/log/nutcracker",
                tid)
    logrotate_conf = ["/var/log/nutcracker/nutcracker*.log {", "\tweekly",
                      "\tmissingok", "\trotate 12", "\tcompress",
                      "\tnotifempty", "}"]
    rc.put_file("/etc/logrotate.d/nutcracker", "\n".join(logrotate_conf))

    # 4. Add init/service scripts to run nutcracker as a service
    if server_os in ["Ubuntu 16", "CentOS 7", "RHEL 7"]:
        local = os.path.join(app.root_path, "templates", "twemproxy",
                             "twemproxy.service")
        remote = "/lib/systemd/system/nutcracker.service"
        rc.upload(local, remote)
        run_and_log(rc, "systemctl enable nutcracker", tid, None)
    elif server_os == "Ubuntu 14":
        local = os.path.join(app.root_path, "templates", "twemproxy",
                             "nutcracker.init")
        remote = "/etc/init.d/nutcracker"
        rc.upload(local, remote)
        run_and_log(rc, 'chmod +x /etc/init.d/nutcracker', tid)
        run_and_log(rc, "update-rc.d nutcracker defaults", tid)
    elif server_os == "CentOS 6":
        local = os.path.join(app.root_path, "templates", "twemproxy",
                             "nutcracker.centos.init")
        remote = "/etc/rc.d/init.d/nutcracker"
        rc.upload(local, remote)
        run_and_log(rc, "chmod +x /etc/init.d/nutcracker", tid)
        run_and_log(rc, "chkconfig --add nutcracker", tid)
        run_and_log(rc, "chkconfig nutcracker on", tid)

    # 5. Create the default configuration file referenced in the init scripts
    run_and_log(rc, "mkdir -p /etc/nutcracker", tid)
    run_and_log(rc, "touch /etc/nutcracker/nutcracker.yml", tid)

    rc.close()
    return installed


@celery.task(bind=True)
def configure_cache_cluster(self, method):
    if method == 'SHARDED':
        return setup_sharded(self.request.id)
    elif method == 'STANDALONE':
        return setup_proxied(self.request.id)
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
    wlogger.log(tid, "Setting up stunnel", "info", server_id=server.id)
    rc = __get_remote_client(server, tid)
    if not rc:
        wlogger.log(tid, "Stunnel setup failed", "error", server_id=server.id)
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

    # setup the certificate file
    wlogger.log(tid, "Generating certificate for stunnel ...", "debug",
                server_id=server.id)
    prop_buffer = StringIO()
    if setup_props:
        propsfile = setup_props
    else:
        propsfile = os.path.join(chdir, "install", "community-edition-setup",
                                 "setup.properties.last")

    rc.sftpclient.getfo(propsfile, prop_buffer)
    prop_buffer.seek(0)
    props = dict()

    def prop_in(string):
        return string.split("=")[1].strip()

    for line in prop_buffer:
        if re.match('^countryCode', line):
            props['country'] = prop_in(line)
        if re.match('^state', line):
            props['state'] = prop_in(line)
        if re.match('^city', line):
            props['city'] = prop_in(line)
        if re.match('^orgName', line):
            props['org'] = prop_in(line)
        if re.match('^hostname', line):
            props['cn'] = prop_in(line)
        if re.match('^admin_email', line):
            props['email'] = prop_in(line)

    subject = "'/C={country}/ST={state}/L={city}/O={org}/CN={cn}" \
              "/emailAddress={email}'".format(**props)
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
    if props['cn'] in cout and props['org'] in cout:
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
    """Connects to LDAP and updates the cache method and the cache servers

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


def setup_proxied(tid):
    """Configures the servers to use the Twemproxy installed in proxy server
    for Redis caching securely via stunnel.

    :param tid: task id for log identification
    :return: None
    """
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    appconf = AppConfiguration.query.first()
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    stunnel_base_conf = [
        "cert = /etc/stunnel/cert.pem",
        "pid = /var/run/stunnel.pid",
        "output = /var/log/stunnel4/stunnel.log"
    ]
    proxy_stunnel_conf = stunnel_base_conf
    twemproxy_servers = []
    proxy_ip = socket.gethostbyname(appconf.nginx_host)
    primary = Server.query.filter(Server.primary_server.is_(True)).first()
    if not primary:
        wlogger.log(tid, "Primary Server is not setup yet. Cannot setup "
                    "clustered caching.", "error")


    # Setup Stunnel and Redis in each server
    for server in servers:
        __update_LDAP_cache_method(tid, server, 'localhost:7000', 'STANDALONE')
        stunnel_conf = [
            "[redis-server]",
            "client = no",
            "accept = {0}:7777".format(server.ip),
            "connect = 127.0.0.1:6379",
            "[twemproxy]",
            "client = yes",
            "accept = 127.0.0.1:7000",
            "connect = {0}:8888".format(proxy_ip)
        ]
        stunnel_conf = stunnel_base_conf + stunnel_conf
        status = __configure_stunnel(tid, server, stunnel_conf, chdir)
        if not status:
            continue

        # if the setup was successful add the server to the list of stunnel
        # clients in the proxy server configuration
        client_conf = [
            "[client{0}]".format(server.id),
            "client = yes",
            "accept = 127.0.0.1:{0}".format(7000+server.id),
            "connect = {0}:7777".format(server.ip)
        ]
        proxy_stunnel_conf.extend(client_conf)
        twemproxy_servers.append("   - 127.0.0.1:{0}:1".format(7000+server.id))


    wlogger.log(tid, "Configuring the proxy server ...")
    # Setup Stunnel in the proxy server
    mock_server = Server()
    mock_server.hostname = appconf.nginx_host
    mock_server.ip = proxy_ip
    rc = __get_remote_client(mock_server, tid)
    if not rc:
        wlogger.log(tid, "Couldn't connect to proxy server. Twemproxy setup "
                    "failed.", "error")
        return
    mock_server.os = get_os_type(rc)
    # Download the setup.properties file from the primary server
    local = os.path.join(app.instance_path, "setup.properties")
    remote = os.path.join("/opt/gluu-server-"+appconf.gluu_version,
                          "install", "community-edition-setup",
                          "setup.properties.last")
    prc = __get_remote_client(primary, tid)
    prc.download(remote, local)
    prc.close()
    rc.upload(local, "/tmp/setup.properties")

    twem_server_conf = [
        "[twemproxy]",
        "client = no",
        "accept = {0}:8888".format(proxy_ip),
        "connect = 127.0.0.1:2222"
    ]
    proxy_stunnel_conf.extend(twem_server_conf)
    status = __configure_stunnel(tid, mock_server, proxy_stunnel_conf, None,
                                 "/tmp/setup.properties")
    if not status:
        return False

    # Setup Twemproxy
    wlogger.log(tid, "Writing Twemproxy configuration")
    twemproxy_conf = [
        "alpha:",
        "  listen: 127.0.0.1:2222",
        "  hash: fnv1a_64",
        "  distribution: ketama",
        "  auto_eject_hosts: true",
        "  redis: true",
        "  server_failure_limit: 2",
        "  timeout: 400",
        "  preconnect: true",
        "  servers:"
    ]
    twemproxy_conf.extend(twemproxy_servers)
    remote = "/etc/nutcracker/nutcracker.yml"
    rc.put_file(remote, "\n".join(twemproxy_conf))

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
def restart_services(self, method):
    tid = self.request.id
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    appconf = AppConfiguration.query.first()
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    ips = []

    for server in servers:
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

        run_and_log(rc, get_cmd('service oxauth restart'), tid, server.id)
        run_and_log(rc, get_cmd('service identity restart'), tid, server.id)
        rc.close()

    if method != 'STANDALONE':
        wlogger.log(tid, "All services restarted.", "success")
        return

    host = appconf.nginx_host
    mock_server = Server()
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
