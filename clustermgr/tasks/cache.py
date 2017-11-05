import json
import os
import re

from StringIO import StringIO

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, celery, wlogger
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import DBManager
from clustermgr.core.task_runner import YAMLTaskRunner

from ldap3.core.exceptions import LDAPSocketOpenError
from flask import current_app as app


@celery.task(bind=True)
def install_redis_stunnel(self):
    """Celery task that installs the redis and stunnel software in the given
    list of servers.
    """
    tid = self.request.id
    servers = Server.query.all()
    task_file = os.path.join(app.root_path, "tasks",
                             "install_redis_stunnel.yaml")

    wlogger.log(tid, "Setting up Redis", "info")
    for server in servers:
        wlogger.log(tid, "Server: {0}".format(server.hostname))
        tr = YAMLTaskRunner(task_file, server.hostname, server.ip)
        tr.run_tasks(weblog_id=tid)
        server.redis = True
        server.stunnel = True
        db.session.commit()


@celery.task(bind=True)
def configure_cache_cluster(self, method):
    if method == 'SHARDED':
        return setup_sharded(self.request.id)
    elif method == 'STANDALONE':
        return setup_sharded(self.request.id, standalone=True)
    elif method == 'CLUSTER':
        return setup_redis_cluster(self.request.id)


def setup_sharded(tid, standalone=False):
    """Function that adds the stunnel configuration to all the servers and
    maps the ports in the LDAP configuration.
    """
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    appconf = AppConfiguration.query.first()
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    # Store the redis server info in the LDA
    for server in servers:
        wlogger.log(tid, "Updating oxCacheConfiguration ...", "debug",
                    server_id=server.id)
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

        server_string = ",".join(redis_instances)

        try:
            dbm = DBManager(server.hostname, 1636, server.ldap_password,
                            ssl=True, ip=server.ip, )
        except Exception as e:
            wlogger.log(tid, "Couldn't connect to LDAP. Error: {0}".format(e),
                        "error", server_id=server.id)
            wlogger.log(tid, "Make sure your LDAP server is listening to "
                             "connections from outside", "debug",
                        server_id=server.id)
            continue
        entry = dbm.get_appliance_attributes('oxCacheConfiguration')
        cache_conf = json.loads(entry.oxCacheConfiguration.value)
        cache_conf['cacheProviderType'] = 'REDIS'
        cache_conf['redisConfiguration']['redisProviderType'] = 'SHARDED'
        if standalone:
            cache_conf['redisConfiguration'][
                'redisProviderType'] = 'STANDALONE'
        cache_conf['redisConfiguration']['servers'] = server_string

        result = dbm.set_applicance_attribute('oxCacheConfiguration',
                                              [json.dumps(cache_conf)])
        if not result:
            wlogger.log(tid, "oxCacheConfigutaion update failed", "fail",
                        server_id=server.id)
            continue

        # generate stunnel configuration and upload it to the server
        wlogger.log(tid, "Setting up stunnel", "info", server_id=server.id)

        rc = __get_remote_client(server, tid)
        if not rc:
            continue

        wlogger.log(tid, "Enable stunnel start on system boot", "debug",
                    server_id=server.id)
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
            rc.run(rc, 'systemctl enable redis', tid, server.id)
            rc.run(rc, 'systemctl enable stunnel', tid, server.id)

        # setup the certificate file
        wlogger.log(tid, "Generating certificate for stunnel ...", "debug",
                    server_id=server.id)
        prop_buffer = StringIO()
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
            wlogger.log(tid, "Certificate generation failed. Add a SSL "
                             "certificate at /etc/stunnel/cert.pem", "error",
                        server_id=server.id)

        # Generate stunnel config
        wlogger.log(tid, "Setup stunnel listening and forwarding", "debug",
                    server_id=server.id)
        rc.put_file("/etc/stunnel/stunnel.conf", "\n".join(stunnel_conf))
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


@celery.task(bind=True)
def restart_services(self, method):
    tid = self.request.id
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    appconf = AppConfiguration.query.first()
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    task_file = os.path.join(app.root_path, "tasks",
                             "restart_redis_services.yaml")

    for server in servers:
        tr = YAMLTaskRunner(task_file, server.hostname, server.ip)
        tr.run_tasks(weblog_id=tid, requirements=dict(chdir=chdir))


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
