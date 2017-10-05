import json
import os.path

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, celery, wlogger
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import DBManager

from ldap3.core.exceptions import LDAPSocketOpenError


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
        self.chdir = None
        if self.server.gluu_server:
            version = AppConfiguration.query.first().gluu_version
            self.chdir = "/opt/gluu-server-{0}".format(version)


    def install(self):
        """install() detects the os of the server and calls the appropriate
        function to install redis on that server.

        Returns:
            boolean status of the installs
        """
        try:
            self.rc.startup()
        except Exception as e:
            wlogger.log(self.tid, "Could not connect to {0}".format(e),
                        "error", server_id=self.server.id)
            return False


        cin, cout, cerr = self.rc.run("ls /etc/*release")
        files = cout.split()
        cin, cout, cerr = self.rc.run("cat "+files[0])

        if "Ubuntu" in cout:
            return self.install_in_ubuntu()
        if "CentOS" in cout:
            return self.install_in_centos()
        else:
            wlogger.log(self.tid, "Server OS is not supported. {0}".format(
                cout), "error", server_id=self.server.id)
            return False

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

    def _chcmd(self, cmd):
        if self.chdir:
            return 'chroot {0} /bin/bash -c "{1}"'.format(self.chdir, cmd)
        else:
            return cmd

    def run_command(self, cmd):
        wlogger.log(self.tid, self._chcmd(cmd), "debug",
                    server_id=self.server.id)
        return self.rc.run(self._chcmd(cmd))



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
        cin, cout, cerr = self.rc.run(
            self._chcmd("apt-get install redis-server -y"))

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
        # TODO find the successful install message and return True
        if cerr:
            return False
        return True


class StunnelInstaller(BaseInstaller):
    def install_in_ubuntu(self):
        self.run_command("apt-get update")
        cin, cout, cerr = self.run_command("apt-get install stunnel4 -y")
        wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        if cerr:
            wlogger.log(self.tid, cerr, "cerror", server_id=self.server.id)

        # Verifying installation by trying to reinstall
        cin, cout, cerr = self.rc.run(
            self._chcmd("apt-get install stunnel4 -y"))
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
        # TODO find the successful install message and return True
        if cerr:
            return False
        return True


def setup_cluster(tid):
    # TODO implement redis-server deployment logic
    pass



def setup_sharding(tid):
    servers = Server.query.all()
    installed = []
    # Store the redis server info in the LDAP
    for server in servers:
        server_string = ''
        count = len(installed)
        if server in installed:
            server_string = 'localhost:6379,'
            count -= 1

        server_string += ",".join(
            ["localhost:700{0}".format(i) for i in xrange(count)])

        dbm = DBManager(server.hostname, 1636,  server.ldap_password, ssl=True,
                        ip=server.ip,)
        entry = dbm.get_appliance_attributes('oxCacheConfiguration')
        cache_conf = json.loads(entry.oxCacheConfiguration.value)
        cache_conf['cacheProviderType'] = 'REDIS'
        redis_conf = cache_conf['cacheProviderType']['redisConfiguration']
        redis_conf['redisProviderType'] = 'SHARDING'
        redis_conf['servers'] = server_string
        cache_conf['cacheProviderType']['redisConfiguration'] = redis_conf

        dbm.set_applicance_attribute('oxCacheConfiguration',
                                     [json.dumps(cache_conf)])

        # TODO generate stunnel configuration and upload it to the server


@celery.task(bind=True)
def install_redis_stunnel(self, servers):
    tid = self.request.id
    installed = 0
    for server_id in servers:
        server = Server.query.get(server_id)
        wlogger.log(tid, "Installing Redis in server {0}".format(
            server.hostname), "info", server_id=server_id)
        ri = RedisInstaller(server, tid)
        redis_installed = ri.install()
        if redis_installed:
            server.redis = True
            wlogger.log(tid, "Redis install successful", "success",
                        server_id=server_id)
        else:
            server.redis = False
            wlogger.log(tid, "Redis install failed", "fail",
                        server_id=server_id)

        wlogger.log(tid, "Installing Stunnel", "info", server_id=server_id)
        si = StunnelInstaller(server, tid)
        stunnel_installed = si.install()
        if stunnel_installed:
            server.stunnel = True
            wlogger.log(tid, "Stunnel install successful", "success",
                        server_id=server_id)
        else:
            server.stunnel = False
            wlogger.log(tid, "Stunnel install failed", "fail",
                        server_id=server_id)
        # Save the redis and stunnel install situation to the db
        db.session.commit()

        if redis_installed and stunnel_installed:
            installed += 1
    return installed


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
