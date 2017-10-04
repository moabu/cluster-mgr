import json

from clustermgr.models import Server
from clustermgr.extensions import db, celery, wlogger
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import DBManager

from ldap3.core.exceptions import LDAPSocketOpenError


class RedisInstaller(object):
    """RedisInstaller installs redis-server in the provided server.

    Args:
        client (class:`clustermgr.core.remote.RemoteClient`): a remote client
            object to connect to the remote server
        server (class:`clustermgr.models.Server`): the server object denoting
            the server where server should be installed
        tid (string): the task id of the celery task to add logs
    """
    def __init__(self, client, server, tid):
        self.rc = client  # rc - Remote Client
        self.server = server
        self.tid = tid

    def install(self):
        """install() detects the os of the server and calls the appropriate
        function to install redis on that server.
        """
        if self.rc.exists('/usr/bin/redis-server'):
            wlogger.log(self.tid, "Redis server is already installed.")
            return True

        wlogger.log(self.tid, "Resolving the OS of the server...")
        cin, cout, cerr = self.rc.run("ls /etc/*release")
        files = cout.split()
        cin, cout, cerr = self.rc.run("cat "+files[0])
        if "Ubuntu" in cout:
            return self.install_in_ubuntu()
        if "CentOS" in cout:
            return self.install_in_centos()
        else:
            wlogger.log(self.tid, "Server OS is not supported. {0}".format(
                cout
            ), "error")
            return False

    def install_in_ubuntu(self):
        """installs redis-server in a Ubuntu machine.

        Returns:
            a boolean flag indicating success or failure of the operation
        """
        wlogger.log(self.tid, "Installing redis-server in Ubuntu")
        commands = [
            "apt-get update && sudo apt-get upgrade",
            "apt-get install software-properties-common -y",
            "add-apt-repository ppa:chris-lea/redis-server -y",
            "apt-get update",
            "apt-get install redis-server -y",
        ]
        return self.run_commands(commands)

    def install_in_centos(self):
        """installs redis-server in a CentOS machine.

        Returns:
            a boolean flag indicating success or failure of the operation
        """
        commands = [
            "yum update -y",
            "yum install epel-release -y",
            "yum update -y",
            "yum install redis -y",
        ]

        # To automatically start redis on boot
        # systemctl enable redis

        return self.run_commands(commands)

    def run_commands(self, commands):
        """runs a list of commands on the remote server via the remote client

        Args:
            commands (list): list of commands to run

        Returns:
            false if any of the commands fail, true if all the commands succeed
        """
        for cmd in commands:
            wlogger.log(self.tid, cmd, "debug")
            cin, cout, cerr = self.rc.run(cmd)
            if cout:
                wlogger.log(self.tid, cout, "debug")
            if cerr:
                wlogger.log(self.tid, cerr, "error")
                return False
        return True


class StunnelInstaller(object):
    def __init__(self, server, redis_servers, tid):
        pass


@celery.task(bind=True)
def configure_redis(self, server_id, method, redis_servers, put_expiration=60):
    """configure_redis is a celery task that installs redis in the specified
    gluu server and configures it according to the parameters specified in the
    arguments.

    Args:
        server_id (int): the id of the server where redis is to be installed
        method (string): the configuration method for redis
        redis_servers (string): the string containing the list of servers that
            oxAuth can use in a comma sperated host:port format. eg.,
            server1:7000,server2:8081
        put_expiration (int, optional): the timeout after which put values can
            be cleared defaults to 60

    Returns:
        boolean value indicating whether configuration has been successful
    """
    # NOTE This task will be applicable for only for STANDALONE
    # For SHARDING and CLUSTER, the task has to operate on multiple servers
    # instead of a number of servers - that's a TODO
    tid = self.request.id
    wlogger.log(tid, "Configuring Redis as Cache", "info")
    server = Server.query.get(server_id)
    # Sanitize the method variable
    accepted_methods = ['STANDALONE', 'SHARDING', 'CLUSTER']
    if method not in accepted_methods:
        wlogger.log(tid, "Redis cannot be configured in the method {0}. "
                    "Choose anyone from {2}.".format(method, accepted_methods),
                    "error")
        return False

    c = RemoteClient(server.hostname, ip=server.ip)
    try:
        c.startup()
    except Exception as e:
        wlogger.log(tid, "Could not connect to the server. {0}".format(e),
                    "error")
        return

    # 1. Check if redis is installed and Install the Redis Server
    ri = RedisInstaller(c, server, tid)
    install_ok = ri.install()
    if not install_ok:
        wlogger.log(tid, "Failed to install redis server. Aborting process.",
                    "error")
        return False

    # 2. Get the oxAuth config from LDAP and change the config values
    dbm = DBManager(server.hostname, 1636,  server.ldap_password, ssl=True,
                    ip=server.ip,)
    entry = dbm.get_appliance_attributes('oxCacheConfiguration')
    cache_conf = json.loads(entry.oxCacheConfiguration.value)
    cache_conf['cacheProviderType'] = 'REDIS'
    redis_conf = cache_conf['cacheProviderType']['redisConfiguration']
    redis_conf['redisProviderType'] = method
    redis_conf['servers'] = redis_servers
    redis_conf['defaultPutExpiration'] = put_expiration
    cache_conf['cacheProviderType']['redisConfiguration'] = redis_conf

    dbm.set_applicance_attribute('oxCacheConfiguration',
                                 [json.dumps(cache_conf)])

    # 3. update the stunnel configuration and restart stunnel
    stunnel_required = False
    servers = redis_servers.split(",")
    for serve in servers:
        if 'localhost' not in serve:
            stunnel_required = True
            break

    if not stunnel_required:
        wlogger.log(tid, "Redis server has been successfully setup as a cache"
                    " for {0}".format(server.hostname), "success")
        return True

    si = StunnelInstaller(server, redis_servers, tid)
    stunnel_installed = si.install()
    if not stunnel_installed:
        wlogger.log(tid, "Stunnel could not be installed in the server",
                    "error")
        return False


@celery.task(bind=True)
def get_cache_methods(self):
    tid = self.request.id
    servers = Server.query.all()
    methods = []
    for server in servers:
        try:
            dbm = DBManager(server.hostname, 1636,  server.ldap_password,
                            ssl=True, ip=server.ip)
        except LDAPSocketOpenError as e:
            wlogger.log(tid, "Couldn't connect to server {0}. Error: "
                        "{1}".format(server.hostname, e), "error")
            continue

        entry = dbm.get_appliance_attributes('oxCacheConfiguration')
        cache_conf = json.loads(entry.oxCacheConfiguration.value)
        server.cache_method = cache_conf['cacheProviderType']
        db.session.commit()
        methods.append({"id": server.id, "method": server.cache_method})
    wlogger.log(tid, "Cache Methods of servers have been updated.", "success")
    return methods
