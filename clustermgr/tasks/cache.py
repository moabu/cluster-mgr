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
        get_redis_config, make_proxy_stunnel_conf, make_twem_proxy_conf, get_cache_servers

from ldap3.core.exceptions import LDAPSocketOpenError
from flask import current_app as app


class BaseInstaller(object):
    """Base class for component installers.

    Args:
        server (class:`clustermgr.models.Server`): the server object denoting
            the server where server should be installed
        tid (string): the task id of the celery task to add logs
    """

    def __init__(self, server, tid, rc):
        self.server = server
        self.tid = tid
        self.rc = rc
        self.os_type = None
        self.determine_os_type()

    def determine_os_type(self):
        cin, cout, cerr = self.rc.run("ls /etc/*release")
        files = cout.split()
        cin, cout, cerr = self.rc.run("cat " + files[0])

        if "Ubuntu" in cout:
            self.os_type = 'deb'
        elif "CentOS" in cout or 'Red Hat' in cout:
            self.os_type = 'rpm'


    def install(self):
        """install() detects the os of the server and calls the appropriate
        function to install redis on that server.

        Returns:
            boolean status of the install process
        """

        status = False
        if self.os_type == 'deb':
            status = self.install_in_ubuntu()
        elif  self.os_type == 'rpm':
            status = self.install_in_centos()
        else:
            wlogger.log(self.tid, "Server OS is not supported. {0}".format(
                cout), "error", server_id=self.server.id)
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

    def check_installed(self):
        if self.rc.exists('/usr/bin/redis-server'):
            wlogger.log(self.tid, "Redis Server was already installed.", "debug", server_id=self.server.id)
            return True

    def install_in_ubuntu(self):
        
        if self.check_installed():
            return True
        
        self.run_command("apt-get update")

        cmd_list = [
            'DEBIAN_FRONTEND=noninteractive apt-get install -y redis-server',
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
        
        if self.check_installed():
            return True
                
        cmd_list = ('yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm',
                    'yum clean all',
                    'yum install -y redis'
                    )
    
        err = ''
        
        for install_cmd in cmd_list:

            cin, cout, cerr = self.run_command(install_cmd)
            wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
            
            if '/var/cache/yum' in cerr:
                wlogger.log(self.tid, cerr, "debug", server_id=self.server.id)
            else:
                wlogger.log(self.tid, cerr, "error", server_id=self.server.id)

        return True


    def run_sysctl(self, command):
        if self.os_type == 'deb':
            cmd = 'systemctl {} redis-server'.format(command)
        elif self.os_type == 'rpm':
            cmd = 'systemctl {} redis'.format(command)
        self.run_command(cmd)




class StunnelInstaller(BaseInstaller):
    
    
    def check_installed(self):
        
        si = self.rc.exists('/usr/bin/stunnel') or self.rc.exists('/bin/stunnel')

        if si:
            wlogger.log(self.tid, "stunnel was already installed.", "debug", server_id=self.server.id)

        return si

    
    def install_in_ubuntu(self):
        self.run_command("apt-get update")
        cin, cout, cerr = self.run_command("DEBIAN_FRONTEND=noninteractive apt-get install stunnel4 -y")
        wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        if cerr:
            wlogger.log(self.tid, cerr, "error", server_id=self.server.id)

        # Verifying installation by trying to reinstall
        cin, cout, cerr = self.rc.run("DEBIAN_FRONTEND=noninteractive apt-get install stunnel4 -y")
        
        
        if "stunnel4 is already the newest version" in cout:
            return True
        else:
            return False

    def install_in_centos(self):
        #self.run_command("yum update -y")
        cin, cout, cerr = self.run_command("yum install -y stunnel")
        wlogger.log(self.tid, cout, "debug", server_id=self.server.id)
        
        if '/var/cache/yum' in cerr:
            wlogger.log(self.tid, cerr, "debug", server_id=self.server.id)
        else:
            wlogger.log(self.tid, cerr, "error", server_id=self.server.id)
            
        # verifying installation
        cin, cout, cerr = self.rc.run("yum install -y stunnel")
        if "already installed" in cout:
            return True
        else:
            return False

    def upload_service_file(self):

        local = os.path.join(app.root_path, 'templates', 'stunnel',
                             'stunnel.service')
        remote = '/lib/systemd/system/stunnel.service'
        wlogger.log(self.tid, "Uploading systemd file", "info",
                    server_id=self.server.id)
        self.rc.upload(local, remote)
        self.rc.run("mkdir -p /var/log/stunnel4")

    def run_sysctl(self, command):
        if self.os_type == 'deb':
            cmd = 'systemctl {} stunnel4'.format(command)
        elif self.os_type == 'rpm':
            cmd = 'systemctl {} stunnel'.format(command)
        self.run_command(cmd)



@celery.task(bind=True)
def install_cache_cluster(self):
    
    tid = self.request.id
    
    app_conf = AppConfiguration.query.first()
    
    cache_servers = get_cache_servers()
    servers = Server.query.all()
    
    primary_cache = None
    
    
    for server in cache_servers:

        rc = __get_remote_client(server, tid)
        if not rc:
            wlogger.log(tid, "SSH connection to server failed", "error", server_id=server.id)
            return False
        
        ri = RedisInstaller(server, tid, rc)
        
        if app_conf.offline:
            if not ri.check_installed():
                wlogger.log(
                    tid, 
                    'Redis Server was not installed. Please install Redis '
                    ' Server and retry.', 
                    'error',
                    server_id=server.id
                    )
                return False

        redis_installed = ri.install()
    
        if redis_installed:
            wlogger.log(tid, "Redis install successful", "success",
                        server_id=server.id)
        else:
            wlogger.log(tid, "Redis install failed", "fail",
                        server_id=server.id)
            return False

        ri.run_sysctl('enable')
        ri.run_sysctl('restart')

        si = StunnelInstaller(server, tid, rc)

        if app_conf.offline:
            if not si.check_installed():
                wlogger.log(
                    tid, 
                    'Stunnel was not installed. Please install stunnel '
                    'and retry.', 
                    'error',
                    server_id=server.id
                    )
                return False

         
        if si.check_installed():
            server.stunnel = True
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
                            
                return False
        
        if si.os_type == 'rpm':
            si.upload_service_file()
        
        if si.os_type == 'deb':
            wlogger.log(tid, "Enabling stunnel", "debug", server_id=server.id)
            si.run_command("sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/stunnel4")
        
        if not primary_cache:
            primary_cache = server.ip
            if not rc.exists('/etc/stunnel/redis-server.crt'):
                wlogger.log(tid, "Creating SSL certificate for stunnel", "info",
                                server_id=server.id)
                si.run_command(
                        'openssl req -x509 -nodes -days 3650 -newkey rsa:2048 '
                        '-batch -keyout /etc/stunnel/redis-server.key '
                        '-out /etc/stunnel/redis-server.crt'
                        )
                si.run_command('chmod 600 /etc/stunnel/redis-server.key')
            
            
            wlogger.log(tid, "Retreiving server certificate", "info",
                                server_id=server.id)
            stunnel_cert = rc.get_file('/etc/stunnel/redis-server.crt')

            if not stunnel_cert[0]:
                wlogger.log(tid, "Can't retreive server certificate", "fail",
                            server_id=server.id)

            stunnel_cert = stunnel_cert[1].read()

            stunnel_redis_conf = (
                                'pid = /run/stunnel-redis.pid\n'
                                '[redis-server]\n'
                                'cert = /etc/stunnel/redis-server.crt\n'
                                'key = /etc/stunnel/redis-server.key\n'
                                'accept = {0}:16379\n'
                                'connect = 127.0.0.1:6379\n'
                                ).format(server.ip)
            
            wlogger.log(tid, "Writing redis stunnel configurations", "info",
                                server_id=server.id)
            
            rc.put_file('/etc/stunnel/stunnel.conf', stunnel_redis_conf)
            
            si.run_sysctl('enable')
            si.run_sysctl('restart')
            
        rc.close()
        
        wlogger.log(tid, "2", "set_step")
    
    for server in servers:
                
        rc = __get_remote_client(server, tid)
        if not rc:
            wlogger.log(tid, "SSH connection to server failed", "error", server_id=server.id)
            return False

        si = StunnelInstaller(server, tid, rc)

        wlogger.log(tid, "Installing Stunnel", "debug", server_id=server.id)
         
        if si.rc.exists('/usr/bin/stunnel') or si.rc.exists('/bin/stunnel'):
            wlogger.log(tid, "Stunnel was allready installed", "info", 
                        server_id=server.id)
            server.stunnel = True
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
                            
                return False

        if si.os_type == 'rpm':
            si.upload_service_file()
        
        
        if si.os_type == 'deb':
            wlogger.log(tid, "Enabling stunnel", "debug", server_id=server.id)
            si.run_command("sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/stunnel4")
        
        stunnel_redis_conf = ( 
                            'pid = /run/stunnel-redis.pid\n'
                            '[redis-client]\n'
                            'client = yes\n'
                            'accept = 127.0.0.1:16379\n'
                            'connect = {0}:16379\n'
                            'CAfile = /etc/stunnel/redis-server.crt\n'
                            'verify = 4\n'
                            ).format(primary_cache)

        wlogger.log(tid, "Writing redis stunnel configurations", "info",
                                server_id=server.id)
        rc.put_file('/etc/stunnel/stunnel.conf', stunnel_redis_conf)

        wlogger.log(tid, "Uploading server certificate", "info",
                                server_id=server.id)

        rc.put_file('/etc/stunnel/redis-server.crt', stunnel_cert)

        si.run_sysctl('enable')
        si.run_sysctl('restart')

        if server.primary_server:
            __update_LDAP_cache_method(tid, server, 'localhost:16379')
        

        wlogger.log(tid, "Restarting Gluu Server", "info",
                                server_id=server.id)


        if server.os in ('RHEL 7', 'CentOS 7', 'Ubuntu 18'):
            si.run_command('/sbin/gluu-serverd-{} restart'.format(app_conf.gluu_version))
        else:
            si.run_command('systemctl restart gluu-server-{}'.format(app_conf.gluu_version))

    wlogger.log(tid, "3", "set_step")



def __update_LDAP_cache_method(tid, server, server_string, method='STANDALONE'):
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
