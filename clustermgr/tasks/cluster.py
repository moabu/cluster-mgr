# -*- coding: utf-8 -*-

import os
import re
import time
import subprocess
import traceback
from flask import current_app as app

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import wlogger, db, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import LdapOLC, getLdapConn
from clustermgr.core.utils import get_setup_properties, modify_etc_hosts, \
        make_nginx_proxy_conf, make_twem_proxy_conf, make_proxy_stunnel_conf
from clustermgr.core.clustermgr_installer import Installer
from clustermgr.config import Config
import uuid
import select


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
    remote_file = os.path.join(installer.container, 'etc/gluu/conf/ox-ldap.properties')
    result = installer.get_file(remote_file)

    state = True

    # iterate ox-ldap.properties file and modify "servers" entry
    if result:
        file_content = ''
        for line in result:
            if line.startswith('servers:'):
                line = 'servers: {0}\n'.format( pDict[server.hostname] )
            file_content += line

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
                'include all replicating servers: {1}'.format(server.hostname, temp),
                'warning')


def get_csync2_config(exclude=None):

    replication_user_file = os.path.join(Config.DATA_DIR,
                            'fs_replication_paths.txt')

    sync_directories = []

    for l in open(replication_user_file).readlines():
        sync_directories.append(l.strip())


    exclude_files = [
        '/etc/gluu/conf/ox-ldap.properties',
        '/etc/gluu/conf/oxTrustLogRotationConfiguration.xml',
        '/etc/gluu/conf/openldap/salt',
        ]

    csync2_config = ['group gluucluster','{']

    all_servers = Server.query.all()

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

    servers = Server.query.all()
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
                                server_os=server.os
                            )
        
        modify_hosts(installer, cysnc_hosts)

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

            csync_rpm = 'https://github.com/mbaser/gluu/raw/master/csync2-2.0-3.gluu.centos{}.x86_64.rpm'.format(server.os[-1])
            installer.install(csync_rpm)
            
            installer.stop_service('xinetd stop')

        if server.os == 'CentOS 6':
            installer.install('crontabs')

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
            csync_line = 'csync2\tstream\ttcp\tnowait\troot\t/usr/sbin/csync2\tcsync2 -i -l -N csync{}.gluu\n'.format(server.id) 
            csync_line_exists = False
            for line in inet_conf_file:
                if line.startswith('csync2'):
                    line = csync_line
                    csync_line_exists = True
                new_inet_conf_file_content.append(line)
            if not csync_line_exists:
                new_inet_conf_file_content.append(csync_line)
            new_inet_conf_file_content = ''.join(new_inet_conf_file_content)
            installer.put_file(inet_conf_file, new_inet_conf_file_content)

            installer.run('/etc/init.d/openbsd-inetd restart')

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
            '{}-59/2 * * * *    root    {} -N csync{}.gluu -xv 2>/var/log/csync2.log\n'.format(
            server_counter, csync2_path, server.id))

        server_counter += 1
        
        wlogger.log(task_id, 'Crontab entry was created to sync files in every minute',
                         'debug', server_id=server.id)

        if installer.clone_type == 'rpm':
            cmd = 'service crond reload'
            installer.start_service('xinetd')
            installer.restart_service('crond')
        else:
            installer.restart_service('cron')
            installer.restart_service('openbsd-inetd')


    return True

def remove_filesystem_replication_do(server, app_config, task_id):

        installer = Installer(server, app_config.gluu_version, logger_task_id=task_id)
        if not installer.conn:
            return False
        installer.run('rm /etc/cron.d/csync2')
        
        if 'CentOS' in server.os or 'RHEL' in server.os :
            installer.run('rm /etc/xinetd.d/csync2')
            services = ['xinetd', 'crond']
            
        else:
            installer.run("sed 's/^csync/#&/' -i /etc/inetd.conf")
            services = ['openbsd-inetd', 'cron']
            
        for s in services:
            installer.restart_service(s)
            
        installer.run('rm /var/lib/csync2/*.*')

        return True


@celery.task(bind=True)
def remove_filesystem_replication(self):
    task_id = self.request.id
    
    app_config = AppConfiguration.query.first()
    servers = Server.query.all()
    
    for server in servers:
        r = remove_filesystem_replication_do(server, app_config, task_id)
        if not r:
            return r

@celery.task(bind=True)
def setup_ldap_replication(self, server_id):
    """Deploys ldap replicaton

    Args:
        server_id (integer): id of server to be deployed replication
    """

    #MB: removed until openldap replication is validated

    pass


def modify_hosts(installer, hosts, inside=True, server_host=None):
    wlogger.log(installer.logger_task_id, "Modifying /etc/hosts", server_id=installer.server_id)
    chroot = installer.container if inside else '/'
    hosts_file = os.path.join(chroot,'etc/hosts')
    
    old_hosts = installer.get_file(hosts_file)
    
    if old_hosts:
        new_hosts = modify_etc_hosts(hosts, old_hosts)
        installer.put_file(hosts_file, new_hosts)
        wlogger.log(installer.logger_task_id, "{} was modified".format(hosts_file), 'success', server_id=installer.server_id)


def download_and_upload_custom_schema(tid, pc, c, ldap_type, gluu_server):
    """Downloads custom ldap schema from primary server and 
        uploads to current server represented by c
    Args:
        tid (string): id of the task running the command,
        pc (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication, representing primary server

        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication, representing current server
        ldap_type (string): type of ldapserver, either openldap or opendj
        gluu_server: Gluu server name
    """
    
    wlogger.log(tid, 'Downloading custom schema files' 
                    'from primary server and upload to this server')
    custom_schema_files = pc.listdir("/opt/{}/opt/gluu/schema/{}/".format(
                                                    gluu_server, ldap_type))

    if custom_schema_files[0]:
        
        schema_folder = '/opt/{}/opt/gluu/schema/{}'.format(
                        gluu_server, ldap_type)
        if not c.exists(schema_folder):
            c.run('mkdir -p {}'.format(schema_folder))
        
        for csf in custom_schema_files[1]:
            schema_filename = '/opt/{0}/opt/gluu/schema/{2}/{1}'.format(
                                                gluu_server, csf, ldap_type)
                                                
            stat, schema = pc.get_file(schema_filename)
            if stat:
                c.put_file(schema_filename, schema.read())
                wlogger.log(tid, 
                    '{0} dowloaded from from primary and uploaded'.format(
                                                            csf), 'debug')

                if ldap_type == 'opendj':

                    opendj_path = ('/opt/{}/opt/opendj/config/schema/'
                                '999-clustmgr-{}').format(gluu_server, csf)
                    c.run('cp {} {}'.format(schema_filename, opendj_path))
                    
            
def upload_custom_schema(tid, c, ldap_type, gluu_server):
    """Uploads custom ldap schema to server
    Args:
        tid (string): id of the task running the command,
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        ldap_type (string): type of ldapserver, either openldap or opendj
        gluu_server: Gluu server name
    """
    
    custom_schema_dir = os.path.join(Config.DATA_DIR, 'schema')
    custom_schemas = os.listdir(custom_schema_dir)

    if custom_schemas:
        schema_folder = '/opt/{}/opt/gluu/schema/{}'.format(
                        gluu_server, ldap_type)
        if not c.exists(schema_folder):
            c.run('mkdir -p {}'.format(schema_folder))

        for sf in custom_schemas:
            
            local = os.path.join(custom_schema_dir, sf)
            remote = '/opt/{0}/opt/gluu/schema/{2}/{1}'.format(
                gluu_server, sf, ldap_type)
            r = c.upload(local, remote)
            if r[0]:
                wlogger.log(tid, 'Custom schame file {0} uploaded'.format(
                        sf), 'success')
            else:
                wlogger.log(tid,
                    "Can't upload custom schame file {0}: ".format(sf,
                                                            r[1]), 'error')
    
@celery.task(bind=True)
def removeMultiMasterDeployement(self, server_id):
    """Removes multi master replication deployment

    Args:
        server_id: id of server to be un-depoloyed
    """
    #MB: removed until openldap replication is validated
    
    pass


def do_disable_replication(task_id, server, primary_server, app_conf):

    installer = Installer(
                    server, 
                    app_conf.gluu_version, 
                    logger_task_id=task_id, 
                    server_os=server.os
                    )

    if not installer.conn:
        return False
    
    wlogger.log(task_id, 
        "Disabling replication for {0}".format(
        server.hostname)
        )

    cmd = ('/opt/opendj/bin/dsreplication disable --disableAll --port 4444 '
            '--hostname {} --adminUID admin --adminPassword $\'{}\' '
            '--trustAll --no-prompt').format(
                            server.hostname,
                            app_conf.replication_pw)


    installer.run(cmd, error_exception='no base DNs replicated')

    server.mmr = False
    db.session.commit()

    configure_OxIDPAuthentication(task_id, exclude=server.id, installers={installer.hostname:installer})

    wlogger.log(task_id, "Checking replication status", 'debug')

    cmd = ('/opt/opendj/bin/dsreplication status -n -X -h {} '
            '-p 1444 -I admin -w $\'{}\'').format(
                    primary_server.hostname,
                    app_conf.replication_pw)

    installer.run(cmd)

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

    nginx_installer = None

        
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
                    server_os=nginx_server.os
                    )
                        
    if not app_conf.external_load_balancer:
        # Update nginx
        nginx_config = make_nginx_proxy_conf(exception=server_id)
        remote = "/etc/nginx/nginx.conf"
        nginx_installer.put_file(remote, nginx_config)
        
        nginx_installer.restart_service('nginx')
    

    # Update Twemproxy
    wlogger.log(task_id, "Updating Twemproxy configuration",'debug')
    twemproxy_conf = make_twem_proxy_conf(exception=server_id)
    remote = "/etc/nutcracker/nutcracker.yml"
    nginx_installer.put_file(remote, twemproxy_conf)

    nginx_installer.restart_service('nutcracker')

    # Update stunnel
    proxy_stunnel_conf = make_proxy_stunnel_conf(exception=server_id)
    proxy_stunnel_conf = '\n'.join(proxy_stunnel_conf)
    remote = '/etc/stunnel/stunnel.conf'
    nginx_installer.put_file(remote, proxy_stunnel_conf)

    if nginx_installer.clone_type == 'rpm':
        nginx_installer.restart_service('stunnel')
    else:
        nginx_installer.restart_service('stunnel4')


    if disable_replication:
        result = do_disable_replication(task_id, server, primary_server, app_conf)
        if not result:
            return False

    if remove_server:
        db.session.delete(server)


    for server in Server.query.all():
        if server.gluu_server:
        
            installer = Installer(
                        server,
                        app_conf.gluu_version,
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

    chroot_fs = '/opt/gluu-server-' + app_conf.gluu_version

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



@celery.task(bind=True)
def opendjenablereplication(self, server_id):

    primary_server = Server.query.filter_by(primary_server=True).first()
    task_id = self.request.id
    app_conf = AppConfiguration.query.first()

    gluu_installed_servers = Server.query.filter_by(gluu_server=True).all()

    if server_id == 'all':
        servers = Server.query.all()
    else:
        servers = [Server.query.get(server_id)]

    installer = Installer(
                    primary_server, 
                    app_conf.gluu_version, 
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
            wlogger.log(task_id, "Enabling replication on server {}".format(
                                                            server.hostname))

            for base in ['gluu', 'site']:

                cmd = ('/opt/opendj/bin/dsreplication enable --host1 {} --port1 4444 '
                        '--bindDN1 \'cn=directory manager\' --bindPassword1 $\'{}\' '
                        '--replicationPort1 8989 --host2 {} --port2 4444 --bindDN2 '
                        '\'cn=directory manager\' --bindPassword2 $\'{}\' '
                        '--replicationPort2 8989 --adminUID admin --adminPassword $\'{}\' '
                        '--baseDN \'o={}\' --trustAll -X -n').format(
                            primary_server.hostname,
                            primary_server.ldap_password.replace("'","\\'"),
                            server.hostname,
                            server.ldap_password.replace("'","\\'"),
                            app_conf.replication_pw.replace("'","\\'"),
                            base,
                            )
                
                installer.run(cmd, error_exception='no base DNs available to enable replication')

                wlogger.log(task_id, "Inıtializing replication on server {}".format(
                                                                server.hostname))

                cmd = ('/opt/opendj/bin/dsreplication initialize --baseDN \'o={}\' '
                        '--adminUID admin --adminPassword $\'{}\' '
                        '--portSource 4444  --hostDestination {} --portDestination 4444 '
                        '--trustAll -X -n').format(
                            base,
                            app_conf.replication_pw.replace("'","\\'"),
                            server.hostname,
                            )

                installer.run(cmd, error_exception='no base DNs available to enable replication')

            if not primary_server_secured:

                wlogger.log(task_id, "Securing replication on primary server {}".format(
                                                                primary_server.hostname))

                cmd = ('/opt/opendj/bin/dsconfig -h {} -p 4444 '
                        ' -D  \'cn=Directory Manager\' -w $\'{}\' --trustAll '
                        '-n set-crypto-manager-prop --set ssl-encryption:true'
                        ).format(primary_server.hostname, primary_server.ldap_password.replace("'","\\'"))

                installer.run(cmd)
                
                primary_server_secured = True
                primary_server.mmr = True

            wlogger.log(task_id, "Securing replication on server {}".format(
                                                            server.hostname))
            cmd = ('/opt/opendj/bin/dsconfig -h {} -p 4444 '
                    ' -D  \'cn=Directory Manager\' -w $\'{}\' --trustAll '
                    '-n set-crypto-manager-prop --set ssl-encryption:true'
                    ).format(server.hostname, primary_server.ldap_password.replace("'","\\'"))

            installer.run(cmd)

            server.mmr = True


    db.session.commit()

    configure_OxIDPAuthentication(task_id, installers={installer.hostname:installer})

    servers = Server.query.filter(Server.primary_server.isnot(True)).all()

    for server in servers:

        if not server.primary_server:

            node_installer = Installer(
                    server, 
                    app_conf.gluu_version, 
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

        node_installer.restart_gluu()

    installer.restart_gluu()

    if 'CentOS' in primary_server.os:
        wlogger.log(tid, "Waiting for Gluu to finish starting")
        time.sleep(60)
    

    wlogger.log(task_id, "Checking replication status")

    cmd = ('/opt/opendj/bin/dsreplication status -n -X -h {} '
            '-p 1444 -I admin -w $\'{}\'').format(
                    primary_server.hostname,
                    app_conf.replication_pw.replace("'","\\'"))

    installer.run(cmd)

    return True


@celery.task(bind=True)
def installNGINX(self, nginx_host):
    """Installs nginx load balancer

    Args:
        nginx_host: hostname of server on which we will install nginx
    """
    task_id = self.request.id
    app_conf = AppConfiguration.query.first()
    primary_server = Server.query.filter_by(primary_server=True).first()

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
                    server_os=nginx_server.os
                    )

    if not nginx_installer.conn:
        return False


    #check if nginx was installed on this server
    wlogger.log(task_id, "Check if NGINX installed")

    result = nginx_installer.conn.exists("/usr/sbin/nginx")

    if result:
        wlogger.log(task_id, "nginx allready exists")
    else:
        nginx_installer.epel_release()
        nginx_installer.install('nginx', inside='False')

    #Check if ssl certificates directory exist on this server
    result = nginx_installer.conn.exists("/etc/nginx/ssl/")
    if not result:
        wlogger.log(task_id, "/etc/nginx/ssl/ does not exists. Creating ...",
                            "debug")
        result = result.conn.mkdir("/etc/nginx/ssl/")
        if result[0]:
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
                    server_os=primary_server.os
                    )

    # get httpd.crt and httpd.key from primary server and put to this server
    for crt_file in ('httpd.crt', 'httpd.key'):
        wlogger.log(task_id, "Downloading {0} from primary server".format(crt_file), "debug")
        remote_file = '/opt/gluu-server-{0}/etc/certs/{1}'.format(app_conf.gluu_version, crt_file)
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

    nginx_installer.enable_service('nginx', inside=False)
    nginx_installer.start_service('nginx', inside=False)
    
    if app_conf.modify_hosts:
        
        host_ip = []
        servers = Server.query.all()

        for ship in servers:
            host_ip.append((ship.hostname, ship.ip))

        host_ip.append((app_conf.nginx_host, app_conf.nginx_ip))
        modify_hosts(nginx_installer, host_ip, inside=False)

    wlogger.log(task_id, "NGINX successfully installed")

def exec_cmd(command):    
    popen = subprocess.Popen(command, stdout=subprocess.PIPE)
    return iter(popen.stdout.readline, b"")


@celery.task(bind=True)
def upgrade_clustermgr_task(self):
    task_id = self.request.id
    
    cmd = '/usr/bin/sudo pip install --upgrade https://github.com/GluuFederation/cluster-mgr/archive/master.zip'

    wlogger.log(task_id, cmd)

    for line in exec_cmd(cmd.split()):
        wlogger.log(task_id, line, 'debug')
    
    return


@celery.task(bind=True)
def register_objectclass(self, objcls):
    
    tid = self.request.id
    primary = Server.query.filter_by(primary_server=True).first()

    servers = Server.query.all()
    appconf = AppConfiguration.query.first()

    
    wlogger.log(tid, "Making LDAP connection to primary server {}".format(primary.hostname))
    
    ldp = getLdapConn(  primary.hostname,
                        "cn=directory manager",
                        primary.ldap_password
                        )
    
    r = ldp.registerObjectClass(objcls)
 
    if not r:
        wlogger.log(tid, "Attribute cannot be registered".format(primary.hostname), 'error')
        return False
    else:
        wlogger.log(tid, "Object class is registered",'success')


    for server in servers:
        installer = Installer(server, appconf.gluu_version, logger_tid=tid)
        if installer.c:
            wlogger.log(tid, "Restarting idendity at {}".format(server.hostname))
            installer.run('/etc/init.d/identity restart')
    
    appconf.object_class_base = objcls
    db.session.commit()
    
    return True

