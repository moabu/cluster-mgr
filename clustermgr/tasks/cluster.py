# -*- coding: utf-8 -*-

import os
import re
import time
import subprocess
import traceback
import uuid
import select
import requests

from flask import current_app as app

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import wlogger, db, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import LdapOLC, getLdapConn
from clustermgr.core.utils import modify_etc_hosts, make_nginx_proxy_conf    
from clustermgr.core.clustermgr_installer import Installer
from clustermgr.config import Config


def modifyOxLdapProperties(server, installer, task_id, pDict):
    """Modifes /etc/gluu/conf/ox-ldap.properties file for gluu server to look
    all ldap server.

    Args:
        c (:object: `clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        tid (string): id of the task running the command
        pDict (dictionary): keys are hostname and values are comma delimated
            providers
        chroot (string): root of container
    """

    # get ox-ldap.properties file from server
    remote_file = os.path.join(installer.container, 'etc/gluu/conf/gluu-ldap.properties')
    result = installer.get_file(remote_file)

    state = True

    # iterate ox-ldap.properties file and modify "servers" entry
    if result:
        file_content = ''
        for line in result.split('\n'):
            if line.startswith('servers:'):
                line = 'servers: {0}'.format( pDict[server.hostname] )
            file_content += line+'\n'

        result = installer.put_file(remote_file,file_content)

        if result:
            wlogger.log(task_id,
                'ox-ldap.properties file on {0} modified to include '
                'all replicating servers'.format(server.hostname),
                'success')
        else:
            state = False
    else:
        state = False

    if not state:
        wlogger.log(task_id,
                'ox-ldap.properties file on {0} was not modified to '
                'include all replicating servers.'.format(server.hostname),
                'warning')

    # Modify Shib ldap.properties to include all ldap properties
    remote_file = os.path.join(installer.container, 'opt/shibboleth-idp/conf/ldap.properties')
    
    if installer.conn.exists(remote_file):
    
        shib_ldap = installer.get_file(remote_file)

        temp = None

        if shib_ldap:
             
            ldap_server_list = [ 'ldaps://'+ldap_server for ldap_server in pDict[server.hostname].split(',') ]
            server_list_string = ' '.join(ldap_server_list)

            # iterate ldap.properties file and modify idp.authn.LDAP.ldapURL entry

            fc = ''
            for l in shib_ldap:
                if l.startswith('idp.authn.LDAP.ldapURL'):
                    l = 'idp.authn.LDAP.ldapURL                          = {}\n'.format( server_list_string )
                fc += l

            r = installer.put_file(remote_file,fc)

            if r:
                wlogger.log(task_id,
                    '/opt/shibboleth-idp/conf/ldap.properties file on {0} modified to include '
                    'all replicating servers'.format(server.hostname),
                    'success')
            else:

                wlogger.log(task_id,
                    '/opt/shibboleth-idp/conf/ldap.propertiess file on {0} was not modified to '
                    'include all replicating servers: {1}'.format(server.hostname, r[1]),
                    'warning')



def get_csync2_config(exclude=None):

    sync_directories = []

    replication_user_file = os.path.join(
                                app.config['DATA_DIR'], 
                                'replication_defaults.txt'
                            )

    if not os.path.exists(replication_user_file):
        replication_user_file = os.path.join(app.root_path, 'templates',
                                    'file_system_replication',
                                    'replication_defaults.txt')

    for l in open(replication_user_file).readlines():
        sync_directories.append(l.strip())

    exclude_files = [
        '/etc/gluu/conf/ox-ldap.properties',
        '/etc/gluu/conf/oxTrustLogRotationConfiguration.xml',
        '/etc/gluu/conf/salt',
        ]

    csync2_config = ['group gluucluster','{']

    all_servers = Server.get_all()

    cysnc_hosts = []
    for server in all_servers:
        if not server.hostname == exclude:
            cysnc_hosts.append(('csync{}.gluu'.format(server.id), server.ip))

    for srv in cysnc_hosts:
        csync2_config.append('  host {};'.format(srv[0]))

    csync2_config.append('')
    csync2_config.append('  key /etc/csync2.key;')
    csync2_config.append('')

    for d in sync_directories:
        csync2_config.append('  include {};'.format(d))

    csync2_config.append('')
    csync2_config.append('  exclude *~ .*;')
    csync2_config.append('')


    for f in exclude_files:
        csync2_config.append('  exclude {};'.format(f))


    csync2_config.append('\n'
          '  action\n'
          '  {\n'
          '    logfile "/var/log/csync2_action.log";\n'
          '    do-local;\n'
          '  }\n'
          )

    csync2_config.append('\n'
          '  action\n'
          '  {\n'
          '    pattern /opt/gluu/jetty/identity/conf/shibboleth3/idp/*;\n'
          '    exec "/sbin/service idp restart";\n'
          '    exec "/sbin/service identity restart";\n'
          '    logfile "/var/log/csync2_action.log";\n'
          '    do-local;\n'
          '  }\n')


    csync2_config.append('  backup-directory /var/backups/csync2;')
    csync2_config.append('  backup-generations 3;')
    csync2_config.append('\n  auto younger;\n')
    csync2_config.append('}')
    csync2_config = '\n'.join(csync2_config)

    return csync2_config


@celery.task(bind=True)
def setup_filesystem_replication(self):
    """Deploys File System replicaton
    """
    task_id = self.request.id

    try:
        setup_filesystem_replication_do(task_id)
    except:
        raise Exception(traceback.format_exc())


def setup_filesystem_replication_do(task_id):
    """Deploys File System replicaton
    """

    servers = Server.get_all()
    app_conf = AppConfiguration.query.first()

    cysnc_hosts = []
    for server in servers:
        cysnc_hosts.append(('csync{}.gluu'.format(server.id), server.ip))

    server_counter = 0

    installers = {}

    primary_installer = None

    for server in servers:
        
        installer =  Installer(
                                server,
                                app_conf.gluu_version,
                                logger_task_id=task_id,
                                server_os=server.os,
                                ssh_port=server.ssh_port
                            )
        
        modify_hosts(installer, cysnc_hosts)

        if not installer.conn.exists(os.path.join(installer.container, 'usr/sbin/csync2')): 

            if app_conf.offline:
                wlogger.log(
                        task_id, 
                        'csync2 was not installed. Please install csync2 and retry.', 
                        'error',
                        server_id=server.id
                    )
                return False


            if installer.clone_type == 'deb':
                for cmd in (
                            'localedef -i en_US -f UTF-8 en_US.UTF-8',
                            'locale-gen en_US.UTF-8',
                            'DEBIAN_FRONTEND=noninteractive apt-get update',
                            ):
                    installer.run(cmd)
                installer.install('apt-utils')
                installer.install('csync2')

            elif installer.clone_type == 'rpm':
                installer.epel_release(True)
                
                
                if installer.server_os == 'RHEL 7':
                    centos_base_repo_file = os.path.join(
                                            app.root_path, 'templates',
                                            'centos-repo',
                                            'CentOS-Base.repo')

                    installer.upload_file(centos_base_repo_file, 
                            '/opt/gluu-server/etc/yum.repos.d/CentOS-Base.repo')
                if installer.os_version == '8':
                    csync_rpm = 'http://162.243.99.240/icrby8xcvbcv/csync2/csync2-2.0-3.gluu.el8.x86_64.rpm'
                else:
                    csync_rpm = 'http://162.243.99.240/icrby8xcvbcv/csync2/csync2-2.0-3.gluu.{}.x86_64.rpm'.format(server.os.replace(' ', '').lower())

                installer.epel_release(True)

                installer.run('curl http://mirror.centos.org/centos/7/os/x86_64/RPM-GPG-KEY-CentOS-7 >/etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7', inside=True, error_exception= '__ALL__')

                

                installer.install(csync_rpm, inside=True, error_exception= '__ALL__')

        else:
            wlogger.log(task_id, "csync2 was allready installed on this serevr.", server_id=server.id)

        installer.run('rm -f /var/lib/csync2/*.db3')
        installer.run('rm -f /etc/csync2*')

        if server.primary_server:

            primary_installer = installer

            key_command= [
                'csync2 -k /etc/csync2.key',
                'openssl genrsa -out /etc/csync2_ssl_key.pem 1024',
                'openssl req -batch -new -key /etc/csync2_ssl_key.pem -out '
                '/etc/csync2_ssl_cert.csr',
                'openssl x509 -req -days 3600 -in /etc/csync2_ssl_cert.csr '
                '-signkey /etc/csync2_ssl_key.pem -out /etc/csync2_ssl_cert.pem',
                ]

            for cmd in key_command:
                installer.run(cmd, error_exception='__ALL__')

            csync2_config = get_csync2_config()
            remote_file = os.path.join(installer.container, 'etc', 'csync2.cfg')
            installer.put_file(remote_file,  csync2_config)


        else:
            wlogger.log(task_id, "Downloading csync2.cfg, csync2.key, "
                        "csync2_ssl_cert.csr, csync2_ssl_cert.pem, and"
                        "csync2_ssl_key.pem from primary server and uploading",
                        'debug', server_id=server.id)

            down_list = ['csync2.cfg', 'csync2.key', 'csync2_ssl_cert.csr',
                    'csync2_ssl_cert.pem', 'csync2_ssl_key.pem']

            for file_name in down_list:
                remote = os.path.join(primary_installer.container, 'etc', file_name)
                local = os.path.join('/tmp',file_name)
                primary_installer.server_id = server.id
                primary_installer.download_file(remote, local)
                installer.upload_file(local, remote)


        csync2_path = '/usr/sbin/csync2'

        if installer.clone_type == 'deb':

            wlogger.log(task_id, "Enabling csync2 via inetd", server_id=server.id)

            new_inet_conf_file_content = []
            inet_conf_file = os.path.join(installer.container, 'etc','inetd.conf')
            inet_conf_file_content = installer.get_file(inet_conf_file)
            
            print "File content {}".format(inet_conf_file_content)
            
            csync_line = 'csync2\tstream\ttcp\tnowait\troot\t/usr/sbin/csync2\tcsync2 -i -l -N csync{}.gluu\n'.format(server.id) 
            csync_line_exists = False
            for line in inet_conf_file_content.splitlines():
                if line.startswith('csync2'):
                    line = csync_line
                    csync_line_exists = True
                else:
                    new_inet_conf_file_content.append(line)
            
            new_inet_conf_file_content.append(csync_line)
            new_inet_conf_file_content = '\n'.join(new_inet_conf_file_content)

            installer.put_file(inet_conf_file, new_inet_conf_file_content)

            installer.restart_service('openbsd-inetd')

        elif installer.clone_type == 'rpm':
            inetd_conf = (
                '# default: off\n'
                '# description: csync2\n'
                'service csync2\n'
                '{\n'
                'flags           = REUSE\n'
                'socket_type     = stream\n'
                'wait            = no\n'
                'user            = root\n'
                'group           = root\n'
                'server          = /usr/sbin/csync2\n'
                'server_args     = -i -l -N %(HOSTNAME)s\n'
                'port            = 30865\n'
                'type            = UNLISTED\n'
                'disable         = no\n'
                '}\n')

            inet_conf_file = os.path.join(installer.container, 'etc', 'xinetd.d', 'csync2')
            inetd_conf = inetd_conf % ({'HOSTNAME': 'csync{}.gluu'.format(server.id)})
            installer.put_file(inet_conf_file, inetd_conf)

        #run time sync in every minute
        cron_file = os.path.join(installer.container, 'etc', 'cron.d', 'csync2')
        installer.put_file(cron_file,
            '{}-59/2 * * * *    root    {} -N csync{}.gluu -xvv 2>/var/log/csync2.log\n'.format(
            server_counter, csync2_path, server.id))

        server_counter += 1

        wlogger.log(task_id, 'Crontab entry was created to sync files in every minute',
                         'debug', server_id=server.id)

        if installer.clone_type == 'rpm':
            installer.restart_service('xinetd')
            installer.restart_service('crond')
        else:
            installer.restart_service('cron')
            installer.restart_service('openbsd-inetd')

    return True

def remove_filesystem_replication_do(server, app_config, task_id):

        installer = Installer(server, app_config.gluu_version, ssh_port=server.ssh_port, logger_task_id=task_id)

        if not installer.conn:
            return False
        
        csync_enabled = False
        
        
        if installer.conn.exists('/opt/gluu-server/etc/cron.d/csync2'):
            installer.run('rm /etc/cron.d/csync2')
            csync_enabled = True
        
        if installer.conn.exists('/opt/gluu-server/var/lib/csync2/'):
            installer.run('rm -f /var/lib/csync2/*.*')
            
        if installer.conn.exists('/opt/gluu-server/etc/csync2.cfg'):
            installer.run('rm -f /etc/csync2.cfg')

        if csync_enabled:
            if 'CentOS' in server.os or 'RHEL' in server.os :
                if installer.conn.exists('/opt/gluu-server/etc/xinetd.d/csync2'):
                    installer.run('rm /etc/xinetd.d/csync2')
                services = ['xinetd', 'crond']
                
            else:
                installer.run("sed 's/^csync/#&/' -i /etc/inetd.conf")
                services = ['openbsd-inetd', 'cron']
                
            for s in services:
                installer.restart_service(s)

        return True


@celery.task(bind=True)
def remove_filesystem_replication(self):
    task_id = self.request.id
    
    app_config = AppConfiguration.query.first()
    servers = Server.get_all()

    for server in servers:
        r = remove_filesystem_replication_do(server, app_config, task_id)
        if not r:
            return r


def modify_hosts(installer, hosts, inside=True, server_host=None):
    wlogger.log(installer.logger_task_id, "Modifying /etc/hosts", server_id=installer.server_id)
    chroot = installer.container if inside else '/'
    hosts_file = os.path.join(chroot,'etc/hosts')
    
    old_hosts = installer.get_file(hosts_file)
    
    print "OLD hosts", old_hosts
    
    if old_hosts:
        new_hosts = modify_etc_hosts(hosts, old_hosts)
        installer.put_file(hosts_file, new_hosts)
        wlogger.log(installer.logger_task_id, "{} was modified".format(hosts_file), 'success', server_id=installer.server_id)



def do_disable_replication(task_id, server, primary_server, app_conf):

    installer = Installer(
                    server, 
                    app_conf.gluu_version,
                    ssh_port=server.ssh_port,
                    logger_task_id=task_id, 
                    server_os=server.os
                    )

    if not installer.conn:
        return False
    
    wlogger.log(task_id, 
        "Disabling replication for {0}".format(
        server.hostname)
        )

    cmd = ( 'OPENDJ_JAVA_HOME=/opt/jre '
            '/opt/opendj/bin/dsreplication disable --disableAll --port 4444 '
            '--hostname {} --adminUID admin --adminPassword $\'{}\' '
            '--trustAll --no-prompt').format(
                            server.hostname,
                            app_conf.replication_pw)

    cmd_fn = os.path.join(installer.container, 'root/.cmd')
    installer.put_file(cmd_fn, cmd)
    installer.run('bash /root/.cmd', error_exception='no base DNs replicated')
    installer.run('rm -f /root/.cmd')

    server.mmr = False
    db.session.commit()

    configure_OxIDPAuthentication(task_id, exclude=server.id, installers={installer.hostname:installer})

    wlogger.log(task_id, "Checking replication status", 'debug')

    cmd = ( 'OPENDJ_JAVA_HOME=/opt/jre '
            '/opt/opendj/bin/dsreplication status -n -X -h {} '
            '-p 4444 -I admin -w $\'{}\'').format(
                    primary_server.hostname,
                    app_conf.replication_pw)

    cmd_fn = os.path.join(installer.container, 'root/.cmd')
    installer.put_file(cmd_fn, cmd)
    installer.run('bash /root/.cmd', error_exception='no base DNs replicated')
    installer.run('rm -f /root/.cmd')

    return True

@celery.task(bind=True)
def opendj_disable_replication_task(self, server_id):
    server = Server.query.get(server_id)
    primary_server = Server.query.filter_by(primary_server=True).first()
    app_conf = AppConfiguration.query.first()
    task_id = self.request.id
    result = do_disable_replication(task_id, server, primary_server, app_conf)
    return result


@celery.task(bind=True)
def remove_server_from_cluster(self, server_id, remove_server=False, 
                                                disable_replication=True):

    app_conf = AppConfiguration.query.first()
    primary_server = Server.query.filter_by(primary_server=True).first()
    server = Server.query.get(server_id)
    task_id = self.request.id

    removed_server_hostname = server.hostname

    remove_filesystem_replication_do(server, app_conf, task_id)

    nginx_installer = get_nginx_installer(app_conf, task_id)

    if not app_conf.external_load_balancer:
        # Update nginx
        nginx_config = make_nginx_proxy_conf(exception=server_id)
        if not nginx_installer.conn:
            wlogger.log(
                task_id, 
                'ssh connection to nginx failed', 
                'error'
                )
            return
                
        nginx_installer.put_file('/etc/nginx/nginx.conf', nginx_config)
        nginx_installer.restart_service('nginx', inside=False)

    if disable_replication:
        result = do_disable_replication(task_id, server, primary_server, app_conf)
        if not result:
            return False

    if remove_server:
        db.session.delete(server)

    for server in Server.get_all():
        if server.gluu_server:
        
            installer = Installer(
                        server,
                        app_conf.gluu_version,
                        ssh_port=server.ssh_port,
                        logger_task_id=task_id,
                        server_os=server.os
                    )

            csync2_config = get_csync2_config(exclude=removed_server_hostname)
            remote_file = os.path.join(installer.container, 'etc', 'csync2.cfg')
            installer.put_file(remote_file,  csync2_config)

            installer.restart_gluu()

    db.session.commit()
    return True


def configure_OxIDPAuthentication(task_id, exclude=None, installers={}):
    
    primary_server = Server.query.filter_by(primary_server=True).first()
    
    app_conf = AppConfiguration.query.first()

    gluu_installed_servers = Server.query.filter_by(gluu_server=True).all()

    pDict = {}

    for server in gluu_installed_servers:
        if server.mmr:
            laddr = server.ip if app_conf.use_ip else server.hostname
            ox_auth = [ laddr+':1636' ]
            for prsrv in gluu_installed_servers:
                if prsrv.mmr:
                    if not prsrv == server:
                        laddr = prsrv.ip if app_conf.use_ip else prsrv.hostname
                        ox_auth.append(laddr+':1636')
            pDict[server.hostname]= ','.join(ox_auth)

    for server in gluu_installed_servers:
        if server.mmr:
            installer = installers.get(server.hostname)
            if not installer:
                installer = Installer(
                    server, 
                    app_conf.gluu_version,
                    ssh_port=server.ssh_port,
                    logger_task_id=task_id, 
                    server_os=server.os
                    )

            modifyOxLdapProperties(server, installer, task_id, pDict)

    oxIDP=['localhost:1636']

    for server in gluu_installed_servers:
        if not server.id == exclude:
            laddr = server.ip if app_conf.use_ip else server.hostname
            oxIDP.append(laddr+':1636')

    adminOlc = LdapOLC('ldaps://{}:1636'.format(primary_server.hostname),
                        'cn=directory manager', primary_server.ldap_password)

    try:
        adminOlc.connect()
    except Exception as e:
        wlogger.log(
            task_id, "Connection to LDAPserver as directory manager at port 1636"
            " has failed: {0}".format(e), "error")
        wlogger.log(task_id, "Ending server setup process.", "error")
        return


    if adminOlc.configureOxIDPAuthentication(oxIDP):
        wlogger.log(task_id,
                'oxIDPAuthentication entry is modified to include all '
                'replicating servers',
                'success')
    else:
        wlogger.log(task_id, 'Modifying oxIDPAuthentication entry is failed: {}'.format(
                adminOlc.conn.result['description']), 'success')

    if app_conf.use_ldap_cache:
        adminOlc.changeOxCacheConfiguration('NATIVE_PERSISTENCE')
        wlogger.log(task_id,
                'cacheProviderType entry is set to NATIVE_PERSISTENCE',
                'success')

@celery.task(bind=True)
def opendjenablereplication(self, server_id):

    primary_server = Server.query.filter_by(primary_server=True).first()
    task_id = self.request.id
    app_conf = AppConfiguration.query.first()

    gluu_installed_servers = Server.query.filter_by(gluu_server=True).all()

    if server_id == 'all':
        servers = Server.get_all()
    else:
        servers = [Server.query.get(server_id)]

    installer = Installer(
                    primary_server, 
                    app_conf.gluu_version,
                    ssh_port=primary_server.ssh_port,
                    logger_task_id=task_id, 
                    server_os=primary_server.os
                    )

    if not installer.conn:
        return False

    # check if gluu server is installed
    if not installer.is_gluu_installed():
        wlogger.log(task_id, "Remote is not a gluu server.", "error")
        wlogger.log(task_id, "Ending server setup process.", "error")
        return False

    tmp_dir = os.path.join('/tmp', uuid.uuid1().hex[:12])
    os.mkdir(tmp_dir)

    wlogger.log(task_id, "Downloading opendj certificates")

    opendj_cert_files = ('keystore', 'keystore.pin', 'truststore')

    for certificate in opendj_cert_files:
        remote = os.path.join(installer.container, 'opt/opendj/config', certificate)
        local = os.path.join(tmp_dir, certificate)
        result = installer.download_file(remote, local)
        if not result:
            return False

    primary_server_secured = False

    for server in servers:
        if not server.primary_server:
            
            for base in ['gluu', 'site']:

                cmd = ( "OPENDJ_JAVA_HOME=/opt/jre "
                        "/opt/opendj/bin/dsreplication enable --host1 {} --port1 4444 "
                        "--bindDN1 'cn=directory manager' --bindPassword1 $'{}' "
                        "--replicationPort1 8989 --host2 {} --port2 4444 --bindDN2 "
                        "'cn=directory manager' --bindPassword2 $'{}' "
                        "--replicationPort2 8989 --adminUID admin --adminPassword $'{}' "
                        "--baseDN 'o={}' --trustAll -X -n").format(
                            primary_server.hostname,
                            primary_server.ldap_password,
                            server.hostname,
                            server.ldap_password,
                            app_conf.replication_pw,
                            base,
                            )
            
                wlogger.log(task_id, "Enabling replication on server {} for {}".format(
                                                            server.hostname, base))

                cmd_fn = os.path.join(installer.container, 'root/.cmd')
                installer.put_file(cmd_fn, cmd)
                wlogger.log(task_id, "Executing command: " + cmd)
                installer.run('bash /root/.cmd', error_exception='no base DNs available to enable replication')
                installer.run('rm -f /root/.cmd')


            if not primary_server_secured:

                wlogger.log(task_id, "Securing replication on primary server {}".format(
                                                                primary_server.hostname))

                cmd = ( "OPENDJ_JAVA_HOME=/opt/jre "
                        "/opt/opendj/bin/dsconfig -h {} -p 4444 "
                        " -D  'cn=Directory Manager' -w $'{}' --trustAll "
                        "-n set-crypto-manager-prop --set ssl-encryption:true"
                        ).format(primary_server.ip, primary_server.ldap_password)

                cmd_fn = os.path.join(installer.container, 'root/.cmd')
                installer.put_file(cmd_fn, cmd)
                wlogger.log(task_id, "Executing command: " + cmd)
                installer.run('bash /root/.cmd', error_exception='no base DNs available to enable replication')
                installer.run('rm -f /root/.cmd')
                
                primary_server_secured = True
                primary_server.mmr = True

            wlogger.log(task_id, "Securing replication on server {}".format(
                                                            server.hostname))
            cmd = ( "OPENDJ_JAVA_HOME=/opt/jre "
                    "/opt/opendj/bin/dsconfig -h {} -p 4444 "
                    " -D  'cn=Directory Manager' -w $'{}' --trustAll "
                    "-n set-crypto-manager-prop --set ssl-encryption:true"
                    ).format(server.ip, primary_server.ldap_password)

            cmd_fn = os.path.join(installer.container, 'root/.cmd')
            installer.put_file(cmd_fn, cmd)
            wlogger.log(task_id, "Executing command: " + cmd)
            installer.run('bash /root/.cmd', error_exception='no base DNs available to enable replication')
            installer.run('rm -f /root/.cmd')

            server.mmr = True


    db.session.commit()

    configure_OxIDPAuthentication(task_id, installers={installer.hostname:installer})

    servers = Server.query.filter(Server.primary_server.isnot(True)).all()

    node_installers = []

    for server in servers:

        if not server.primary_server:

            node_installer = Installer(
                    server, 
                    app_conf.gluu_version,
                    ssh_port=server.ssh_port,
                    logger_task_id=task_id, 
                    server_os=primary_server.os
                    )

            wlogger.log(task_id, "Uploading OpenDj certificate files")
            for certificate in opendj_cert_files:
                remote = os.path.join(node_installer.container, 'opt/opendj/config', certificate)
                local = os.path.join(tmp_dir, certificate)
                result = node_installer.upload_file(local, remote)
                
                if not result:
                    return False

            node_installer.restart_service('opendj')
            
            node_installers.append(node_installer)

    wlogger.log(task_id, "Waiting for OpenDJ Server to finish starting")
    time.sleep(20)


    wlogger.log(task_id, "Initialization replication on all servers")
    for base in ['gluu', 'site']:
        cmd = ( "OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsreplication "
                "initialize-all --adminUID admin "
                "--adminPassword $'{}' --baseDN o={} --hostname {} "
                "--port 4444 --trustAll --no-prompt"
                ).format(
                        app_conf.replication_pw,
                        base,
                        primary_server.hostname,
                        )
        
        cmd_fn = os.path.join(installer.container, 'root/.cmd')
        installer.put_file(cmd_fn, cmd)
        wlogger.log(task_id, "Executing command: " + cmd)
        installer.run('bash /root/.cmd', error_exception='no base DNs available to enable replication')
        installer.run('rm -f /root/.cmd')


    wlogger.log(task_id, "Restarting Cluster Nodes")
    for node_installer in node_installers:
            node_installer.restart_gluu()

    wlogger.log(task_id, "Restarting Primary Server")
    installer.restart_gluu()

    wlogger.log(task_id, "Waiting for Gluu to finish starting")
    time.sleep(40)

    wlogger.log(task_id, "Checking replication status")

    cmd = ( "OPENDJ_JAVA_HOME=/opt/jre "
            "/opt/opendj/bin/dsreplication status -n -X -h {} "
            "-p 4444 -I admin -w $'{}'").format(
                    primary_server.hostname,
                    app_conf.replication_pw)

    
    cmd_fn = os.path.join(installer.container, 'root/.cmd')
    installer.put_file(cmd_fn, cmd)
    wlogger.log(task_id, "Executing command: " + cmd)
    installer.run('bash /root/.cmd', error_exception='no base DNs available to enable replication')
    installer.run('rm -f /root/.cmd')

    return True


def get_nginx_installer(app_conf, task_id):
    #mock server
    nginx_server = Server(
                        hostname=app_conf.nginx_host, 
                        ip=app_conf.nginx_ip,
                        os=app_conf.nginx_os
                        )

    nginx_installer = Installer(
                    nginx_server, 
                    app_conf.gluu_version, 
                    logger_task_id=task_id,
                    ssh_port=app_conf.nginx_ssh_port,
                    server_os=nginx_server.os
                    )

    return nginx_installer

@celery.task(bind=True)
def installNGINX(self, nginx_host, session_type):
    """Installs nginx load balancer

    Args:
        nginx_host: hostname of server on which we will install nginx
    """

    task_id = self.request.id
    app_conf = AppConfiguration.query.first()
    primary_server = Server.query.filter_by(primary_server=True).first()

    nginx_installer = get_nginx_installer(app_conf, task_id)

    if not nginx_installer.conn:
        return False

    if not nginx_installer.conn.exists('/usr/bin/python'):
        
        if app_conf.offline:
            wlogger.log(
                task_id, 
                'python was not installed. Please install python and retry.', 
                'error'
                )
            return False

        nginx_installer.install('python', inside=False)

    #check if nginx was installed on this server
    wlogger.log(task_id, "Check if NGINX installed")

    if not nginx_installer.conn.exists("/usr/sbin/nginx"):

        if app_conf.offline:
            wlogger.log(
                task_id, 
                'nginx was not installed. Please install nginx and retry.', 
                'error'
                )
            return False

        nginx_installer.epel_release()

        if session_type == 'ip_hash':
            nginx_installer.install('nginx', inside=False, error_exception= '__ALL__')

        else:
            if 'ubuntu' in nginx_installer.server_os.lower():
                ubuntu_sticky_packages = {
                        '18': [ 
                                'nginx-common_1.14.0-0ubuntu1.7_all.deb',
                                'libnginx-mod-http-geoip_1.14.0-0ubuntu1.7_amd64.deb',
                                'libnginx-mod-http-image-filter_1.14.0-0ubuntu1.7_amd64.deb',
                                'libnginx-mod-http-xslt-filter_1.14.0-0ubuntu1.7_amd64.deb',
                                'libnginx-mod-mail_1.14.0-0ubuntu1.7_amd64.deb',
                                'libnginx-mod-stream_1.14.0-0ubuntu1.7_amd64.deb',
                                'nginx-core_1.14.0-0ubuntu1.7_amd64.deb'
                                ],
                        '20': [
                           
                                'nginx-common_1.18.0-0ubuntu1_all.deb',
                                'libnginx-mod-http-geoip_1.18.0-0ubuntu1_amd64.deb',
                                'libnginx-mod-http-xslt-filter_1.18.0-0ubuntu1_amd64.deb',
                                'libnginx-mod-mail_1.18.0-0ubuntu1_amd64.deb',
                                'libnginx-mod-stream_1.18.0-0ubuntu1_amd64.deb',
                                'libnginx-mod-http-image-filter_1.18.0-0ubuntu1_amd64.deb',
                                'nginx-core_1.18.0-0ubuntu1_amd64.deb',
                                ]
                        }
                ubuntu_ver = nginx_installer.server_os.split()[1]
                for package in ubuntu_sticky_packages[ubuntu_ver]:
                    wlogger.log(task_id, "Download and Install" + package, "debug")
                    package_url = 'http://162.243.99.240/icrby8xcvbcv/nginx/ubuntu{}/{}'.format(ubuntu_ver, package)
                    nginx_installer.run('wget -nv {} -O /tmp/{} 2>&1'.format(package_url, package), inside=False)
                    nginx_installer.run('DEBIAN_FRONTEND=noninteractive dpkg -i /tmp/{} 2>&1'.format(package), inside=False)
                    nginx_installer.run('DEBIAN_FRONTEND=noninteractive apt-get install -y -f 2>&1', inside=False)
            elif nginx_installer.server_os == 'CentOS 7':
                nginx_installer.run('yum install -y http://162.243.99.240/icrby8xcvbcv/nginx/centos7/nginx-1.14.2-1.gluu.centos7.x86_64.rpm 2>&1', inside=False)
            elif nginx_installer.server_os == 'RHEL 7':
                nginx_installer.run('yum install -y http://162.243.99.240/icrby8xcvbcv/nginx/rhel7/nginx-1.14.2-1.gluu.rhel7.x86_64.rpm 2>&1', inside=False)
            elif nginx_installer.server_os in ('CentOS 8', 'RHEL 8'):
                nginx_installer.run('yum install -y http://162.243.99.240/icrby8xcvbcv/nginx/el8/nginx-1.19.6-1.el8.ngx_sticky.x86_64.rpm 2>&1', inside=False)


    #Check if ssl certificates directory exist on this server
    result = nginx_installer.conn.exists("/etc/nginx/ssl/")
    if not result:
        wlogger.log(task_id, "/etc/nginx/ssl/ does not exists. Creating ...",
                            "debug")
        result = nginx_installer.run("mkdir -p /etc/nginx/ssl/", inside=False)
        if result:
            wlogger.log(task_id, "/etc/nginx/ssl/ was created", "success")
        else:
            wlogger.log(task_id, 
                        "Error creating /etc/nginx/ssl/ {0}".format(result[1]),
                        "error")
            wlogger.log(task_id, "Ending server setup process.", "error")
            return False
    else:
        wlogger.log(task_id, "Directory /etc/nginx/ssl/ exists.", "debug")

    # we need to download ssl certifiactes from primary server.
    wlogger.log(task_id, "Making SSH connection to primary server {} for "
                     "downloading certificates".format(primary_server.hostname))

    primary_installer = Installer(
                    primary_server,
                    app_conf.gluu_version,
                    logger_task_id=task_id,
                    ssh_port=primary_server.ssh_port,
                    server_os=primary_server.os
                    )

    # get httpd.crt and httpd.key from primary server and put to this server
    for crt_file in ('httpd.crt', 'httpd.key'):
        wlogger.log(task_id, "Downloading {0} from primary server".format(crt_file), "debug")
        remote_file = '/opt/gluu-server/etc/certs/{0}'.format(crt_file)
        file_content = primary_installer.get_file(remote_file)

        if not file_content:
            return False

        remote_file = os.path.join("/etc/nginx/ssl/", crt_file)

        result = nginx_installer.put_file(remote_file, file_content)
        if not result:
            return False

    primary_installer.conn.close()
    
    nginx_config = make_nginx_proxy_conf()

    #put nginx.conf to server
    remote_file = "/etc/nginx/nginx.conf"
    result = nginx_installer.put_file(remote_file, nginx_config)

    if not result:
        return False

    if app_conf.modify_hosts:
        
        host_ip = []
        servers = Server.get_all()

        for ship in servers:
            host_ip.append((ship.hostname, ship.ip))

        host_ip.append((app_conf.nginx_host, app_conf.nginx_ip))
        modify_hosts(nginx_installer, host_ip, inside=False)

    nginx_installer.enable_service('nginx', inside=False)
    nginx_installer.restart_service('nginx', inside=False)

    # write nginx os type to database
    app_conf.nginx_os_type = nginx_installer.server_os
    db.session.commit()

    wlogger.log(task_id, "NGINX successfully installed")


@celery.task(bind=True)
def uninstallNGINX(self):
    task_id = self.request.id
    app_conf = AppConfiguration.query.first()
    nginx_installer = get_nginx_installer(app_conf, task_id)

    if not nginx_installer.conn:
        wlogger.log(
            task_id, 
            'ssh connection to nginx host failed', 
            'error'
            )
        return

    if 'ubuntu' in nginx_installer.server_os.lower():
        nginx_installer.run('DEBIAN_FRONTEND=noninteractive apt-get -y purge nginx-common 2>&1', inside=False)
    else:
        nginx_installer.run('yum remove -y nginx', inside=False)

    nginx_installer.run('rm -r -f /etc/nginx', inside=False)

    return True

def exec_cmd(command):    
    popen = subprocess.Popen(command, stdout=subprocess.PIPE)
    return iter(popen.stdout.readline, b"")


@celery.task(bind=True)
def upgrade_clustermgr_task(self):
    task_id = self.request.id
    
    cmd = '/usr/bin/sudo pip install --upgrade https://github.com/GluuFederation/cluster-mgr/archive/4.1.zip'

    wlogger.log(task_id, cmd)

    for line in exec_cmd(cmd.split()):
        wlogger.log(task_id, line, 'debug')
    
    return


@celery.task(bind=True)
def register_objectclass(self, objcls):
    
    task_id = self.request.id
    primary = Server.query.filter_by(primary_server=True).first()

    servers = Server.get_all()
    app_conf = AppConfiguration.query.first()

    
    wlogger.log(task_id, "Making LDAP connection to primary server {}".format(primary.hostname))
    
    ldp = getLdapConn(  primary.hostname,
                        "cn=directory manager",
                        primary.ldap_password
                        )
    
    result = ldp.registerObjectClass(objcls)
 
    if not result:
        wlogger.log(task_id, "Attribute cannot be registered".format(primary.hostname), 'error')
        return False
    else:
        wlogger.log(task_id, "Object class is registered",'success')


    for server in servers:
        installer = Installer(server, app_conf.gluu_version, ssh_port=server.ssh_port, logger_task_id=task_id)
        if installer.conn:
            wlogger.log(task_id, "Restarting idendity at {}".format(server.hostname))
            installer.run('/etc/init.d/identity restart', error_exception='__ALL__')
    
    app_conf.object_class_base = objcls
    db.session.commit()
    
    return True

@celery.task(bind=True)
def update_httpd_certs_task(self, httpd_key, httpd_crt):
    
    task_id = self.request.id
    app_conf = AppConfiguration.query.first()

    servers = Server.get_all()

    if not app_conf.external_load_balancer:
        mock_server = Server()
        mock_server.hostname = app_conf.nginx_host
        mock_server.ip = app_conf.nginx_ip
        mock_server.proxy = True
        mock_server.os = app_conf.nginx_os_type
        servers.insert(0, mock_server)

    for server in servers:
        installer = Installer(server, app_conf.gluu_version, ssh_port=server.ssh_port, logger_task_id=task_id)
        if hasattr(server, 'proxy'):
            if not server.os:
                print "Determining nginx os type"
                app_conf.nginx_os_type = installer.server_os
                db.session.commit()

            key_path = '/etc/nginx/ssl/httpd.key'
            crt_path = '/etc/nginx/ssl/httpd.crt'
        else:
            key_path = os.path.join(installer.container, 'etc/certs/httpd.key')
            crt_path = os.path.join(installer.container, 'etc/certs/httpd.crt')

        installer.put_file(key_path, httpd_key)        
        installer.put_file(crt_path, httpd_crt)

        if hasattr(server, 'proxy'):
            installer.restart_service('nginx', inside=False)
        else:
            installer.delete_key('httpd', app_conf.nginx_host)
            installer.import_key('httpd', app_conf.nginx_host)
            installer.restart_gluu()

    return True


@celery.task
def check_latest_version():
    app_conf = AppConfiguration.query.first()
    if app_conf:
        print "Checking latest version from github"
        result = requests.get('https://raw.githubusercontent.com/GluuFederation/cluster-mgr/4.1/clustermgr/__init__.py')
        text = result.text.strip()
        latest_version = text.split('=')[1].strip().strip('"').strip("'")        
        app_conf.latest_version = latest_version
        print "Latest github version is %s" % latest_version
        db.session.commit()
