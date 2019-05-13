# -*- coding: utf-8 -*-

import os
import re
import time
import subprocess
import requests

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

def run_command(tid, c, command, container=None, no_error='error',  server_id='', exclude_error=None):
    """Shorthand for RemoteClient.run(). This function automatically logs
    the commands output at appropriate levels to the WebLogger to be shared
    in the web frontend.

    Args:
        tid (string): task id of the task to store the log
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        command (string): the command to be run on the remote server
        container (string, optional): location where the Gluu Server container
            is installed. For standalone LDAP servers this is not necessary.

    Returns:
        the output of the command or the err thrown by the command as a string
    """
    
    excluded_errors = [
                        'config file testing succeeded',
                        'There are no base DNs available to enable replication between the two servers',
                        'Redirecting to',
                        'warning: /var/cache/',
                        'Created symlink from',
                    ]
                    
    if exclude_error:
        excluded_errors.append(exclude_error)
    
    if container == '/':
        container = None
    if container:
        command = "chroot {0} /bin/bash -c $'{1}'".format(container,
                                                         command)

    print "command", command

    wlogger.log(tid, command, "debug", server_id=server_id)

    cin, cout, cerr = c.run(command)
    output = ''

    if cout:
        wlogger.log(tid, cout, "debug", server_id=server_id)
        output += "\n" + cout

    if cerr:        
        not_error = False
        for ee in excluded_errors:
            if cerr.startswith(ee):
                not_error = True
                break
        
        # For some reason slaptest decides to send success message as err, so
        if not_error:
            wlogger.log(tid, cerr, "debug", server_id=server_id)
        else:
            wlogger.log(tid, cerr, no_error, server_id=server_id)
        output += "\n" + cerr

    return output


def upload_file(tid, c, local, remote, server_id=''):
    """Shorthand for RemoteClient.upload(). This function automatically handles
    the logging of events to the WebLogger

    Args:
        tid (string): id of the task running the command
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        local (string): local location of the file to upload
        remote (string): location of the file in remote server
    """
    out = c.upload(local, remote)
    wlogger.log(tid, out, 'error' if 'Error' in out else 'success', server_id=server_id)


def download_file(tid, c, remote, local, server_id=''):
    """Shorthand for RemoteClient.download(). This function automatically
     handles the logging of events to the WebLogger

    Args:
        tid (string): id of the task running the command
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        remote (string): location of the file in remote server
        local (string): local location of the file to upload
    """
    out = c.download(remote, local)
    wlogger.log(tid, out, 'error' if 'Error' in out else 'success', server_id=server_id)


def modifyOxLdapProperties(server, c, tid, pDict, chroot):
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
    remote_file = os.path.join(chroot, 'etc/gluu/conf/ox-ldap.properties')
    ox_ldap = c.get_file(remote_file)

    temp = None

    # iterate ox-ldap.properties file and modify "servers" entry
    if ox_ldap[0]:
        fc = ''
        for l in ox_ldap[1]:
            if l.startswith('servers:'):
                l = 'servers: {0}\n'.format( pDict[server.hostname] )
            fc += l

        r = c.put_file(remote_file,fc)

        if r[0]:
            wlogger.log(tid,
                'ox-ldap.properties file on {0} modified to include '
                'all replicating servers'.format(server.hostname),
                'success')
        else:
            temp = r[1]
    else:
        temp = ox_ldap[1]

    if temp:
        wlogger.log(tid,
                'ox-ldap.properties file on {0} was not modified to '
                'include all replicating servers: {1}'.format(server.hostname, temp),
                'warning')

    """
    # Modify Shib ldap.properties to include all ldap properties
    remote_file = os.path.join(chroot, 'opt/shibboleth-idp/conf/ldap.properties')
    shib_ldap = c.get_file(remote_file)

    temp = None

    if shib_ldap[0]:
         
        ldap_server_list = [ 'ldaps://'+ldap_server for ldap_server in pDict[server.hostname].split(',') ]
        server_list_string = ' '.join(ldap_server_list)

        # iterate ldap.properties file and modify idp.authn.LDAP.ldapURL entry

        fc = ''
        for l in shib_ldap[1]:
            if l.startswith('idp.authn.LDAP.ldapURL'):
                l = 'idp.authn.LDAP.ldapURL                          = {}\n'.format( server_list_string )
            fc += l

        r = c.put_file(remote_file,fc)

        if r[0]:
            wlogger.log(tid,
                '/opt/shibboleth-idp/conf/ldap.properties file on {0} modified to include '
                'all replicating servers'.format(server.hostname),
                'success')
        else:

            wlogger.log(tid,
                '/opt/shibboleth-idp/conf/ldap.propertiess file on {0} was not modified to '
                'include all replicating servers: {1}'.format(server.hostname, r[1]),
                'warning')

    """


def get_csync2_config(exclude=None):

    fsr_file_name = os.path.join(app.root_path, 'templates',
                                    'file_system_replication',
                                    'replication_defaults.txt')
                                    

    user_fsr_file_name = os.path.join(app.config["DATA_DIR"], 'fsr_paths')
    
    if os.path.exists(user_fsr_file_name):
        fsr_file_name = user_fsr_file_name


    sync_directories = []

    for l in open(fsr_file_name).readlines():
        if l.strip():
            sync_directories.append(l.strip())


    exclude_files = [
        '/etc/gluu/conf/ox-ldap.properties',
        '/etc/gluu/conf/oxTrustLogRotationConfiguration.xml',
        '/etc/gluu/conf/salt',

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

def get_chroot():
    app_config = AppConfiguration.query.first()
    chroot = '/opt/gluu-server-' + app_config.gluu_version
    return chroot

def get_run_cmd(server):
    run_cmd = "{}"
    cmd_chroot = get_chroot()

    if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        cmd_chroot = None
        run_cmd = ("ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o "
            "Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no "
            "-o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes "
            "root@localhost $'{}'")
                
    return run_cmd, cmd_chroot


def restart_inetd(tid, c, server):

    run_cmd , cmd_chroot = get_run_cmd(server)

    if server.os in ('Ubuntu 16', 'Debian 9', 'Ubuntu 18'):
    
        cmd = run_cmd.format('/etc/init.d/openbsd-inetd stop')
        run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)


        # ubuntu is buggy, sometimes it can't stop inetd
        if server.os == 'Ubuntu 16':
            pids = c.run('pidof inetd')
            if pids[1].strip():
                cmd = 'kill -9 {0}'.format( pids[1].strip())
                run_command(tid, c, cmd, cmd_chroot, no_error='debug', server_id=server.id)


        cmd = run_cmd.format('/etc/init.d/openbsd-inetd start')
        run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)

    
    if ('CentOS' in server.os) or ('RHEL' in server.os):

        cmd = run_cmd.format('service xinetd restart')
        run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)



@celery.task(bind=True)
def update_filesystem_replication_paths(self):
    tid = self.request.id

    servers = Server.query.all()
    app_config = AppConfiguration.query.first()
    
    chroot = '/opt/gluu-server-' + app_config.gluu_version
    csync2_config = get_csync2_config()
    
    for server in servers:
        c = RemoteClient(server.hostname, ip=server.ip)
        c.startup()

        remote_file = os.path.join(chroot, 'etc', 'csync2.cfg')
        wlogger.log(tid, "Uploading csync2.cfg", 'debug', server_id=server.id)
        c.put_file(remote_file,  csync2_config)
        restart_inetd(tid, c, server)


@celery.task(bind=True)
def setup_filesystem_replication(self):
    """Deploys File System replicaton
    """

    tid = self.request.id

    servers = Server.query.all()
    app_config = AppConfiguration.query.first()

    chroot = '/opt/gluu-server-' + app_config.gluu_version
    
    cysnc_hosts = []
    for server in servers:
        cysnc_hosts.append(('csync{}.gluu'.format(server.id), server.ip))

    server_counter = 0

    for server in servers:
        
        c = RemoteClient(server.hostname, ip=server.ip)
        c.startup()

        modify_hosts(tid, c, cysnc_hosts, chroot=chroot, server_id=server.id)

        run_cmd , cmd_chroot = get_run_cmd(server)

        cmd = run_cmd.format('rm -f /etc/csync2*')
        run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)
        

        cmd = run_cmd.format('rm -f /var/lib/csync2/*.db3')
        run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)


        if not c.exists(os.path.join(chroot, 'usr/sbin/csync2')):

            if app_config.offline:
            
                wlogger.log(
                    tid, 
                    'csync2 was not installed. Please install csync2 and retry.', 
                    'error',
                    server_id=server.id
                )
                return False
            else:

                if 'Ubuntu' in server.os:
                    
                    print("*"*50)
                    cmd_list = ['localedef -i en_US -f UTF-8 en_US.UTF-8',
                                'locale-gen en_US.UTF-8',
                                'apt-get -y update'.format('DEBIAN_FRONTEND=noninteractive apt-get'),
                                'apt-get install -y apt-utils',
                                'apt-get install -y csync2',
                                ]
                    
                    for cmdi in cmd_list:
                        cmd = run_cmd.format(cmdi)                    
                        run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)

                elif 'CentOS' in server.os:

                    cmd = run_cmd.format('yum install -y epel-release')
                    run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)

                    cmd = run_cmd.format('yum repolist')
                    run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)

                    if server.os == 'CentOS 7':
                        csync_rpm = 'https://github.com/mbaser/gluu/raw/master/csync2-2.0-3.gluu.centos7.x86_64.rpm'
                    if server.os == 'CentOS 6':
                        csync_rpm = 'https://github.com/mbaser/gluu/raw/master/csync2-2.0-3.gluu.centos6.x86_64.rpm'

                    cmd = run_cmd.format('yum install -y ' + csync_rpm)
                    run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)

                    cmd = run_cmd.format('service xinetd stop')
                    run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)

                if server.os == 'CentOS 6':
                    cmd = run_cmd.format('yum install -y crontabs')
                    run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)

                if server.os == 'RHEL 7':
                    #enable centos7 repo
                    centos7_repo = ('[centos]\n'
                                    'name=CentOS-7\n'
                                    'baseurl=http://ftp.heanet.ie/pub/centos/7/os/x86_64/\n'
                                    'enabled=1\n'
                                    'gpgcheck=1\n'
                                    'gpgkey=http://ftp.heanet.ie/pub/centos/7/os/x86_64/RPM-GPG-KEY-CentOS-7\n'
                                    )
                    
                    wlogger.log(tid, "Enabling CentOS 7 repository", 'debug', server_id=server.id)
                    repo_fn = os.path.join(chroot, 'etc/yum.repos.d/centos.repo')
                    c.put_file(repo_fn, centos7_repo)


                    cmd_list = ('yum repolist',
                                'yum install -y sqlite-devel xinetd gnutls librsync',
                                'yum install -y https://github.com/mbaser/gluu/raw/master/csync2-2.0-3.gluu.centos7.x86_64.rpm',
                                )
                    
                    for cmdi in cmd_list:
                        cmd = run_cmd.format(cmdi)
                        run_command(tid, c, cmd, cmd_chroot, no_error=None, server_id=server.id)
                    
                    

        if server.primary_server:

            key_command= [
                'csync2 -k /etc/csync2.key',
                'openssl genrsa -out /etc/csync2_ssl_key.pem 1024',
                'openssl req -batch -new -key /etc/csync2_ssl_key.pem -out '
                '/etc/csync2_ssl_cert.csr',
                'openssl x509 -req -days 3600 -in /etc/csync2_ssl_cert.csr '
                '-signkey /etc/csync2_ssl_key.pem -out /etc/csync2_ssl_cert.pem',
                ]

            for cmdi in key_command:
                cmd = run_cmd.format(cmdi)
                wlogger.log(tid, cmd, 'debug', server_id=server.id)
                run_command(tid, c, cmd, cmd_chroot, no_error=None,  server_id=server.id)


            csync2_config = get_csync2_config()

            remote_file = os.path.join(chroot, 'etc', 'csync2.cfg')

            wlogger.log(tid, "Uploading csync2.cfg", 'debug', server_id=server.id)

            c.put_file(remote_file,  csync2_config)


        else:
            wlogger.log(tid, "Downloading csync2.cfg, csync2.key, "
                        "csync2_ssl_cert.csr, csync2_ssl_cert.pem, and"
                        "csync2_ssl_key.pem from primary server and uploading",
                        'debug', server_id=server.id)

            down_list = ['csync2.cfg', 'csync2.key', 'csync2_ssl_cert.csr',
                    'csync2_ssl_cert.pem', 'csync2_ssl_key.pem']

            primary_server = Server.query.filter_by(primary_server=True).first()
            pc = RemoteClient(primary_server.hostname, ip=primary_server.ip)
            pc.startup()
            for f in down_list:
                remote = os.path.join(chroot, 'etc', f)
                local = os.path.join('/tmp',f)
                pc.download(remote, local)
                c.upload(local, remote)

            pc.close()

        csync2_path = '/usr/sbin/csync2'


        if 'Ubuntu' in server.os:

            wlogger.log(tid, "Enabling csync2 via inetd", server_id=server.id)

            fc = []
            inet_conf_file = os.path.join(chroot, 'etc','inetd.conf')
            r,f=c.get_file(inet_conf_file)
            csync_line = 'csync2\tstream\ttcp\tnowait\troot\t/usr/sbin/csync2\tcsync2 -i -l -N csync{}.gluu\n'.format(server.id) 
            csync_line_exists = False
            
            for l in f:
                
                if l.startswith('csync2'):
                    l = csync_line
                    csync_line_exists = True
                fc.append(l)
            if not csync_line_exists:
                fc.append(csync_line)
            fc=''.join(fc)
            c.put_file(inet_conf_file, fc)


            restart_inetd(tid, c, server)



        elif 'CentOS' in server.os or 'RHEL' in server.os:
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

            inet_conf_file = os.path.join(chroot, 'etc', 'xinetd.d', 'csync2')
            inetd_conf = inetd_conf % ({'HOSTNAME': 'csync{}.gluu'.format(server.id)})
            c.put_file(inet_conf_file, inetd_conf)

        #run time sync in every minute
        cron_file = os.path.join(chroot, 'etc', 'cron.d', 'csync2')
        c.put_file(cron_file,
            '{}-59/2 * * * *    root    {} -N csync{}.gluu -xvv 2>/var/log/csync2.log\n'.format(
            server_counter, csync2_path, server.id))

        server_counter += 1
        
        wlogger.log(tid, 'Crontab entry was created to sync files in every minute',
                         'debug', server_id=server.id)


        cmd = run_cmd.format('service crond restart')
        if ('CentOS' in server.os) or ('RHEL' in server.os):
            restart_inetd(tid, c, server)
            run_command(tid, c, cmd, cmd_chroot, no_error='debug', server_id=server.id)
        else:
            cmd = run_cmd.format('service cron reload')
            run_command(tid, c, cmd, cmd_chroot, no_error='debug', server_id=server.id)

        c.close()

    return True

def remove_filesystem_replication_do(server, app_config, tid):

        installer = Installer(server, app_config.gluu_version, logger_tid=tid)
        if not installer.c:
            return False

        installer.run('rm -f /etc/cron.d/csync2')
        installer.run('rm -f /etc/csync2.cfg')

        if 'CentOS' in server.os or 'RHEL' in server.os :
            installer.run('rm /etc/xinetd.d/csync2')
            services = ['xinetd', 'crond']
            
        else:
            installer.run("sed 's/^csync/#&/' -i /etc/inetd.conf")
            services = ['openbsd-inetd', 'cron']
            
        for s in services:
            installer.run('service {} restart '.format(s))
            
        installer.run('rm /var/lib/csync2/*.*')

        return True


@celery.task(bind=True)
def remove_filesystem_replication(self):
    tid = self.request.id
    
    app_config = AppConfiguration.query.first()
    servers = Server.query.all()
    
    for server in servers:
        r = remove_filesystem_replication_do(server, app_config, tid)
        if not r:
            return r



def get_os_type(c):
    
    # 2. Linux Distribution of the server
    cin, cout, cerr = c.run("ls /etc/*release")
    files = cout.split()
    
    if files[0] == '/etc/alpine-release':
        return 'Alpine'

    cin, cout, cerr = c.run("cat "+files[0])

    if "Ubuntu" in cout and "14.04" in cout:
        return "Ubuntu 14"
    if "Ubuntu" in cout and "16.04" in cout:
        return "Ubuntu 16"
    if "Ubuntu" in cout and "18.04" in cout:
        return "Ubuntu 18"
    if "CentOS" in cout and "release 6." in cout:
        return "CentOS 6"
    if "CentOS" in cout and "release 7." in cout:
        return "CentOS 7"
    if 'Red Hat Enterprise Linux' in cout and '7.':
        return 'RHEL 7'
    if 'Debian' in cout and "(jessie)" in cout:
        return 'Debian 8'
    if 'Debian' in cout and "(stretch)" in cout:
        return 'Debian 9'

def check_gluu_installation(c):
    """Checks if gluu server is installed

    Args:
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
    """
    appconf = AppConfiguration.query.first()
    check_file = ('/opt/gluu-server-{}/install/community-edition-setup/'
                  'setup.properties.last').format(
                                                appconf.gluu_version
                                            )
    result = c.exists(check_file)

    return result


@celery.task
def collect_server_details(server_id):
    print "Start collecting server details task"
    server = Server.query.get(server_id)
    appconf = AppConfiguration.query.first()
    c = RemoteClient(server.hostname, ip=server.ip)
    #try:
    c.startup()
    #except:
    #    return

    # 0. Make sure it is a Gluu Server
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    if not c.exists(chdir):
        server.gluu_server = False
        chdir = '/'

    # 1. The components installed in the server
    components = {
        'oxAuth': 'opt/gluu/jetty/oxauth',
        'oxTrust': 'opt/gluu/jetty/identity',
        'Shibboleth': 'opt/shibboleth-idp',
        'oxAuthRP': 'opt/gluu/jetty/oxauth-rp',
        'Passport': 'opt/gluu/node/passport',
    }
    installed = []
    for component, marker in components.iteritems():
        marker = os.path.join(chdir, marker)
        if c.exists(marker):
            installed.append(component)
    server.components = ",".join(installed)

    server.os = get_os_type(c)
    server.gluu_server = check_gluu_installation(c)

    db.session.commit()


def import_key(suffix, hostname, gluu_version, tid, c, sos):
    """Imports key for identity server

    Args:
        suffix (string): suffix of the key to be imported
        hostname (string): hostname of server
        gluu_version (string): version of installed gluu server
        tid (string): id of the task running the command

        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        sos: how to specify logger type
    """
    defaultTrustStorePW = 'changeit'
    defaultTrustStoreFN = '/opt/jre/jre/lib/security/cacerts'
    certFolder = '/etc/certs'
    public_certificate = '%s/%s.crt' % (certFolder, suffix)
    cmd =' '.join([
                    '/opt/jre/bin/keytool', "-import", "-trustcacerts",
                    "-alias", "%s_%s" % (hostname, suffix),
                    "-file", public_certificate, "-keystore",
                    defaultTrustStoreFN,
                    "-storepass", defaultTrustStorePW, "-noprompt"
                    ])

    chroot = '/opt/gluu-server-{0}'.format(gluu_version)

    if sos in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        command = "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost '{0}'".format(cmd)
    else:
        command = 'chroot {0} /bin/bash -c "{1}"'.format(chroot,
                                                         cmd)

    cin, cout, cerr = c.run(command)
    wlogger.log(tid, cmd, 'debug')
    wlogger.log(tid, cout+cerr, 'debug')


def delete_key(suffix, hostname, gluu_version, tid, c, sos):
    """Delted key of identity server

    Args:
        suffix (string): suffix of the key to be imported
        hostname (string): hostname of server
        gluu_version (string): version of installed gluu server
        tid (string): id of the task running the command

        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        sos: how to specify logger type
    """
    defaultTrustStorePW = 'changeit'
    defaultTrustStoreFN = '/opt/jre/jre/lib/security/cacerts'
    chroot = '/opt/gluu-server-{0}'.format(gluu_version)
    cert = "etc/certs/%s.crt" % (suffix)
    if c.exists(os.path.join(chroot, cert)):
        cmd=' '.join([
                        '/opt/jre/bin/keytool', "-delete", "-alias",
                        "%s_%s" % (hostname, suffix),
                        "-keystore", defaultTrustStoreFN,
                        "-storepass", defaultTrustStorePW
                        ])

        if sos in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
            command = "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost '{0}'".format(cmd)
        else:
            command = 'chroot {0} /bin/bash -c "{1}"'.format(chroot,
                                                         cmd)
        cin, cout, cerr = c.run(command)
        wlogger.log(tid, cmd, 'debug')
        wlogger.log(tid, cout+cerr, 'debug')


def modify_hosts(tid, c, hosts, chroot='/', server_host=None, server_id=''):
    wlogger.log(tid, "Modifying /etc/hosts", server_id=server_id)
    
    h_file = os.path.join(chroot,'etc/hosts')
    
    r, old_hosts = c.get_file(h_file)
    
    if r:
        new_hosts = modify_etc_hosts(hosts, old_hosts)
        c.put_file(h_file, new_hosts)
        wlogger.log(tid, "{} was modified".format(h_file), 'success', server_id=server_id)
    else:
        wlogger.log(tid, "Can't receive {}".format(h_file), 'fail', server_id=server_id)


    if chroot:

        h_file = os.path.join(chroot, 'etc/hosts')
        
        r, old_hosts = c.get_file(h_file)
        
        #for host in hosts:
        #    if host[0] == server_host:
        #        hosts.remove(host)
        #        break
        
        if r:
            new_hosts = modify_etc_hosts(hosts, old_hosts)
            c.put_file(h_file, new_hosts)
            wlogger.log(tid, "{} was modified".format(h_file), 'success', server_id=server_id)
        else:
            wlogger.log(tid, "Can't receive {}".format(h_file), 'fail', server_id=server_id)


def download_and_upload_custom_schema(tid, pc, c, ldap_type, gluu_server):
    """Downloads custom ldap schema from primary server and 
        uploads to current server represented by c
    Args:
        tid (string): id of the task running the command,
        pc (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication, representing primary server

        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication, representing current server
        ldap_type (string): type of ldapserver, either opendj
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
        ldap_type (string): type of ldapserver, either opendj
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
                                                            
                                                            
def makeOpenDjListenIpAddr(tid, c, cmd_chroot, run_cmd, server, ip_addr='0.0.0.0'):

    appconf = AppConfiguration.query.first()

    wlogger.log(tid, "Making openDJ listens all interfaces for port 4444 and 1636")

    cmd = "sed -i 's/dsreplication.java-args=-Xms8m -client/dsreplication.java-args=-Xms8m -client -Dcom.sun.jndi.ldap.object.disableEndpointIdentification=true/g' /opt/gluu-server-{}/opt/opendj/config/java.properties".format(appconf.gluu_version)

    run_command(tid, c, cmd)

    opendj_commands = [
            "/opt/opendj/bin/dsjavaproperties",
            "OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsconfig -h localhost -p 4444 -D \\\'cn=directory manager\\\' -w \\\'{}\\\' -n set-administration-connector-prop  --set listen-address:{} -X".format(server.ldap_password, ip_addr),
            "OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsconfig -h localhost -p 4444 -D \\\'cn=directory manager\\\' -w \\\'{}\\\' -n set-connection-handler-prop --handler-name \\\'LDAPS Connection Handler\\\' --set enabled:true --set listen-address:{} -X".format(server.ldap_password, ip_addr),
            ]

    if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        opendj_commands.append('systemctl stop opendj')
        opendj_commands.append('systemctl start opendj')
    else:
        opendj_commands.append('/etc/init.d/opendj stop')
        opendj_commands.append('/etc/init.d/opendj start')
    
    for command in opendj_commands:
        #if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        #    command = command.replace('\\\"',"'")
        cmd = run_cmd.format(command)
        run_command(tid, c, cmd, cmd_chroot)

def checkOfflineRequirements(tid, server, c, appconf):
    os_type, os_version = server.os.split()

    wlogger.log(tid, "Checking if dependencies were installed")

    
    
    
    #Check if archive type and os type matches
    if os_type.lower() in ('ubuntu', 'debian'):
        if not appconf.gluu_archive.endswith('.deb'):
            wlogger.log(tid,
                    "Os type does not match gluu archive type", 'error')
            return False
    elif os_type.lower() in ('centos', 'rhel'):
        if not appconf.gluu_archive.endswith('.rpm'):
            wlogger.log(tid,
                    "Os type does not match gluu archive type", 'error')
            return False

        
    wlogger.log(tid,
                    "Os type matches with gluu archive", 'success')

    #Determine gluu version
    a_path, a_fname = os.path.split(appconf.gluu_archive)
    m=re.search('gluu-server-(?P<gluu_version>(\d+).(\d+).(\d+)(\.\d+)?)',a_fname)
    if m:
        gv = m.group('gluu_version')
        appconf.gluu_version = gv
        db.session.commit()
        wlogger.log(
            tid,
            "Gluu version was determined as {0} from gluu archive".format(gv),
            'success'
            )
    else:
        wlogger.log(tid,
                    "Gluu version could not be determined from gluu archive", 
                    'error')
        return False


    #Check if python is installed
    
    if c.exists('/usr/bin/python'):
        wlogger.log(tid, "Python was installed",'success')
    else:
        wlogger.log(
            tid, 
            'python was not installed. Please install python on the host '
            'system (outside of the container) and retry.', 
            'error'
            )
        return False


    #Check if ntp was installed
    if c.exists('/usr/sbin/ntpdate'):
        wlogger.log(tid, "ntpdate was installed", 'success')
    else:
        wlogger.log(
            tid, 
            'ntpdate was not installed. Please install ntpdate on the host '
            'system (outside of the container) and retry.', 
            'error'
            )
        return False
        
    #Check if stunnel was installed
    if c.exists('/usr/bin/stunnel') or c.exists('/bin/stunnel'):
        wlogger.log(tid, "stunnel was installed", 'success')
    else:
        wlogger.log(
            tid, 
            'stunnel was not installed. Please install stunnel on the host '
            'system (outside of the container) and retry.', 
            'error'
            )
        return False
        
    
    return True

@celery.task(bind=True)
def installGluuServer(self, server_id):
    """Install Gluu server

    Args:
        server_id: id of server to be installed
    """

    tid = self.request.id
    server = Server.query.get(server_id)


    if not server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18','Ubuntu 16', 'Debian 9'):
        wlogger.log(tid, "Unsopported OS type", "error")
        return False
    

    pserver = Server.query.filter_by(primary_server=True).first()

    appconf = AppConfiguration.query.first()

    c = RemoteClient(server.hostname, ip=server.ip)

    try:
        c.startup()
    except:
        wlogger.log(tid, "Can't establish SSH connection",'fail')
        wlogger.log(tid, "Ending server installation process.", "error")
        return


    run_cmd, cmd_chroot = get_run_cmd(server)


    if appconf.offline:
        if not checkOfflineRequirements(tid, server, c, appconf):
            return False


    #setup properties file path
    setup_properties_file = os.path.join(Config.DATA_DIR, 'setup.properties')

    setup_prop = get_setup_properties()

    gluu_server = 'gluu-server-' + appconf.gluu_version

    

    #If os type of this server was not idientified, return to home
    if not server.os:
        wlogger.log(tid, "OS type has not been identified.", 'fail')
        wlogger.log(tid, "Ending server installation process.", "error")
        return


    #If this is not primary server, we will download setup.properties file from
    #primary server
    if not server.primary_server:
        wlogger.log(tid, "Check if Primary Server is Installed")

        if not server.os == pserver.os:
            wlogger.log(tid, "OS type is not the same as primary server.", 'fail')
            wlogger.log(tid, "Ending server installation process.", "error")
            return False

        pc = RemoteClient(pserver.hostname, ip=pserver.ip)

        try:
            pc.startup()
        except:
            wlogger.log(tid, "Can't make SSH connection to "
                             "primary server: ".format(
                             pserver.hostname), 'error')
            wlogger.log(tid, "Ending server installation process.", "error")
            return


        if check_gluu_installation(pc):
            wlogger.log(tid, "Primary Server is Installed",'success')
        else:
            wlogger.log(tid, "Primary Server is not Installed. "
                             "Please first install Primary Server",'fail')
            wlogger.log(tid, "Ending server installation process.", "error")
            return


    wlogger.log(tid, "Preparing for Installation")

    start_command  = 'service gluu-server-{0} start'
    stop_command   = 'service gluu-server-{0} stop'
    enable_command = None



    if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        enable_command  = '/sbin/gluu-serverd-{0} enable'
        stop_command    = '/sbin/gluu-serverd-{0} stop'
        start_command   = '/sbin/gluu-serverd-{0} start'


    if appconf.offline:
        gluu_archive_fn = os.path.split(appconf.gluu_archive)[1]
        wlogger.log(tid, "Uploading {}".format(gluu_archive_fn))
        
        cmd = 'scp {} root@{}:/root'.format(appconf.gluu_archive, server.hostname)
        
        wlogger.log(tid, cmd,'debug')
        
        os.system(cmd)

        if ('Ubuntu' in server.os) or ('Debian' in server.os):
            install_command = 'dpkg -i /root/{}'.format(gluu_archive_fn)
        else:
            install_command = 'rpm -i /root/{}'.format(gluu_archive_fn)
    else:


        #check if curl exists on the system
        cmd = 'which curl'
        result = c.run(cmd)
        
        if not 'curl' in result[1]:
            curlexist = False
        else:
            curlexist = True


        #add gluu server repo and imports signatures
        if ('Ubuntu' in server.os) or ('Debian' in server.os):

            if server.os == 'Ubuntu 16':
                dist = 'xenial'
            elif server.os == 'Ubuntu 18':
                dist = 'bionic'


            if not curlexist:
                cmd = 'DEBIAN_FRONTEND=noninteractive apt-get update'
                run_command(tid, c, cmd, no_error='debug')
                cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y curl"
                run_command(tid, c, cmd, no_error='debug')


            if 'Ubuntu' in server.os:
                cmd = 'curl https://repo.gluu.org/ubuntu/gluu-apt.key | apt-key add -'
            elif 'Debian' in server.os:
                cmd = 'curl https://repo.gluu.org/debian/gluu-apt.key | apt-key add -'

            run_command(tid, c, cmd, no_error='debug')

            if 'Ubuntu' in server.os:
                cmd = ('echo "deb https://repo.gluu.org/ubuntu/ {0} main" '
                   '> /etc/apt/sources.list.d/gluu-repo.list'.format(dist))
                   
                #Testing
                cmd = ('echo "deb https://repo.gluu.org/ubuntu/ {0}-devel main" '
                   '> /etc/apt/sources.list.d/gluu-repo.list'.format(dist))

            elif 'Debian' in server.os:
                cmd = ('echo "deb https://repo.gluu.org/debian/ stable main" '
                   '> /etc/apt/sources.list.d/gluu-repo.list')

            run_command(tid, c, cmd)

            install_command = 'DEBIAN_FRONTEND=noninteractive apt-get '

            cmd = 'DEBIAN_FRONTEND=noninteractive apt-get update'
            wlogger.log(tid, cmd, 'debug')
            cin, cout, cerr = c.run(cmd)
            wlogger.log(tid, cout+'\n'+cerr, 'debug')

            if 'dpkg --configure -a' in cerr:
                cmd = 'dpkg --configure -a'
                wlogger.log(tid, cmd, 'debug')
                cin, cout, cerr = c.run(cmd)
                wlogger.log(tid, cout+'\n'+cerr, 'debug')


        elif 'CentOS' in server.os or 'RHEL' in server.os:
            install_command = 'yum '


            if not curlexist:
                cmd = "yum install -y curl"
                run_command(tid, c, cmd, no_error='debug')

            qury_package = 'yum list installed | grep gluu-server-'

            if not c.exists('/usr/bin/wget'):
                cmd = install_command +'install -y wget'
                run_command(tid, c, cmd, no_error='debug')

            if server.os == 'CentOS 6':
                cmd = 'wget https://repo.gluu.org/centos/Gluu-centos6.repo -O /etc/yum.repos.d/Gluu.repo'
                
            elif server.os == 'CentOS 7':
                cmd = 'wget https://repo.gluu.org/centos/Gluu-centos7.repo -O /etc/yum.repos.d/Gluu.repo'
                
            elif server.os == 'RHEL 7':
                cmd = 'wget https://repo.gluu.org/rhel/Gluu-rhel7.repo -O /etc/yum.repos.d/Gluu.repo'

            run_command(tid, c, cmd, no_error='debug')

            cmd = 'wget https://repo.gluu.org/centos/RPM-GPG-KEY-GLUU -O /etc/pki/rpm-gpg/RPM-GPG-KEY-GLUU'
            run_command(tid, c, cmd, no_error='debug')

            cmd = 'rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-GLUU'
            run_command(tid, c, cmd, no_error='debug')

            cmd = 'yum clean all'
            run_command(tid, c, cmd, no_error='debug')


    if not c.exists('/usr/bin/python'):
        if 'Ubuntu' in server.os or 'Debian' in server.os:
            cmd = 'DEBIAN_FRONTEND=noninteractive apt-get install -y python'
        else:
            cmd = 'yum install -y python'
        run_command(tid, c, cmd, no_error='debug')



    wlogger.log(tid, "Check if Gluu Server was installed")

    gluu_installed = False

    #Determine if a version of gluu server was installed.
    r = c.listdir("/opt")
    if r[0]:
        for s in r[1]:
            m=re.search('gluu-server-(?P<gluu_version>(\d+).(\d+).(\d+)(.\d+)?)$',s)
            if m:
                gluu_version = m.group("gluu_version")
                gluu_installed = True
                cmd = stop_command.format(gluu_version)
                rs = run_command(tid, c, cmd, no_error='debug')

                #If gluu server is installed, first stop it then remove
                if "Can't stop gluu server" in rs:
                    cmd = 'rm -f /var/run/{0}.pid'.format(gluu_server)
                    run_command(tid, c, cmd, no_error='debug')

                    cmd = "df -aP | grep %s | awk '{print $6}' | xargs -I {} umount -l {}" % (gluu_server)
                    run_command(tid, c, cmd, no_error='debug')

                    cmd = stop_command.format(gluu_version)
                    rs = run_command(tid, c, cmd, no_error='debug')


                if appconf.offline:
                    if ('Ubuntu' in server.os) or ('Debian' in server.os):
                        cmd = 'apt-get remove -y ' + s
                    else:
                        cmd = 'rpm -e ' + s
                else:
                    cmd = install_command + "remove -y "+s
                        
                run_command(tid, c,cmd)


    if not gluu_installed:
        wlogger.log(tid, "Gluu Server was not previously installed", "debug")


    #start installing gluu server
    wlogger.log(tid, "Installing Gluu Server: " + gluu_server)


    if appconf.offline:
        cmd = install_command 
    else:
        cmd = install_command + 'install -y ' + gluu_server
    wlogger.log(tid, cmd, "debug")
    
    
    c.log_me("running command: {}".format(cmd))
    
    channel = c.client.get_transport().open_session()
    channel.get_pty()
    channel.exec_command(cmd)
    
    ubuntu_re = re.compile('\[(\s|\w|%|/|-|\.)*\]')
    ubuntu_re_2 = re.compile('\(Reading database ... \d*')
    centos_re = re.compile(' \[(=|-|#|\s)*\] ')
    
    last_debug = False
    log_id = 0
    while True:
        if channel.exit_status_ready():
            break
        rl = ''
        try:
            rl, wl, xl = select.select([channel], [], [], 0.0)
        except:
            pass
        if len(rl) > 0:
            coutt = channel.recv(1024)
            if coutt:
                for cout in coutt.split('\n'):
                    if cout.strip():
                        if centos_re.search(cout) or ubuntu_re.search(cout) or ubuntu_re_2.search(cout):
                            if not last_debug:
                                cout = cout.strip()
                                wlogger.log(tid, "...", "debug", log_id="logc-{}".format(log_id), new_log_id=True)
                                last_debug = True

                            wlogger.log(tid, cout, "debugc", log_id="logc-{}".format(log_id))

                        else:
                            log_id += 1
                            last_debug = False
                            wlogger.log(tid, cout, "debug")


    if enable_command:
        run_command(tid, c, enable_command.format(appconf.gluu_version), no_error='debug')

    run_command(tid, c, start_command.format(appconf.gluu_version))

    #Since we will make ssh inot centos container, we need to wait ssh server to
    #be started properly
    if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        wlogger.log(tid, "Sleeping 10 secs to wait for gluu server start properly.")
        time.sleep(10)


    if setup_prop.get('opendj_type') == 'wrends':
        cmd = 'wget https://ox.gluu.org/maven/org/forgerock/opendj/opendj-server-legacy/4.0.0-M3/opendj-server-legacy-4.0.0-M3.zip -P /opt/{}/opt/dist/app'.format(gluu_server)
        run_command(tid, c, cmd, no_error='debug')
        
    

    # If this server is primary, upload local setup.properties to server
    if server.primary_server:
        wlogger.log(tid, "Uploading setup.properties")
        r = c.upload(setup_properties_file, '/opt/{}/install/community-edition-setup/setup.properties'.format(gluu_server))
    # If this server is not primary, get setup.properties.last from primary
    # server and upload to this server
    else:
        #this is not primary server, so download setup.properties.last
        #from primary server and upload to this server
        pc = RemoteClient(pserver.hostname, ip=pserver.ip)
        try:
            pc.startup()
        except:
            wlogger.log(tid, "Can't establish SSH connection to primary server: ".format(pserver.hostname), 'error')
            wlogger.log(tid, "Ending server installation process.", "error")
            return


        # ldap_paswwrod of this server should be the same with primary server
        ldap_passwd = None


        remote_file = '/opt/{}/install/community-edition-setup/setup.properties.last'.format(gluu_server)
        wlogger.log(tid, 'Downloading setup.properties.last from primary server', 'debug')

       #get setup.properties.last from primary server.
        r=pc.get_file(remote_file)
        if r[0]:
            new_setup_properties=''
            setup_properties = r[1].readlines()
            #replace ip with address of this server
            for l in setup_properties:
                if l.startswith('ip='):
                    l = 'ip={0}\n'.format(server.ip)
                elif l.startswith('ldapPass='):
                    ldap_passwd = l.split('=')[1].strip()
                elif l.startswith('hostname='):
                    l = 'hostname={0}\n'.format(appconf.nginx_host)
                elif l.startswith('os_type=') or l.startswith('os_initdaemon=') or l.startswith('rsyslogUbuntuInitFile'):
                    l = ''
                new_setup_properties += l

            #put setup.properties to server
            remote_file_new = '/opt/{}/install/community-edition-setup/setup.properties'.format(gluu_server)
            wlogger.log(tid, 'Uploading setup.properties', 'debug')
            c.put_file(remote_file_new,  new_setup_properties)

            if ldap_passwd:
                server.ldap_password = ldap_passwd
        else:
            wlogger.log(tid, "Can't download setup.properties.last from primary server", 'fail')
            wlogger.log(tid, "Ending server installation process.", "error")
            return



    #run setup.py on the server

    if appconf.gluu_version < '3.1.3':
        wlogger.log(tid, "Downloading setup.py")
        cmd = ( 
                'curl  https://raw.githubusercontent.com/GluuFederation/'
                'community-edition-setup/master/setup.py  -o /opt/{}/install/'
                'community-edition-setup/setup.py'
                ).format(gluu_server)
                
        cmd = ( 
                'curl https://raw.githubusercontent.com/mbaser/gluu/master/setup.py -o /opt/{}/install/'
                'community-edition-setup/setup.py'
                ).format(gluu_server)

        
        
        run_command(tid, c, cmd, no_error='debug')
        
        cmd = 'chmod +x /opt/{}/install/community-edition-setup/setup.py'.format(
            gluu_server)
        run_command(tid, c, cmd)
    
    if not server.primary_server:
        setup_py = os.path.join(app.root_path,'setup', 'setup_{}.py'.format(appconf.gluu_version.replace('.','_')))
        remote_py = '/opt/{}/install/community-edition-setup/setup.py'.format(gluu_server)
        wlogger.log(tid, "Uploading setup.py",'debug')
        c.upload(setup_py, remote_py)
        c.run('chmod +x ' + remote_py)
        
    
    #run setup.py on the server
    wlogger.log(tid, "Running setup.py - Be patient this process will take a while ...")


    if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        cmd = run_cmd.format('cd /install/community-edition-setup/ && ./setup.py -n -v %s')
    else:
        cmd = 'chroot /opt/{} /bin/bash -c "cd /install/community-edition-setup/ && ./setup.py -n -v %s"'.format(gluu_server)

    if not server.primary_server:
        cmd = cmd % ' --empty-ldap'
    else:
        cmd = cmd % ''


    wlogger.log(tid ,cmd, "debug")

    c.log_me("running command: {}".format(cmd))

    channel = c.client.get_transport().open_session()
    channel.get_pty()
    channel.exec_command(cmd)
    
    last_debug = False

    while True:
        if channel.exit_status_ready():
            break
        rl = ''
        try:
            rl, wl, xl = select.select([channel], [], [], 0.0)
        except:
            pass

        if len(rl) > 0:
            cout = channel.recv(1024)
            
            if re.search(' \[(#|\s)*\] ', cout):
                if not last_debug:
                    cout = cout.strip()
                    wlogger.log(tid, "...", "debug", log_id="logc-{}".format(log_id), new_log_id=True)
                    last_debug = True

                wlogger.log(tid, cout, "debugc", log_id="logc-{}".format(log_id))
            else:
                log_id += 1
                last_debug = False
                cout = cout.strip()
                if cout:
                    wlogger.log(tid, cout, "debug")

    
    if appconf.modify_hosts:
        all_server = Server.query.all()
        
        host_ip = []
        
        for ship in all_server:
            host_ip.append((ship.hostname, ship.ip))

        modify_hosts(tid, c, host_ip, '/opt/'+gluu_server+'/', server.hostname)


    if appconf.gluu_version >= '3.1.4':
        #make opendj listen all interfaces
        makeOpenDjListenIpAddr(tid, c, cmd_chroot, run_cmd, server)

    # Get certificates from primary server and upload this server
    if not server.primary_server:

        #If gluu version is greater than 3.0.2 we need to download certificates
        #from primary server and upload to this server, then will delete and
        #import keys
        if appconf.gluu_version > '3.0.2':
            wlogger.log(tid, "Downloading certificates from primary "
                             "server and uploading to this server")
            certs_remote_tmp = "/tmp/certs_"+str(uuid.uuid4())[:4].upper()+".tgz"
            certs_local_tmp = "/tmp/certs_"+str(uuid.uuid4())[:4].upper()+".tgz"

            cmd = ('tar -zcf {0} /opt/gluu-server-{1}/etc/certs/ '
                    '/opt/gluu-server-{1}/install/community-edition-setup'
                    '/output/scim-rp.jks '
                    '/opt/gluu-server-{1}'
                    '/etc/gluu/conf/passport-config.json'
                    ).format(certs_remote_tmp, appconf.gluu_version)
            wlogger.log(tid,cmd,'debug')
            cin, cout, cerr = pc.run(cmd)
            wlogger.log(tid, cout+cerr, 'debug')
            wlogger.log(tid,cmd,'debug')

            r = pc.download(certs_remote_tmp, certs_local_tmp)
            if 'Download successful' in r :
                wlogger.log(tid, r,'success')
            else:
                wlogger.log(tid, r,'error')

            r = c.upload(certs_local_tmp, "/tmp/certs.tgz")

            if 'Upload successful' in r:
                wlogger.log(tid, r,'success')
            else:
                wlogger.log(tid, r,'error')

            cmd = ('cp -r /opt/gluu-server-{0}/etc/certs /opt/gluu-server-{0}/etc/certs.back'.format(appconf.gluu_version))
            run_command(tid, c, cmd)

            cmd = 'tar -zxf /tmp/certs.tgz -C /'
            run_command(tid, c, cmd)

            #delete old keys and import new ones
            wlogger.log(tid, 'Manuplating keys')
            for suffix in (
                    'httpd',
                    'shibIDP',
                    'idp-encryption',
                    'asimba',
                    setup_prop['ldap_type'],
                    ):
                delete_key(suffix, appconf.nginx_host, appconf.gluu_version,
                            tid, c, server.os)
                import_key(suffix, appconf.nginx_host, appconf.gluu_version,
                            tid, c, server.os)
        else:
            download_and_upload_custom_schema(  
                                                tid, pc, c, 
                                                'opendj', gluu_server
                                            )
    else:
        #this is primary server so we need to upload local custom schemas if any
        upload_custom_schema(tid, c, 
                            setup_prop['ldap_type'], gluu_server)

    #ntp is required for time sync, since ldap replication will be
    #done by time stamp. If not isntalled, install and configure crontab

    if c.exists('/usr/sbin/ntpdate'):
        wlogger.log(tid, "ntp was installed", 'success')
    else:

        cmd = install_command + 'install -y ntpdate'
        run_command(tid, c, cmd)

    #run time sync an every minute
    c.put_file('/etc/cron.d/setdate',
                '* * * * *    root    /usr/sbin/ntpdate -s time.nist.gov\n')
    wlogger.log(tid, 'Crontab entry was created to update time in every minute',
                     'debug')

    if 'CentOS' in server.os or 'RHEL' in server.os:
        cmd = 'service crond reload'
    else:
        cmd = 'service cron reload'

    run_command(tid, c, cmd, exclude_error="Redirecting to /bin/systemctl reload crond.service")

    #We need to fix opendj initscript
    wlogger.log(tid, 'Uploading fixed opendj init.d script')
    opendj_init_script = os.path.join(app.root_path, "templates",
                           "opendj", "opendj")
    #remote_opendj_init_script = '/opt/{0}/etc/init.d/opendj'.format(gluu_server)
    #c.upload(opendj_init_script, remote_opendj_init_script)
    #cmd = 'chmod +x {}'.format(remote_opendj_init_script)
    run_command(tid, c, cmd)
    #########

    if appconf.gluu_version == '3.1.6':
        #fix oxauth.war for openid connect session
        wlogger.log(tid, "Fixing oxauth.war for OpenId connect session")
        rcmd, cmdchr = get_run_cmd(server)
        cmd_list = [
                '/opt/jre/bin/jar -xf /opt/gluu/jetty/oxauth/webapps/oxauth.war WEB-INF/incl/layout/authorize-template.xhtml',
                'sed \\\'s/<f:view locale="#{language.localeCode}">/<f:view transient="true" locale="#{language.localeCode}">/\\\' -i WEB-INF/incl/layout/authorize-template.xhtml',
                '/opt/jre/bin/jar -uf /opt/gluu/jetty/oxauth/webapps/oxauth.war WEB-INF/incl/layout/authorize-template.xhtml',
                ]

        for cmd in cmd_list:
            run_command(tid, c, run_cmd.format(cmd), cmd_chroot)

    server.gluu_server = True
    db.session.commit()
    wlogger.log(tid, "Gluu Server successfully installed")


def do_disable_replication(tid, server, primary_server, app_config):


    c = RemoteClient(primary_server.hostname, ip=primary_server.ip)



    cmd_run, cmd_chroot = get_run_cmd(server)

    wlogger.log(tid, 
        "Disabling replication for {0}".format(
        server.hostname)
        )

    wlogger.log(tid, 
            "Making SSH connection to primary server {0}".format(
            primary_server.hostname), 'debug'
            )

    try:
        c.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection {0}".format(e), "warning")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False

    wlogger.log(tid, "SSH connection successful", 'success')

    cmd = ('/opt/opendj/bin/dsreplication disable --disableAll --port 4444 '
            '--hostname {} --adminUID admin --adminPassword \\\'{}\\\' '
            '--trustAll --no-prompt').format(
                            server.hostname,
                            app_config.replication_pw)

    cmd = cmd_run.format(cmd)
    run_command(tid, c, cmd, cmd_chroot)

    server.mmr = False
    db.session.commit()

    configure_OxIDPAuthentication(tid, exclude=server.id)

    wlogger.log(tid, "Checking replication status", 'debug')

    cmd = ('OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsreplication status -n -X -h {} '
            '-p 1444 -I admin -w \\\'{}\\\'').format(
                    primary_server.hostname,
                    app_config.replication_pw)

    cmd = cmd_run.format(cmd)
    run_command(tid, c, cmd, cmd_chroot)

    return True

@celery.task(bind=True)
def opendj_disable_replication_task(self, server_id):
    server = Server.query.get(server_id)
    primary_server = Server.query.filter_by(primary_server=True).first()
    app_config = AppConfiguration.query.first()
    tid = self.request.id
    r = do_disable_replication(tid, server, primary_server, app_config)
    return r

@celery.task(bind=True)
def remove_server_from_cluster(self, server_id, remove_server=False, 
                                                disable_replication=True):

    app_config = AppConfiguration.query.first()
    primary_server = Server.query.filter_by(primary_server=True).first()
    server = Server.query.get(server_id)
    tid = self.request.id

    removed_server_hostname = server.hostname

    remove_filesystem_replication_do(server, app_config, tid)

    proxy_c = None

    if not app_config.external_load_balancer:
        proxy_c = RemoteClient(app_config.nginx_host, ip=app_config.nginx_ip)

        wlogger.log(tid, "Reconfiguring proxy server {}".format(
                                                            app_config.nginx_host))

        wlogger.log(tid,
                "Making SSH connection to load balancer {0}".format(
                app_config.nginx_host), 'debug'
                )

        try:
            proxy_c.startup()

            wlogger.log(tid, "SSH connection successful", 'success')

            # Update nginx
            nginx_config = make_nginx_proxy_conf(exception=server_id)
            remote = "/etc/nginx/nginx.conf"
            r = proxy_c.put_file(remote, nginx_config)
            
            if not r[0]:
                wlogger.log(tid, "An error occurred while uploadng nginx.conf.", "warning")

            wlogger.log(tid, "nginx configuration updated", 'success')
            wlogger.log(tid, "Restarting nginx", 'debug')
            run_command(tid, proxy_c, 'service nginx restart', no_error='warning')

            wlogger.log(tid, "Proxy server configuration were not updated", 'success')


        except Exception as e:
            wlogger.log(
                tid, "Cannot establish SSH connection {0}".format(e), "warning")
            wlogger.log(tid, "Proxy server configuration were not updated", "warning")

        if not proxy_c and not app_config.use_ldap_cache:
            
            proxy_c = RemoteClient(app_config.cache_host, ip=app_config.cache_ip)
            
            wlogger.log(tid,
                    "Making SSH connection to cache server {0}".format(
                    app_config.cache_host), 'debug'
                    )

            try:
                proxy_c.startup()
                # Update Twemproxy
                wlogger.log(tid, "Updating Twemproxy configuration",'debug')
                twemproxy_conf = make_twem_proxy_conf(exception=server_id)
                remote = "/etc/nutcracker/nutcracker.yml"
                r = proxy_c.put_file(remote, twemproxy_conf)

                if not r[0]:
                    wlogger.log(tid, "An error occurred while uploading nutcracker.yml.", "warning")

                wlogger.log(tid, "Twemproxy configuration updated", 'success')

                run_command(tid, proxy_c, 'service nutcracker restart', no_error='warning')

                # Update stunnel
                proxy_stunnel_conf = make_proxy_stunnel_conf(exception=server_id)
                proxy_stunnel_conf = '\n'.join(proxy_stunnel_conf)
                remote = '/etc/stunnel/stunnel.conf'
                r = proxy_c.put_file(remote, proxy_stunnel_conf)

                if not r[0]:
                    wlogger.log(tid, "An error occurred while uploadng stunnel.conf.", "warning")

                wlogger.log(tid, "Stunnel configuration updated", 'success')



                os_type = get_os_type(proxy_c)

                if 'CentOS' or 'RHEL' in os_type:
                    run_command(tid, proxy_c, 'systemctl restart stunnel', no_error='warning')
                else:
                    run_command(tid, proxy_c, 'service stunnel4 restart', no_error='warning')

                proxy_c.close()

            except Exception as e:
                wlogger.log(
                    tid, "Cannot establish SSH connection {0}".format(e), "warning")
                wlogger.log(tid, "Proxy server configuration were not updated", "warning")


    if disable_replication:
        r = do_disable_replication(tid, server, primary_server, app_config)
        if not r:
            wlogger.log(tid, "An error occurred while disabling replication", "warning")


    if remove_server:
        db.session.delete(server)


    chroot = '/opt/gluu-server-' + app_config.gluu_version

    for server in Server.query.all():
        if server.gluu_server:
        
            if server.os == 'CentOS 7' or server.os == 'RHEL 7':
                restart_command = '/sbin/gluu-serverd-{0} restart'.format(
                                    app_config.gluu_version)
            else:
                restart_command = '/etc/init.d/gluu-server-{0} restart'.format(
                                    app_config.gluu_version)


            wlogger.log(tid, "Making SSH connection to the server %s" %
                    server.hostname)

            ct = RemoteClient(server.hostname, ip=server.ip)

            try:
                ct.startup()
            except Exception as e:
                wlogger.log(
                    tid, "Cannot establish SSH connection {0}".format(e),
                    "warning")
                wlogger.log(tid, "Ending server setup process.", "warning")

            remote_file = os.path.join(chroot, 'etc', 'csync2.cfg')
            
            if ct.exists(remote_file):
                wlogger.log(tid, "Reconfiguring file system replication")
                csync2_config = get_csync2_config(exclude=removed_server_hostname)
                wlogger.log(tid, "Uploading csync2.cfg", 'debug')
                ct.put_file(remote_file,  csync2_config)

            wlogger.log(tid, "Restarting Gluu Server on {}".format(
                                server.hostname))

            run_command(tid, ct, restart_command, no_error='warning')

            ct.close()

    db.session.commit()
    return True


def configure_OxIDPAuthentication(tid, exclude=None):
    
    primary_server = Server.query.filter_by(primary_server=True).first()
    
    app_config = AppConfiguration.query.first()

    gluu_installed_servers = Server.query.filter_by(gluu_server=True).all()

    chroot_fs = '/opt/gluu-server-' + app_config.gluu_version

    pDict = {}

    for server in gluu_installed_servers:
        if server.mmr:
            laddr = server.ip if app_config.use_ip else server.hostname
            ox_auth = [ laddr+':1636' ]
            for prsrv in gluu_installed_servers:
                if prsrv.mmr:
                    if not prsrv == server:
                        laddr = prsrv.ip if app_config.use_ip else prsrv.hostname
                        ox_auth.append(laddr+':1636')
            pDict[server.hostname]= ','.join(ox_auth)


    for server in gluu_installed_servers:
        if server.mmr:
            ct = RemoteClient(server.hostname, ip=server.ip)
            try:
                ct.startup()
            except Exception as e:
                wlogger.log(
                    tid, "Cannot establish SSH connection {0}".format(e), "warning")
                wlogger.log(tid, "Ending server setup process.", "error")
            
            modifyOxLdapProperties(server, ct, tid, pDict, chroot_fs)

    oxIDP=['localhost:1636']

    for server in gluu_installed_servers:
        if not server.id == exclude:
            laddr = server.ip if app_config.use_ip else server.hostname
            oxIDP.append(laddr+':1636')

    adminOlc = LdapOLC('ldaps://{}:1636'.format(primary_server.hostname),
                        'cn=directory manager', primary_server.ldap_password)

    try:
        adminOlc.connect()
    except Exception as e:
        wlogger.log(
            tid, "Connection to LDAPserver as directory manager at port 1636"
            " has failed: {0}".format(e), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return


    if adminOlc.configureOxIDPAuthentication(oxIDP):
        wlogger.log(tid,
                'oxIDPAuthentication entry is modified to include all '
                'replicating servers',
                'success')
    else:
        wlogger.log(tid, 'Modifying oxIDPAuthentication entry is failed: {}'.format(
                adminOlc.conn.result['description']), 'success')


    if app_config.use_ldap_cache:
        adminOlc.changeOxCacheConfiguration('NATIVE_PERSISTENCE')
        wlogger.log(tid,
                'cacheProviderType entry is set to NATIVE_PERSISTENCE',
                'success')


@celery.task(bind=True)
def opendjenablereplication(self, server_id):

    primary_server = Server.query.filter_by(primary_server=True).first()
    tid = self.request.id
    app_config = AppConfiguration.query.first()

    gluu_installed_servers = Server.query.filter_by(gluu_server=True).all()

    if server_id == 'all':
        servers = Server.query.all()
    else:
        servers = [Server.query.get(server_id)]

    if not primary_server.gluu_server:
        chroot = '/'
    else:
        chroot = '/opt/gluu-server-' + app_config.gluu_version

    chroot_fs = '/opt/gluu-server-' + app_config.gluu_version

    wlogger.log(tid, "Making SSH connection to the primary server %s" %
                primary_server.hostname)

    c = RemoteClient(primary_server.hostname, ip=primary_server.ip)

    try:
        c.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection {0}".format(e), "warning")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False

    if primary_server.gluu_server:
        # check if remote is gluu server
        if c.exists(chroot):
            wlogger.log(tid, 'Checking if remote is gluu server', 'success')
        else:
            wlogger.log(tid, "Remote is not a gluu server.", "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False


    tmp_dir = os.path.join('/tmp', uuid.uuid1().hex[:12])
    os.mkdir(tmp_dir)

    wlogger.log(tid, "Downloading opendj certificates")

    opendj_cert_files = ('keystore', 'keystore.pin', 'truststore')

    for cf in opendj_cert_files:
        remote = os.path.join(chroot_fs, 'opt/opendj/config', cf)
        local = os.path.join(tmp_dir, cf)
        result = c.download(remote, local)
        if not result.startswith('Download successful'):
            wlogger.log(tid, result, "warning")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False

    primary_server_secured = False

    for server in servers:
        
        cmd_run, chroot =  get_run_cmd(server)
        
        if not server.primary_server:
            wlogger.log(tid, "Enabling replication on server {}".format(
                                                            server.hostname))
                                                            
            for base in ['gluu', 'site']:

                cmd = ('OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsreplication enable --host1 {} --port1 4444 '
                        '--bindDN1 \\\'cn=directory manager\\\' --bindPassword1 \\\'{}\\\' '
                        '--replicationPort1 8989 --host2 {} --port2 4444 --bindDN2 '
                        '\\\'cn=directory manager\\\' --bindPassword2 \\\'{}\\\' '
                        '--replicationPort2 8989 --adminUID admin --adminPassword \\\'{}\\\' '
                        '--baseDN \\\'o={}\\\' --trustAll -X -n').format(
                            primary_server.ip,
                            primary_server.ldap_password.replace("'","\\'"),
                            server.ip,
                            server.ldap_password.replace("'","\\'"),
                            app_config.replication_pw.replace("'","\\'"),
                            base,
                            )

                cmd = cmd_run.format(cmd)
                
                run_command(tid, c, cmd, chroot)


            if not primary_server_secured:

                wlogger.log(tid, "Securing replication on primary server {}".format(
                                                                primary_server.hostname))

                cmd = ('OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsconfig -h {} -p 4444 '
                        ' -D  \\\'cn=Directory Manager\\\' -w \\\'{}\\\' --trustAll '
                        '-n set-crypto-manager-prop --set ssl-encryption:true'
                        ).format(primary_server.ip, primary_server.ldap_password.replace("'","\\'"))

                cmd = cmd_run.format(cmd)
                run_command(tid, c, cmd, chroot)
                primary_server_secured = True
                primary_server.mmr = True

            wlogger.log(tid, "Securing replication on server {}".format(
                                                            server.hostname))
            cmd = ('OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsconfig -h {} -p 4444 '
                    ' -D  \\\'cn=Directory Manager\\\' -w \\\'{}\\\' --trustAll '
                    '-n set-crypto-manager-prop --set ssl-encryption:true'
                    ).format(server.ip, primary_server.ldap_password.replace("'","\\'"))

            cmd = cmd_run.format(cmd)
            run_command(tid, c, cmd, chroot)

        server.mmr = True


    db.session.commit()

    

    servers = Server.query.all()

    for server in servers:

        if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
            restart_command = '/sbin/gluu-serverd-{0} restart'.format(
                                app_config.gluu_version)
        else:
            restart_command = '/etc/init.d/gluu-server-{0} restart'.format(
                                app_config.gluu_version)


        wlogger.log(tid, "Making SSH connection to the server %s" %
                server.hostname)

        ct = RemoteClient(server.hostname, ip=server.ip)

        try:
            ct.startup()
        except Exception as e:
            wlogger.log(
                tid, "Cannot establish SSH connection {0}".format(e),
                "warning")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False


        for target in servers:

            if  target != server:

                for base in ['gluu', 'site']:
                    cmd = ('OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsreplication initialize --baseDN \\\'o={}\\\' '
                        '--adminUID admin --adminPassword \\\'{}\\\' '
                        '--hostSource {} --portSource 4444 '
                        '--hostDestination {} --portDestination 4444 '
                        '--trustAll --no-prompt').format(
                            base,
                            app_config.replication_pw.replace("'","\\'"),
                            target.ip,
                            server.ip,
                            )

                    cmd_run, cmd_chroot = get_run_cmd(server)

                    print "Sleeping 30 seconds"
                    time.sleep(30)

                    wlogger.log(tid, "Inıtializing replication on server {} for base {}".format(
                                                                        server.hostname, base))

                    cmd = cmd_run.format(cmd)
                    run_command(tid, c, cmd, cmd_chroot)
            

        if not server.primary_server:

            if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):

                print "Sleeping 30 seconds"
                time.sleep(30)

                print "Running second initialization on {}".format(ct.host)


                #sometimes we need re-imitialization
                cmd = ('OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsreplication initialize --adminUID admin '
                        '--adminPassword \\\'{}\\\' --baseDN o=gluu --hostSource {} '
                        '--portSource 4444 --hostDestination {} '
                        '--portDestination 4444 --trustAll --no-prompt').format(
                                app_config.replication_pw.replace("'","\\'"),
                                primary_server.ip,
                                server.ip,
                                )


                print "Init command", cmd


                cmd = cmd_run.format(cmd)
                run_command(tid, ct, cmd, chroot)

            wlogger.log(tid, "Uploading OpenDj certificate files")
            for cf in opendj_cert_files:


                remote = os.path.join(chroot_fs, 'opt/opendj/config', cf)
                local = os.path.join(tmp_dir, cf)

                result = ct.upload(local, remote)
                if not result:
                    wlogger.log(tid, "An error occurred while uploading OpenDj certificates.", "error")
                    return False

                if not result.startswith('Upload successful'):
                    wlogger.log(tid, result, "warning")
                    wlogger.log(tid, "Ending server setup process.", "error")
                    return False

        wlogger.log(tid, "Restarting Gluu Server on {}".format(
                            server.hostname))

        run_command(tid, ct, restart_command)

        ct.close()


    if server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        wlogger.log(tid, "Waiting for Gluu to finish starting")
        time.sleep(60)

    configure_OxIDPAuthentication(tid)

    wlogger.log(tid, "Checking replication status")

    cmd = ('OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsreplication status -n -X -h {} '
            '-p 1444 -I admin -w \'{}\'').format(
                    primary_server.ip,
                    app_config.replication_pw.replace("'","\\'"))

    cmd = cmd_run.format(cmd)
    run_command(tid, c, cmd, chroot)

    c.close()

    return True


@celery.task(bind=True)
def installNGINX(self, nginx_host):
    """Installs nginx load balancer

    Args:
        nginx_host: hostname of server on which we will install nginx
    """
    tid = self.request.id
    app_config = AppConfiguration.query.first()
    pserver = Server.query.filter_by(primary_server=True).first()
    wlogger.log(tid, "Making SSH connection to the server {}".format(
                                                                nginx_host))
    c = RemoteClient(nginx_host)

    try:
        c.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection {0}".format(e), "warning")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False

    # We should determine os type to install nginx
    wlogger.log(tid, "Determining OS type")
    os_type = get_os_type(c)
    wlogger.log(tid, "OS is determined as {0}".format(os_type),'debug')
    
    # write nginx os type to database
    app_config.nginx_os_type = os_type
    db.session.commit()

    wlogger.log(tid, "Checking if Python was installed",'debug')

    if not c.exists('/usr/bin/python'):
        
        if app_config.offline:
            wlogger.log(
            tid, 
            'python was not installed. Please install python and retry.', 
            'error'
            )
            return False
        
        if 'Ubuntu' in os_type or 'Debian' in os_type:
            cmd = 'DEBIAN_FRONTEND=noninteractive apt-get install -y python'
        else:
            cmd = 'yum install -y python'
        run_command(tid, c, cmd, no_error='debug')
    else:
        wlogger.log(tid, "Python was installed", 'success')


    #check if nginx was installed on this server
    wlogger.log(tid, "Check if NGINX installed")

    r = c.exists("/usr/sbin/nginx")

    if r:
        wlogger.log(tid, "nginx allready exists")
    else:
        
        if app_config.offline:
            wlogger.log(
            tid, 
            'nginx was not installed. Please install nginx and retry.', 
            'error'
            )
            return False
        
        
        #If this is centos we need to install epel-release
        if os_type in ('CentOS 7', 'RHEL 7'):
            run_command(tid, c, 'yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm')
            cmd = 'yum install -y nginx'
        else:
            run_command(tid, c, 'DEBIAN_FRONTEND=noninteractive apt-get update')
            cmd = 'DEBIAN_FRONTEND=noninteractive apt-get install -y nginx'

        wlogger.log(tid, cmd, 'debug')

        #FIXME: check cerr??
        cin, cout, cerr = c.run(cmd)
        wlogger.log(tid, cout, 'debug')

    #Check if ssl certificates directory exist on this server
    r = c.exists("/etc/nginx/ssl/")
    if not r:
        wlogger.log(tid, "/etc/nginx/ssl/ does not exists. Creating ...",
                            "debug")
        r2 = c.mkdir("/etc/nginx/ssl/")
        if r2[0]:
            wlogger.log(tid, "/etc/nginx/ssl/ was created", "success")
        else:
            wlogger.log(tid, "Error creating /etc/nginx/ssl/ {0}".format(r2[1]),
                            "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
    else:
        wlogger.log(tid, "Directory /etc/nginx/ssl/ exists.", "debug")

    # we need to download ssl certifiactes from primary server.
    wlogger.log(tid, "Making SSH connection to primary server {} for "
                     "downloading certificates".format(pserver.hostname))
    pc = RemoteClient(pserver.hostname, pserver.ip)
    try:
        pc.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection to primary server {0}".format(e), "warning")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False
    # get httpd.crt and httpd.key from primary server and put to this server
    for crt in ('httpd.crt', 'httpd.key'):
        wlogger.log(tid, "Downloading {0} from primary server".format(crt), "debug")
        remote_file = '/opt/gluu-server-{0}/etc/certs/{1}'.format(app_config.gluu_version, crt)
        r = pc.get_file(remote_file)
        if not r[0]:
            wlogger.log(tid, "Can't download {0} from primary server: {1}".format(crt,r[1]), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
        else:
            wlogger.log(tid, "File {} was downloaded.".format(remote_file), "success")
        fc = r[1].read()
        remote = os.path.join("/etc/nginx/ssl/", crt)
        r = c.put_file(remote, fc)

        if r[0]:
            wlogger.log(tid, "File {} uploaded".format(remote), "success")
        else:
            wlogger.log(tid, "Can't upload {0}: {1}".format(remote,r[1]), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False

    nginx_config = make_nginx_proxy_conf()

    #put nginx.conf to server
    remote = "/etc/nginx/nginx.conf"
    r = c.put_file(remote, nginx_config)

    if r[0]:
         wlogger.log(tid, "File {} uploaded".format(remote), "success")
    else:
        wlogger.log(tid, "Can't upload {0}: {1}".format(remote,r[1]), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False
    #it is time to start nginx server
    cmd = 'service nginx restart'

    run_command(tid, c, cmd, no_error='debug')

    #enable nginx on boot
    cmd = 'systemctl enable nginx.service'
    run_command(tid, c, cmd, no_error='debug')

    if app_config.modify_hosts:
        
        host_ip = []

        servers = Server.query.all()

        for ship in servers:
            host_ip.append((ship.hostname, ship.ip))

        host_ip.append((app_config.nginx_host, app_config.nginx_ip))

        modify_hosts(tid, c, host_ip)

    wlogger.log(tid, "NGINX successfully installed")

def exec_cmd(command):
    print "executing commnd", command
    popen = subprocess.Popen(command, stdout=subprocess.PIPE)
    return iter(popen.stdout.readline, b"")


@celery.task(bind=True)
def upgrade_clustermgr_task(self, pip=False):
    tid = self.request.id
    
    cmd = '/usr/bin/sudo pip install --upgrade https://github.com/GluuFederation/cluster-mgr/archive/master.zip'

    wlogger.log(tid, cmd)

    for line in exec_cmd(cmd.split()):
        wlogger.log(tid, line, 'debug')
    
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


@celery.task(bind=True)
def update_httpd_certs_task(self, httpd_key, httpd_crt):
    
    tid = self.request.id
    appconf = AppConfiguration.query.first()

    servers = Server.query.all()

    if not appconf.external_load_balancer:
        mock_server = Server()
        mock_server.hostname = appconf.nginx_host
        mock_server.ip = appconf.nginx_ip
        mock_server.proxy = True
        mock_server.os = appconf.nginx_os_type
        servers.insert(0, mock_server)

    for server in servers:
        installer = Installer(server, appconf.gluu_version, logger_tid=tid)
        if hasattr(server, 'proxy'):
            if not server.os:
                print "Determining nginx os type"
                os_type = get_os_type(installer.c)
                installer.server_os = os_type
                appconf.nginx_os_type = os_type
                installer.appy_config()
                db.session.commit()

            key_path = '/etc/nginx/ssl/httpd.key'
            crt_path = '/etc/nginx/ssl/httpd.crt'
        else:
            key_path = os.path.join(installer.container, 'etc/certs/httpd.key')
            crt_path = os.path.join(installer.container, 'etc/certs/httpd.crt')


        wlogger.log(tid, "Uploading key to " + server.hostname,'debug')
        result = installer.c.put_file(key_path, httpd_key)
        if result[0]:
            wlogger.log(tid, "Key uploaded",'success')
        else:
            wlogger.log(tid, "Failed to upload key: " + str(result[1]) ,'error')
        
        wlogger.log(tid, "Uploading certificate to " + server.hostname,'debug')
        result = installer.c.put_file(crt_path, httpd_crt)
        if result[0]:
            wlogger.log(tid, "Certificate uploaded",'success')
        else:
            wlogger.log(tid, "Failed to upload certificate: " + str(result[1]) ,'error')

        if hasattr(server, 'proxy'):
            installer.run('service nginx restart', False)
        else:
            delete_key('httpd', appconf.nginx_host, appconf.gluu_version, tid, installer.c, installer.server_os)
            import_key('httpd', appconf.nginx_host, appconf.gluu_version, tid, installer.c, installer.server_os)
            installer.restart_gluu()

    return True

@celery.task
def check_latest_version():
    appconf = AppConfiguration.query.first()
    if appconf:
        print "Checking latest version from github"
        result = requests.get('https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/clustermgr/__init__.py')
        text = result.text.strip()
        latest_version = text.split('=')[1].strip().strip('"').strip("'")        
        appconf.latest_version = latest_version
        print "Latest github version is %s" % latest_version
        db.session.commit()

