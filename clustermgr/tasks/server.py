# -*- coding: utf-8 -*-

import os
import re
import time
import subprocess
import uuid
import traceback
import io

from flask import current_app as app

from clustermgr.models import ConfigParam
from clustermgr.extensions import wlogger, db, celery
import re

from clustermgr.core.remote import RemoteClient, get_connection
from clustermgr.config import Config


from clustermgr.core.clustermgr_installer import Installer
from clustermgr.core.utils import get_setup_properties, modify_etc_hosts
from clustermgr.core.jproperties import Properties

from clustermgr.core.ldap_functions import LdapOLC

@celery.task
def collect_server_details(server_id):
    print("Start collecting server details task")
    
    server = ConfigParam.get_by_id(server_id)
    
    installer = Installer(
                server,
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
        'Shibboleth': 'opt/shibboleth-idp',
        'oxAuthRP': 'opt/gluu/jetty/oxauth-rp',
        'Asimba': 'opt/gluu/jetty/asimba',
        'Passport': 'opt/gluu/node/passport',
    }
    installed = []
    
    if server.gluu_server:
        for component, marker in components.items():
            marker = os.path.join(installer.container, marker)
            if installer.conn.exists(marker):
                installed.append(component)

    server.data.components = installed

    server.data.os = os_type

    server.save()


def modify_hosts(task_id, conn, hosts, chroot='/', server_host=None, server_id=''):
    wlogger.log(task_id, "Modifying /etc/hosts of server {0}".format(server_host), server_id=server_id)
    
    hosts_file = os.path.join(chroot,'etc/hosts')
    
    result, old_hosts = conn.get_file(hosts_file)
    
    if result:
        new_hosts = modify_etc_hosts(hosts, old_hosts.read())
        conn.put_file(hosts_file, new_hosts)
        wlogger.log(task_id, "{} was modified".format(hosts_file), 'success', server_id=server_id)
    else:
        wlogger.log(task_id, "Can't receive {}".format(hosts_file), 'fail', server_id=server_id)


    if chroot:

        hosts_file = os.path.join(chroot, 'etc/hosts')
        
        result, old_hosts = conn.get_file(hosts_file)
        
        if result:
            new_hosts = modify_etc_hosts(hosts, old_hosts.read())
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
        ldap_type (string): type of ldapserver, currently opendj
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

def checkOfflineRequirements(installer, server, settings):
    os_type, os_version = server.data.os.split()

    wlogger.log(installer.logger_task_id, "Checking if dependencies were installed")

    #Check if archive type and os type matches    
    if not settings.data.gluu_archive.endswith('.'+installer.clone_type):
        wlogger.log(installer.logger_task_id,
                    "Os type does not match gluu archive type", 'error')
        return False

    wlogger.log(installer.logger_task_id,
                    "Os type matches with gluu archive", 'success')
    
    #Determine gluu version
    a_path, a_fname = os.path.split(settings.data.gluu_archive)
    m = re.search('gluu-server(_|-)(?P<gluu_version>(\d+).(\d+)((.\d+)?)(\.\d+)?)',a_fname)

    if m:
        gv = m.group('gluu_version')
        gv = gv.split('_')[0]
        appconf.gluu_version = gv
        db.session.commit()
        wlogger.log(
            installer.logger_task_id,
            "Gluu version was determined as {0} from gluu archive".format(gv),
            'success'
            )
    else:
        wlogger.log(installer.logger_task_id,
                    "Gluu version could not be determined from gluu archive", 
                    'error')
        return False

    #check if curl exists on the system
    cmd = 'which curl'
    result = installer.run(cmd, inside=False, error_exception='no curl in')

    curlexist = False if not 'curl' in result[1] else True

    if result[1]:
        wlogger.log(installer.logger_task_id, "curl was installed",'success')
    else:
        wlogger.log(
            installer.logger_task_id, 
            'curl was not installed. Please install curl on the host '
            'system (outside of the container) and retry.', 
            'error'
            )
        return False
        

    #Check if python is installed
    if installer.conn.exists('/usr/bin/python'):
        wlogger.log(installer.logger_task_id, "Python was installed",'success')
    else:
        wlogger.log(
            installer.logger_task_id, 
            'python was not installed. Please install python on the host '
            'system (outside of the container) and retry.', 
            'error'
            )
        return False

    #Check if ntp was installed
    if installer.conn.exists('/usr/sbin/ntpdate'):
        wlogger.log(installer.logger_task_id, "ntpdate was installed", 'success')
    else:
        wlogger.log(
            installer.logger_task_id, 
            'ntpdate was not installed. Please install ntpdate on the host '
            'system (outside of the container) and retry.', 
            'error'
            )
        return False

    #Check if stunnel was installed
    if installer.conn.exists('/usr/bin/stunnel') or installer.conn.exists('/bin/stunnel'):
        wlogger.log(installer.logger_task_id, "stunnel was installed", 'success')
    else:
        wlogger.log(
            installer.logger_task_id, 
            'stunnel was not installed. Please install stunnel on the host '
            'system (outside of the container) and retry.', 
            'error'
            )
        return False

    return True


def make_opendj_listen_world(server, installer):
        
    wlogger.log(installer.logger_task_id, "Making openDJ listens all interfaces for port 4444 and 1636")
    
    opendj_commands = [
            "sed -i 's/dsreplication.java-args=-Xms8m -client/dsreplication.java-args=-Xms8m -client -Dcom.sun.jndi.ldap.object.disableEndpointIdentification=true/g' /opt/opendj/config/java.properties",
            "/opt/opendj/bin/dsjavaproperties",
            "/opt/opendj/bin/dsconfig -h localhost -p 4444 -D 'cn=directory manager' -w $'{}' -n set-administration-connector-prop  --set listen-address:0.0.0.0 -X".format(server.ldap_password),
            "/opt/opendj/bin/dsconfig -h localhost -p 4444 -D 'cn=directory manager' -w $'{}' -n set-connection-handler-prop --handler-name 'LDAPS Connection Handler' --set enabled:true --set listen-address:0.0.0.0 -X".format(server.ldap_password),
            ]

    if server.os in ('RHEL 7', 'Ubuntu 18'):
        opendj_commands.append('systemctl stop opendj')
        opendj_commands.append('systemctl start opendj')
    else:
        opendj_commands.append('/etc/init.d/opendj stop')
        opendj_commands.append('/etc/init.d/opendj start')
    
    for command in opendj_commands:
        installer.run(command)

    #wait a couple of seconds for starting opendj
    time.sleep(5)

def install_gluu_server(task_id, server_id):

    server = ConfigParam.get_by_id(server_id)
    primary_server = ConfigParam.get_primary_server()

    settings = ConfigParam.get('settings')
    load_balancer = ConfigParam.get('load_balancer')
    enable_command = None
    gluu_server = 'gluu-server'

    # local setup properties file path
    setup_properties_file = os.path.join(
                                        Config.DATA_DIR, 
                                        'setup.properties'
                                        )


    # get setup properties
    setup_prop = get_setup_properties()


    # If os type of this server was not idientified, return to home
    if not server.data.os:
        wlogger.log(task_id, "OS type has not been identified.", 'fail')
        return False

    if server.data.os != primary_server.data.os:
        wlogger.log(task_id, "OS type is not the same as primary server.", 'fail')
        return False

    # If this is not primary server, we will download setup.properties
    # file from primary server
    if not server.data.primary:
        wlogger.log(task_id, "Check if Primary Server is Installed", 'head')

        primary_server_installer = Installer(
                                primary_server,
                                logger_task_id=task_id,
                                server_os=server.data.os
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
                    logger_task_id=task_id, 
                    server_os=server.data.os
                    )
    
    if not installer.conn:
        return False


    if settings.data.offline:
        if not checkOfflineRequirements(installer, server, settings):
            return False

    if not settings.data.offline:
        
        #check if curl exists on the system
        cmd = 'which curl'
        result = installer.run(cmd, inside=False)
        if not result[1]:
            installer.install('curl', inside=False)
        
        
        #nc is required for dyr run
        netcat_package = 'nc'
        if installer.clone_type == 'deb':
            netcat_package = 'netcat'
        installer.install(netcat_package, inside=False)
            
        if not installer.conn.exists('/usr/bin/python'):
            installer.install('python', inside=False)

        #add gluu server repo and imports signatures
        if ('Ubuntu' in server.data.os) or ('Debian' in server.data.os):

            if server.data.os == 'Ubuntu 16':
                dist = 'xenial'
            elif server.data.os == 'Ubuntu 18':
                dist = 'bionic'

            if 'Ubuntu' in server.data.os:
                cmd_list = (
                    'curl https://repo.gluu.org/ubuntu/gluu-apt.key | '
                    'apt-key add -',
                    'echo "deb https://repo.gluu.org/ubuntu/ {0} main" '
                    '> /etc/apt/sources.list.d/gluu-repo.list'.format(dist)
                    )
            
            elif 'Debian' in server.data.os:
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

        elif 'CentOS' in server.data.os or 'RHEL' in server.data.os:
            if not installer.conn.exists('/usr/bin/wget'):
                installer.install('wget', inside=False, error_exception='warning: /var/cache/')

            if server.data.os == 'CentOS 7':

                cmd = (
                  'wget https://repo.gluu.org/centos/Gluu-centos7.repo -O '
                  #'wget https://repo.gluu.org/centos/Gluu-centos-7-testing.repo  -O '
                  '/etc/yum.repos.d/Gluu.repo'
                  )

                enable_command  = '/sbin/gluu-serverd enable'
                
            elif server.data.os == 'RHEL 7':
                cmd = (
                  'wget https://repo.gluu.org/rhel/Gluu-rhel7.repo -O '
                  '/etc/yum.repos.d/Gluu.repo'
                  )
                enable_command  = '/sbin/gluu-serverd enable'

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
    
    if installer.conn.exists('/opt/gluu-server'):
        gluu_version = installer.get_gluu_version(installed=True)
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

        installer.remove('gluu-server', inside=False)

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


    if settings.data.offline:

        gluu_archive_fn = os.path.split(settings.data.gluu_archive)[1]
        wlogger.log(task_id, "Uploading {}".format(gluu_archive_fn))

        cmd = 'scp {} root@{}:/root'.format(settings.data.gluu_archive, server.data.hostname)
        wlogger.log(task_id, cmd,'debug')
        time.sleep(1)
        os.system(cmd)
        
        if installer.clone_type == 'deb':
            install_command = 'dpkg -i /root/{}'.format(gluu_archive_fn)
        else:
            install_command = 'rpm -i /root/{}'.format(gluu_archive_fn)

        installer.run(install_command, inside=False, error_exception='__ALL__')

    else:

        if server.data.os in ('Ubuntu 16', 'Ubuntu 18'):
            gluu_package_name = gluu_server + '=' + settings.data.gluu_version + '~' + dist
        else:
            gluu_package_name = gluu_server + '-' + settings.data.gluu_version
        
        cmd = installer.get_install_cmd(gluu_package_name, inside=False)

        ubuntu_re = re.compile('\[(\s|\w|%|/|-|\.)*\]')
        ubuntu_re_2 = re.compile('\(Reading database ... \d*')
        centos_re = re.compile(' \[(=|-|#|\s)*\] ')
        
        re_list = [ubuntu_re, ubuntu_re_2, centos_re]
        
        all_cout = installer.run_channel_command(cmd, re_list)

        #If previous installation was broken, make a re-installation. 
        #This sometimes occur on ubuntu installations
        if 'half-installed' in all_cout:
            if ('Ubuntu' in server.data.os) or ('Debian' in server.data.os):
                cmd = 'DEBIAN_FRONTEND=noninteractive  apt-get install --reinstall -y '+ gluu_server
                installer.run_channel_command(cmd, re_list)

        if enable_command:
            installer.run(enable_command, inside=False, error_exception='__ALL__')

    installer.start_gluu()

    #Since we will make ssh inot centos container, we need to wait ssh server to
    #be started properly
    if server.data.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
        wlogger.log(task_id, "Sleeping 10 secs to wait for gluu server start properly.")
        time.sleep(10)


    # If this server is primary, upload local setup.properties to server
    if server.data.primary:
        wlogger.log(task_id, "Uploading setup.properties")
        result = installer.upload_file(setup_properties_file, 
                 '/opt/gluu-server/root/setup.properties')
    # If this server is not primary, get setup.properties.last from primary
    # server and upload to this server
    else:
        #this is not primary server, so download setup.properties.last
        #from primary server and upload to this server

        # ldap_paswwrod of this server should be the same with primary server
        ldap_passwd = None

        remote_file = '/opt/gluu-server/install/community-edition-setup/setup.properties.last'
        wlogger.log(task_id, 'Downloading setup.properties.last from primary server', 'debug')

        prop_list = ['passport_rp_client_jks_pass', 
                     'application_max_ram',
                     'encoded_ldap_pw',
                     'ldapPass',
                     'state',
                     'defaultTrustStorePW',
                     'passport_rs_client_jks_pass_encoded',
                     'passportSpJksPass',
                     'pairwiseCalculationSalt',
                     'installAsimba',
                     'installLdap',
                     'oxauth_client_id',
                     'oxTrust_log_rotation_configuration',
                     'scim_rs_client_jks_pass_encoded',
                     'encoded_openldapJksPass',
                     'inumApplianceFN',
                     'inumAppliance',
                     'oxauthClient_pw',
                     'opendj_p12_pass',
                     'passportSpKeyPass',
                     'scim_rs_client_jks_pass',
                     'inumOrgFN',
                     'scim_rs_client_id',
                     'default_key_algs',
                     'installOxTrust',
                     'ldap_port',
                     'encoded_shib_jks_pw',
                     'orgName',
                     'openldapKeyPass',
                     'city',
                     'oxVersion',
                     'baseInum',
                     'asimbaJksPass',
                     'oxTrustConfigGeneration',
                     'passport_rp_client_id',
                     'pairwiseCalculationKey',
                     'scim_rp_client_jks_pass',
                     'encoded_opendj_p12_pass',
                     'httpdKeyPass',
                     'installOxAuth',
                     'admin_email',
                     'passport_rs_client_jks_pass',
                     'oxauth_openid_jks_pass',
                     'countryCode',
                     'installSaml',
                     'installJce',
                     'encoded_ldapTrustStorePass',
                     'encode_salt',
                     'inumOrg',
                     'openldapJksPass',
                     'encoded_ox_ldap_pw',
                     'installHttpd',
                     'passport_rs_client_id',
                     'scim_rp_client_id',
                     'ldap_hostname',
                     'oxauthClient_encoded_pw',
                     'shibJksPass',
                     'installPassport',
                     'installOxAuthRP',
                     ]

        prop_io = None

        #get setup.properties.last from primary server.
        if primary_server_installer.conn.exists(remote_file):
            result = primary_server_installer.conn.get_file(remote_file)
            prop_io = result[1]
        else:
            cmd_unenc = 'openssl enc -d -aes-256-cbc -in /install/community-edition-setup/setup.properties.last.enc -k {}'.format(server.data.ldap_password)
            result = primary_server_installer.run(cmd_unenc, inside=True)
            prop_io = io.StringIO(result[1])
            prop_io.seek(0)

        prop = Properties()
        if prop_io:
            prop.load(prop_io.read())
            prop_keys = list(prop.keys())
            
            for p in prop_keys[:]:
                if not p in prop_list:
                    del prop[p]

            prop['ip'] = str(server.data.ip)
            prop['ldap_type'] = 'opendj'
            prop['hostname'] = str(load_balancer.data.hostname)
            ldap_passwd = prop['ldapPass']

            new_setup_properties_io = io.BytesIO()
            prop.store(new_setup_properties_io)
            new_setup_properties_io.seek(0)
            new_setup_properties = new_setup_properties_io.read()

            #put setup.properties to server
            remote_file_new = '/opt/gluu-server/root/setup.properties'
            installer.put_file(remote_file_new, new_setup_properties.decode())

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

    # setup.py of 4.1.0 is buggy, we need to download from github
    if settings.data.gluu_version == '4.1.0':
        installer.run('wget https://raw.githubusercontent.com/GluuFederation/community-edition-setup/version_4.1.0/setup.py -O /install/community-edition-setup/setup.py',
                        inside=True, error_exception='__ALL__')
        installer.run('chmod +x /install/community-edition-setup/setup.py', inside=True, error_exception='__ALL__')

    setup_cmd = '/install/community-edition-setup/setup.py -f /root/setup.properties --listen_all_interfaces -n'

    #Don't load base data for secondary nodes
    if not server.data.primary:
        setup_cmd += ' --no-data'

    cmd = installer.run_command.format(setup_cmd)
    
    re_list = [re.compile(' \[(#|\s)*\] ')]
    
    all_cout = installer.run_channel_command(cmd, re_list)

    wlogger.log(task_id, "4", "setstep")
    #JavaScript on logger duplicates next log if we don't add this
    time.sleep(1)

    if settings.data.modify_hosts:
        all_server = ConfigParam.get_servers()
        host_ip = [ (ship.data.hostname, ship.data.ip) for ship in all_server ]
        modify_hosts(task_id, installer.conn, host_ip, '/opt/gluu-server/', server.data.hostname)

    # Get slapd.conf from primary server and upload this server
    if not server.data.primary:

        #we need to download certificates
        #from primary server and upload to this server, then will delete and
        #import keys
        wlogger.log(task_id, "Downloading certificates from primary "
                         "server and uploading to this server")
        certs_remote_tmp = "/tmp/certs_"+str(uuid.uuid4())[:4].upper()+".tgz"
        certs_local_tmp = "/tmp/certs_"+str(uuid.uuid4())[:4].upper()+".tgz"

        cmd = ('tar -zcf {0} /opt/{1}/etc/certs/ '
                '/opt/{1}/install/community-edition-setup/output/scim-rp.jks '
                '/opt/{1}/etc/gluu/conf/passport-config.json'
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
                setup_prop['ldap_type'],
                ):
            installer.delete_key(suffix, load_balancer.data.hostname)
            installer.import_key(suffix, load_balancer.data.hostname)

        download_and_upload_custom_schema(  
                                            task_id,
                                            primary_server_installer.conn,
                                            installer.conn, 
                                            'opendj', gluu_server
                                        )
                                        
        #create base dn for o=metric backend    
        wlogger.log(task_id, "Creating base dn for o=metric backend")
        
        ldapc = LdapOLC(
                    'ldaps://{}:1636'.format(server.data.hostname),
                    'cn=Directory Manager',
                    server.data.ldap_password
                     )
        
        if not ldapc.connect():
            wlogger.log(task_id, "Cannot connect to ldap server. Failed to "
                            "create base dn for o=metric backend", 'warning')
        else:
            r = ldapc.checkBaseDN(dn='o=metric', 
                                attributes={
                                    'objectClass': ['top', 'organization'],
                                    'o': 'site'
                                        }
                                )
            if r:
                wlogger.log(task_id, "o=metric created", 'success')
                            
            r = ldapc.checkBaseDN(dn='ou=statistic,o=metric', 
                                attributes={
                                  'objectClass': ['top', 'organizationalUnit'],
                                  'ou': 'statistic'
                                      }
                                )
            if r:
                wlogger.log(task_id, "ou=statistic,o=metric created", 'success')

        wlogger.log(task_id, "Gluu Server successfully installed")

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


    server.data.gluu_server = True
    server.save()

    #ntp is required for time sync, since ldap replication will be
    #done by time stamp. If not isntalled, install and configure crontab
    wlogger.log(task_id, "Checking if ntp is installed and configured.")

    if installer.conn.exists('/usr/sbin/ntpdate'):
        wlogger.log(task_id, "ntp was installed", 'success')
    else:
        installer.install('ntpdate', inside=False)

    #run time sync an every minute
    installer.put_file('/etc/cron.d/setdate',
                '* * * * *    root    /usr/sbin/ntpdate -s time.nist.gov\n')
    wlogger.log(task_id, 'Crontab entry was created to update time in every minute',
                     'debug')

    if 'CentOS' in server.data.os or 'RHEL' in server.data.os:
        installer.restart_service('crond')
    else:
        installer.restart_service('cron')


    
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
