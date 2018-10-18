# -*- coding: utf-8 -*-

import os
import re
import time
import subprocess
import uuid
import traceback

from flask import current_app as app

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import wlogger, db, celery
import re

from clustermgr.core.remote import RemoteClient, get_connection
from clustermgr.config import Config


from clustermgr.core.clustermgr_installer import Installer
from clustermgr.core.utils import get_setup_properties, modify_etc_hosts


@celery.task
def collect_server_details(server_id):
    print "Start collecting server details task"
    app_conf = AppConfiguration.query.first()
    
    if server_id == -1:
        #mock server
        server = Server( hostname=app_conf.nginx_host,
                         ip = app_conf.nginx_ip
                         )
    else:
        server = Server.query.get(server_id)
        hostname = server.hostname
        ip = server.ip
    
    installer = Installer(
                server,
                app_conf.gluu_version,
                logger_task_id=-1,
                server_os=None
                )

    os_type = installer.get_os_type()

    if server_id == -1:
        app_conf.nginx_os = os_type
        db.session.commit()
        return


    # 0. Make sure it is a Gluu Server
    server.gluu_server = installer.is_gluu_installed()

    # 1. The components installed in the server
    components = {
        'oxAuth': 'opt/gluu/jetty/oxauth',
        'oxTrust': 'opt/gluu/jetty/identity',
        'OpenLDAP': 'opt/symas/etc/openldap',
        'Shibboleth': 'opt/shibboleth-idp',
        'oxAuthRP': 'opt/gluu/jetty/oxauth-rp',
        'Asimba': 'opt/gluu/jetty/asimba',
        'Passport': 'opt/gluu/node/passport',
    }
    installed = []
    
    if server.gluu_server:
        for component, marker in components.iteritems():
            marker = os.path.join(installer.container, marker)
            if installer.conn.exists(marker):
                installed.append(component)

    server.components = ",".join(installed)

    server.os = os_type

    db.session.commit()


def modify_hosts(task_id, conn, hosts, chroot='/', server_host=None, server_id=''):
    wlogger.log(task_id, "Modifying /etc/hosts of server {0}".format(server_host), server_id=server_id)
    
    hosts_file = os.path.join(chroot,'etc/hosts')
    
    result, old_hosts = conn.get_file(hosts_file)
    
    if result:
        new_hosts = modify_etc_hosts(hosts, old_hosts)
        conn.put_file(hosts_file, new_hosts)
        wlogger.log(task_id, "{} was modified".format(hosts_file), 'success', server_id=server_id)
    else:
        wlogger.log(task_id, "Can't receive {}".format(hosts_file), 'fail', server_id=server_id)


    if chroot:

        hosts_file = os.path.join(chroot, 'etc/hosts')
        
        result, old_hosts = conn.get_file(hosts_file)
        
        if result:
            new_hosts = modify_etc_hosts(hosts, old_hosts)
            conn.put_file(hosts_file, new_hosts)
            wlogger.log(task_id, "{0} of server {1} was modified".format(hosts_file, server_host), 'success', server_id=server_id)
        else:
            wlogger.log(task_id, "Can't receive {}".format(hosts_file), 'fail', server_id=server_id)


def download_and_upload_custom_schema(task_id, primary_conn, conn, ldap_type, gluu_server):
    """Downloads custom ldap schema from primary server and 
        uploads to current server represented by conn
    Args:
        tid (string): id of the task running the command,
        primary_conn (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication, representing primary server

        conn (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication, representing current server
        ldap_type (string): type of ldapserver, either openldap or opendj
        gluu_server: Gluu server name
    """
    
    wlogger.log(task_id, 'Downloading custom schema files' 
                    'from primary server and upload to this server')
    custom_schema_files = primary_conn.listdir("/opt/{}/opt/gluu/schema/{}/".format(
                                                    gluu_server, ldap_type))

    if custom_schema_files[0]:
        
        schema_folder = '/opt/{}/opt/gluu/schema/{}'.format(
                        gluu_server, ldap_type)
        if not conn.exists(schema_folder):
            conn.run('mkdir -p {}'.format(schema_folder))
        
        for custom_schema in custom_schema_files[1]:
            schema_filename = '/opt/{0}/opt/gluu/schema/{2}/{1}'.format(
                                                gluu_server, custom_schema, ldap_type)
                                                
            result, schema = primary_conn.get_file(schema_filename)
            if result:
                conn.put_file(schema_filename, schema.read())
                wlogger.log(tid, 
                    '{0} dowloaded from from primary and uploaded'.format(
                                                            custom_schema),
                                                            'debug')

                if ldap_type == 'opendj':

                    opendj_path = ('/opt/{}/opt/opendj/config/schema/'
                                '999-clustmgr-{}').format(gluu_server, custom_schema)
                    conn.run('cp {} {}'.format(schema_filename, opendj_path))





@celery.task(bind=True)
def task_install_gluu_server(self, server_id):
    
    task_id = self.request.id

    """
    for i in range(5):
        wlogger.log(task_id, str(i))
        time.sleep(1)
        
    
    wlogger.log(task_id, "2", "setstep")
    wlogger.log(task_id, "New Step")
    
    for i in range(5):
        wlogger.log(task_id, str(i))
        time.sleep(1)

    wlogger.log(task_id, "3", "setstep")
    wlogger.log(task_id, "New Step")
    
    
    for i in range(5):
        wlogger.log(task_id, str(i))
        time.sleep(1)
    
    return
    """

    try:
        install_gluu_server(task_id, server_id)
    except:
        raise Exception(traceback.format_exc())

def install_gluu_server(task_id, server_id):

    server = Server.query.get(server_id)
    primary_server = Server.query.filter_by(primary_server=True).first()

    app_conf = AppConfiguration.query.first()

    enable_command = None
    gluu_server = 'gluu-server-{0}'.format(app_conf.gluu_version)

    # local setup properties file path
    setup_properties_file = os.path.join(
                                        Config.DATA_DIR, 
                                        'setup.properties'
                                        )


    # get setup properties
    setup_prop = get_setup_properties()


    # If os type of this server was not idientified, return to home
    if not server.os:
        wlogger.log(task_id, "OS type has not been identified.", 'fail')
        return False


    # If this is not primary server, we will download setup.properties
    # file from primary server
    if not server.primary_server:
        wlogger.log(task_id, "Check if Primary Server is Installed", 'head')

        primary_server_installer = Installer(
                                primary_server,
                                app_conf.gluu_version,
                                logger_task_id=task_id,
                                server_os=server.os
                            )

        if not primary_server_installer.conn:
            wlogger.log(task_id, "Primary server is reachable via ssh.", "fail"
                        )
            return False
        else:
            if not primary_server_installer.is_gluu_installed():
                wlogger.log(task_id, "Primary server is not installed.","fail")
                return False
            
            else:
                wlogger.log(task_id, "Primary server is installed.", "success")


    wlogger.log(task_id, "Preparing Server for installation", 'head')
                
    installer = Installer(
                    server, 
                    app_conf.gluu_version, 
                    logger_task_id=task_id, 
                    server_os=server.os
                    )

    if not installer.conn:
        return False


    #nc is required for dyr run
    installer.install('nc', inside=False)

    if not installer.c.exists('/usr/bin/python'):
        installer.install('python', inside=False)

    #add gluu server repo and imports signatures
    if ('Ubuntu' in server.os) or ('Debian' in server.os):

        if server.os == 'Ubuntu 14':
            dist = 'trusty'
        elif server.os == 'Ubuntu 16':
            dist = 'xenial'


        if 'Ubuntu' in server.os:
            cmd_list = (
                'curl https://repo.gluu.org/ubuntu/gluu-apt.key | '
                'apt-key add -',
                'echo "deb https://repo.gluu.org/ubuntu/ {0}-devel main" '
                '> /etc/apt/sources.list.d/gluu-repo.list'.format(dist)
                )
        elif 'Debian' in server.os:
            cmd_list = (
                'curl https://repo.gluu.org/debian/gluu-apt.key | '
                'apt-key add -',
                'echo "deb https://repo.gluu.org/debian/ stable main" '
               '> /etc/apt/sources.list.d/gluu-repo.list'
                )


        for cmd in cmd_list:
            installer.run(cmd, inside=False, error_exception='Xferd')

        cmd = 'DEBIAN_FRONTEND=noninteractive apt-get update'
        cin, cout, cerr = installer.run(cmd, inside=False)
        
        if 'dpkg --configure -a' in cerr:
            cmd = 'dpkg --configure -a'
            wlogger.log(task_id, cmd, 'debug')
            installer.run(cmd, inside=False)

    elif 'CentOS' in server.os or 'RHEL' in server.os:
        if not installer.conn.exists('/usr/bin/wget'):
            installer.install('wget', inside=False, error_exception='warning: /var/cache/')

        if server.os == 'CentOS 6':
            cmd = (
              'wget https://repo.gluu.org/centos/Gluu-centos6.repo -O '
              '/etc/yum.repos.d/Gluu.repo')
        elif server.os == 'CentOS 7':
            
            cmd = (
              'wget https://repo.gluu.org/centos/Gluu-centos7.repo -O '
              '/etc/yum.repos.d/Gluu.repo'
              )
            enable_command  = '/sbin/gluu-serverd-{0} enable'
            
        elif server.os == 'RHEL 7':
            cmd = (
              'wget https://repo.gluu.org/rhel/Gluu-rhel7.repo -O '
              '/etc/yum.repos.d/Gluu.repo'
              )
            enable_command  = '/sbin/gluu-serverd-{0} enable'

        installer.run(cmd, inside=False, error_exception='__ALL__')

        cmd = (
          'wget https://repo.gluu.org/centos/RPM-GPG-KEY-GLUU -O '
          '/etc/pki/rpm-gpg/RPM-GPG-KEY-GLUU'
          )
        installer.run(cmd, inside=False, error_exception='__ALL__')

        cmd = 'rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-GLUU'
        installer.run(cmd, inside=False, error_exception='__ALL__')

        cmd = 'yum clean all'
        installer.run(cmd, inside=False, error_exception='__ALL__')


    wlogger.log(task_id, "Check if Gluu Server was installed", 'action')

    gluu_installed = False

    #Determine if a version of gluu server was installed.
    result = installer.conn.listdir("/opt")

    if result[0]:
        for file_name in result[1]:
            test = re.search(
                     "gluu-server-(?P<gluu_version>(\d+).(\d+).(\d+))$",
                      file_name
                      )
            if test:
                gluu_version = test.group("gluu_version")
                gluu_installed = True

                stop_result = installer.stop_gluu()

                #If gluu server is installed, first stop it then remove
                if "Can't stop gluu server" in stop_result:
                    cmd = 'rm -f /var/run/{0}.pid'.format(gluu_server)
                    installer.run(cmd, inside=False,
                                error_exception='__ALL__')

                    cmd = (
                      "df -aP | grep %s | awk '{print $6}' | xargs -I "
                      "{} umount -l {}" % (gluu_server)
                      )
                    installer.run(cmd, 
                                    inside=False, 
                                    error_exception='__ALL__')
                    
                    stop_result = installer.stop_gluu()

                installer.remove('gluu-server-'+gluu_version, 
                                inside=False)

    if not gluu_installed:
        wlogger.log(
                    task_id, 
                    "Gluu Server was not previously installed", 
                    "debug"
                    )

    wlogger.log(task_id, "2", "setstep")
    #JavaScript on logger duplicates next log if we don't add this
    time.sleep(1)

    wlogger.log(task_id, "Installing Gluu Server: " + gluu_server)
    
    cmd = installer.get_install_cmd(gluu_server, inside=False)

    ubuntu_re = re.compile('\[(\s|\w|%|/|-|\.)*\]')
    ubuntu_re_2 = re.compile('\(Reading database ... \d*')
    centos_re = re.compile(' \[(=|-|#|\s)*\] ')
    
    re_list = [ubuntu_re, ubuntu_re_2, centos_re]
    
    all_cout = installer.run_channel_command(cmd, re_list)

    #If previous installation was broken, make a re-installation. 
    #This sometimes occur on ubuntu installations
    if 'half-installed' in all_cout:
        if ('Ubuntu' in server.os) or ('Debian' in server.os):
            cmd = 'DEBIAN_FRONTEND=noninteractive  apt-get install --reinstall -y '+ gluu_server
            installer.run_channel_command(cmd, re_list)


    if enable_command:
        installer.run(enable_command.format(app_conf.gluu_version), error_exception='__ALL__')

    installer.start_gluu()

    #Since we will make ssh inot centos container, we need to wait ssh server to
    #be started properly
    if server.os == 'CentOS 7' or server.os == 'RHEL 7':
        wlogger.log(task_id, "Sleeping 10 secs to wait for gluu server start properly.")
        time.sleep(10)

    # If this server is primary, upload local setup.properties to server
    if server.primary_server:
        wlogger.log(task_id, "Uploading setup.properties")
        result = installer.conn.upload(setup_properties_file, 
                 '/opt/{}/install/community-edition-setup/'
                 'setup.properties'.format(gluu_server))
    # If this server is not primary, get setup.properties.last from primary
    # server and upload to this server
    else:
        #this is not primary server, so download setup.properties.last
        #from primary server and upload to this server

        # ldap_paswwrod of this server should be the same with primary server
        ldap_passwd = None


        remote_file = '/opt/{}/install/community-edition-setup/setup.properties.last'.format(gluu_server)
        wlogger.log(task_id, 'Downloading setup.properties.last from primary server', 'debug')

       #get setup.properties.last from primary server.
        result = primary_server_installer.conn.get_file(remote_file)
        if result[0]:
            new_setup_properties=''
            setup_properties = result[1].readlines()
            #replace ip with address of this server
            for l in setup_properties:
                if l.startswith('ip='):
                    l = 'ip={0}\n'.format(server.ip)
                elif l.startswith('ldapPass='):
                    ldap_passwd = l.split('=')[1].strip()
                elif l.startswith('hostname='):
                    l = 'hostname={0}\n'.format(app_conf.nginx_host)
                new_setup_properties += l

            #put setup.properties to server
            remote_file_new = '/opt/{}/install/community-edition-setup/setup.properties'.format(gluu_server)
            installer.put_file(remote_file_new,  new_setup_properties)

            if ldap_passwd:
                server.ldap_password = ldap_passwd
        else:
            wlogger.log(task_id, 
                    "Can't download setup.properties.last from primary server",
                    'fail')
            wlogger.log(task_id, 
                        "Ending server installation process.",
                        "error")
            return
    
    wlogger.log(task_id, "3", "setstep")
    #JavaScript on logger duplicates next log if we don't add this
    time.sleep(1)
    
    if app_conf.gluu_version < '3.1.3':
        wlogger.log(tid, "Downloading setup.py")
        cmd = ( 
                'curl  https://raw.githubusercontent.com/GluuFederation/'
                'community-edition-setup/master/setup.py  -o /install/'
                'community-edition-setup/setup.py'
                )
                
        cmd = ( 
                'curl https://raw.githubusercontent.com/mbaser/gluu/master'
                '/setup.py -o /install/'
                'community-edition-setup/setup.py'
                )

        
                
        installer.run(cmd)
        
        cmd = 'chmod +x /install/community-edition-setup/setup.py'
        installer.run(cmd)
    
    #run setup.py on the server
    wlogger.log(task_id, 
            "Running setup.py - Be patient this process will take a while ...")


    cmd = installer.run_command.format(
                    'cd /install/community-edition-setup/ && ./setup.py -n -v')

    
    re_list = [re.compile(' \[(#|\s)*\] ')]
    
    all_cout = installer.run_channel_command(cmd, re_list)


    wlogger.log(task_id, "4", "setstep")
    #JavaScript on logger duplicates next log if we don't add this
    time.sleep(1)

    if app_conf.modify_hosts:
        all_server = Server.query.all()
        
        host_ip = []
        
        for ship in all_server:
            host_ip.append((ship.hostname, ship.ip))

        modify_hosts(task_id, installer.conn, host_ip, '/opt/'+gluu_server+'/', server.hostname)


    # Get slapd.conf from primary server and upload this server
    if not server.primary_server:

        #If gluu version is greater than 3.0.2 we need to download certificates
        #from primary server and upload to this server, then will delete and
        #import keys
        if app_conf.gluu_version > '3.0.2':
            wlogger.log(task_id, "Downloading certificates from primary "
                             "server and uploading to this server")
            certs_remote_tmp = "/tmp/certs_"+str(uuid.uuid4())[:4].upper()+".tgz"
            certs_local_tmp = "/tmp/certs_"+str(uuid.uuid4())[:4].upper()+".tgz"

            cmd = ('tar -zcf {0} /opt/{1}/etc/certs/ '
                    '/opt/{1}/install/community-edition-setup/output/scim-rp.jks '
                    '/etc/gluu/conf/passport-config.json'
                    ).format(certs_remote_tmp, gluu_server)
            
            primary_server_installer.run(cmd,inside=False, error_exception='Removing leading')

            primary_server_installer.download_file(certs_remote_tmp, certs_local_tmp)
           
            installer.upload_file(certs_local_tmp, 
                                "/tmp/certs.tgz".format(gluu_server))

            cmd = 'tar -zxf /tmp/certs.tgz -C /'
            installer.run(cmd, inside=False)

            #delete old keys and import new ones
            wlogger.log(task_id, 'Manuplating keys')
            for suffix in (
                    'httpd',
                    'shibIDP',
                    'idp-encryption',
                    'asimba',
                    setup_prop['ldap_type'],
                    ):
                installer.delete_key(suffix, app_conf.nginx_host)
                installer.import_key(suffix, app_conf.nginx_host)

        download_and_upload_custom_schema(  
                                            task_id,
                                            primary_server_installer.conn,
                                            installer.conn, 
                                            'opendj', gluu_server
                                        )
    else:
        #this is primary server so we need to upload local custom schemas if any
        custom_schema_dir = os.path.join(Config.DATA_DIR, 'schema')
        custom_schemas = os.listdir(custom_schema_dir)

        if custom_schemas:
            schema_folder = '/opt/gluu/schema/{}'.format(ldap_type)
            if not installer.conn.exists(schema_folder):
                installer.conn.run('mkdir -p {}'.format(schema_folder))

            for schema_file in custom_schemas:
                
                local = os.path.join(custom_schema_dir, schema_file)
                remote = '/opt/{0}/opt/gluu/schema/{2}/{1}'.format(
                    gluu_server, schema_file, ldap_type)
                result = installer.upload_file(local, remote)



    #ntp is required for time sync, since ldap replication will be
    #done by time stamp. If not isntalled, install and configure crontab
    wlogger.log(task_id, "Checking if ntp is installed and configured.")

    if installer.conn.exists('/usr/sbin/ntpdate'):
        wlogger.log(task_id, "ntp was installed", 'success')
    else:
        installer.install('ntpdate')

    #run time sync an every minute
    installer.put_file('/etc/cron.d/setdate',
                '* * * * *    root    /usr/sbin/ntpdate -s time.nist.gov\n')
    wlogger.log(task_id, 'Crontab entry was created to update time in every minute',
                     'debug')

    if 'CentOS' in server.os or 'RHEL' in server.os:
        installer.restart_service('crond')
    else:
        installer.restart_service('cron')

    #We need to fix opendj initscript
    wlogger.log(task_id, 'Uploading fixed opendj init.d script')
    opendj_init_script = os.path.join(app.root_path, "templates",
                           "opendj", "opendj")
    remote_opendj_init_script = '/opt/{0}/etc/init.d/opendj'.format(gluu_server)
    
    result = installer.upload_file(opendj_init_script, remote_opendj_init_script)

    if not result:
        return False

    cmd = 'chmod +x {}'.format(remote_opendj_init_script)
    installer.run(cmd, inside=False)

    server.gluu_server = True
    db.session.commit()
    wlogger.log(task_id, "Gluu Server successfully installed")
    
    wlogger.log(task_id, "5", "setstep")
    return True


@celery.task(bind=True)
def task_test(self):
    
    task_id = self.request.id

    for si in range(1,4):
        for i in range(3):
            wlogger.log(task_id, str(i), server_id=si)
            time.sleep(1)

    wlogger.log(task_id, "2", "setstep")
    
    for si in range(1,4):
        for i in range(3):
            wlogger.log(task_id, str(i), server_id=si)
            time.sleep(1)
