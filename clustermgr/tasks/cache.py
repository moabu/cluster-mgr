import json
import os
import re

from StringIO import StringIO

from clustermgr.core.utils import split_redis_cluster_slots
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

    for server in servers:
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
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    appconf = AppConfiguration.query.first()
    # Store the redis server info in the LDA
    for server in servers:
        wlogger.log(tid, "Updating oxCacheConfiguration ...", "debug",
                    server_id=server.id)
        redis_instances = []
        stunnel_conf = [
            "cert = /etc/stunnel/cert.pem",
            "pid = /var/run/stunnel.pid",
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
        chdir = '/'
        if server.gluu_server:
            chdir = "/opt/gluu-server-{0}".format(appconf.gluu_version)

        rc = RemoteClient(server.hostname, ip=server.ip)
        try:
            rc.startup()
        except Exception as e:
            wlogger.log(tid, "Could not connect to the server over SSH. "
                             "Stunnel setup failed. Error: {0}".format(e),
                        "error",
                        server_id=server.id)
            continue

        wlogger.log(tid, "Enable stunnel start on system boot", "debug",
                    server_id=server.id)
        # replace the /etc/default/stunnel4 to enable start on system startup
        local = os.path.join(app.root_path, 'templates', 'stunnel',
                             'stunnel4.default')
        remote = os.path.join(chdir, 'etc/default/stunnel4')
        rc.upload(local, remote)

        if 'CentOS' in server.os:
            local = os.path.join(app.root_path, 'templates', 'stunnel',
                                 'centos.init')
            remote = os.path.join(chdir, 'etc/rc.d/init.d/stunnel4')
            rc.upload(local, remote)
            rc.run("chmod +x {0}".format(remote))

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
        cert_path = os.path.join(chdir, "etc", "stunnel", "server.crt")
        key_path = os.path.join(chdir, "etc", "stunnel", "server.key")
        pem_path = os.path.join(chdir, "etc", "stunnel", "cert.pem")
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
        rc.put_file(os.path.join(chdir, "etc/stunnel/stunnel.conf"),
                    "\n".join(stunnel_conf))
    return True


def setup_redis_cluster(tid):
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    appconf = AppConfiguration.query.first()

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
        rc = get_remote_client(server, tid)
        if not rc:
            continue

        chdir = '/'
        if server.gluu_server:
            chdir = "/opt/gluu-server-{0}".format(appconf.gluu_version)
        # upload the conf files
        wlogger.log(tid, "Uploading redis conf files...", "debug",
                    server_id=server.id)
        rc.put_file(os.path.join(chdir, "etc/redis/redis_7000.conf"),
                    "\n".join(master_conf))
        rc.put_file(os.path.join(chdir, "etc/redis/redis_7001.conf"),
                    "\n".join(slave_conf))
        # upload the modified init.d file
        rc.upload(os.path.join(
            app.root_path, "templates", "redis", "redis-server"),
            os.path.join(chdir, "etc/init.d/redis-server"))
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


def get_remote_client(server, tid):
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


def run_and_log(rc, cmd, tid, server_id):
    """Runs a command using the provided RemoteClient instance and logs the
    cout and cerr to the wlogger using the task id and server id

    :param rc: the remote client to run the command
    :param cmd: command that has to be executed
    :param tid: the task id of the celery task for logging
    :param server_id: id of the server in which the cmd is excuted
    :return: nothing
    """
    wlogger.log(tid, cmd, "debug", server_id=server_id)
    _, cout, cerr = rc.run(cmd)
    if cout:
        wlogger.log(tid, cout, "debug", server_id=server_id)
    if cerr:
        wlogger.log(tid, cerr, "warning", server_id=server_id)


@celery.task(bind=True)
def finish_cluster_setup(self, method):
    tid = self.request.id
    servers = Server.query.filter(Server.redis.is_(True)).filter(
        Server.stunnel.is_(True)).all()
    appconf = AppConfiguration.query.first()
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    ips = []
    task_file = os.path.join(app.root_path, "tasks",
                             "restart_redis_services.yaml")

    for server in servers:
        ips.append(server.ip)
        tr = YAMLTaskRunner(task_file, server.hostname, server.ip)
        tr.run_tasks(weblog_id=tid, requirements=dict(chdir=chdir))

    if method == 'SHARDED':
        return True

    # If redis-cluster is requested, then we need to setup cluster manually
    # iterate through the servers and find the one which can be accessed
    wlogger.log(tid, "Setting up redis cluster", "info")
    init_client = None
    initializer = None
    for server in servers:
        initializer = server
        init_client = get_remote_client(server, tid)
        if init_client:
            break

    if not init_client:
        wlogger.log(tid, "Cannot connect even a single server. Redis-cluster"
                         " setup failed", "error")

    for i, ip in enumerate(ips):
        # add all the masters and create a cluster
        meet_cmd = "redis-cli -c -h 127.0.0.1 -p 7000 cluster meet {0} 7000".format(
            ip)

        if initializer.gluu_server:
            meet_cmd = 'chroot {0} /bin/bash -c "{1}"'.format(chdir, meet_cmd)

        if ip is not initializer.ip:
            wlogger.log(tid, meet_cmd, "debug")
            init_client.run(meet_cmd)

    # Connect to each server and assign the slots
    slot_ranges = split_redis_cluster_slots(len(ips))
    for i, server in enumerate(servers):
        range_str = "{{{0}..{1}}}".format(*slot_ranges[i])
        slot_cmd = "for slot in {0}; do redis-cli -h localhost -p 7000 " \
                   "CLUSTER ADDSLOTS \$slot; done;".format(range_str)
        rc = get_remote_client(server, tid)
        if initializer.gluu_server:
            slot_cmd = 'chroot {0} /bin/bash -c "{1}"'.format(chdir, slot_cmd)
        wlogger.log(tid, slot_cmd, "debug")
        rc.run(slot_cmd)
        rc.close()

    # TODO Setup slaves to replicate the masters

    status_cmd = "redis-cli -p 7000 cluster nodes"
    if initializer.gluu_server:
        status_cmd = 'chroot {0} /bin/bash -c "{1}"'.format(chdir, status_cmd)
    wlogger.log(tid, status_cmd, "debug")
    reply = init_client.run(status_cmd)
    wlogger.log(tid, reply[1], "debug")
    wlogger.log(tid, reply[2], "debug")
    wlogger.log(tid, "Cache clustering setup is complete.", "success")
    init_client.close()
    return True


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
