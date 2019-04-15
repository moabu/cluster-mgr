import json
import os
import getpass
import re

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.utils import run_and_log
from clustermgr.tasks.cluster import get_os_type, makeOpenDjListenIpAddr,\
        get_chroot, get_run_cmd
from clustermgr.core.clustermgr_installer import Installer
from clustermgr.config import Config
from clustermgr.core.utils import get_setup_properties, \
        write_setup_properties_file
from clustermgr.core.change_gluu_host import ChangeGluuHostname

from flask import current_app as app



@celery.task(bind=True)
def wizard_step1(self):
    
    """Celery task that collects information about server.

    :param self: the celery task

    :return: the number of servers where both stunnel and redis were installed
        successfully
    """
    
    tid = self.request.id

    wlogger.log(tid, "Analayzing Current Server")

    server = Server.query.filter_by(primary_server=True).first()

    app_conf = AppConfiguration.query.first()
    
    c = RemoteClient(server.hostname, ip=server.ip)

    try:
        c.startup()
        wlogger.log(tid, "SSH connection established", 'success')
    except:
        wlogger.log(tid, "Can't establish SSH connection",'fail')
        wlogger.log(tid, "Ending analyzation of server.", 'error')
        return

    os_type = get_os_type(c)
    
    server.os = os_type
    
    wlogger.log(tid, "OS type was determined as {}".format(os_type), 'debug')
    
    gluu_version = None
    
    #Determine if a version of gluu server was installed.
    r = c.listdir("/opt")
    if r[0]:
        for s in r[1]:
            m=re.search('gluu-server-(?P<gluu_version>(\d+).(\d+).(\d+)(.\d+)?)$',s)
            if m:
                gluu_version = m.group("gluu_version")
                
                app_conf.gluu_version = gluu_version
                wlogger.log(tid, "Gluu version was determined as {}".format(
                                                        gluu_version), 'debug')
    
    if not gluu_version:
        wlogger.log(tid, "Gluu server was not installed on this server",'fail')
        wlogger.log(tid, "Ending analyzation of server.", 'error')
        return
    
    gluu_path = '/opt/gluu-server-{}'.format(gluu_version)
    
    server.gluu_server = True
    
    setup_properties_last = os.path.join(gluu_path, 
                        'install/community-edition-setup/setup.properties.last')
    
    setup_properties_local = os.path.join(Config.DATA_DIR, 'setup.properties')
    
    result = c.download(setup_properties_last, setup_properties_local)
    
    prop = get_setup_properties()
    prop['hostname'] = app_conf.nginx_host
    write_setup_properties_file(prop)
    
    
    if not result.startswith('Download successful'):
        wlogger.log(tid, result,'fail')
        wlogger.log(tid, "Ending analyzation of server.", 'error')
        return
    
    wlogger.log(tid, "setup.properties file was downloaded", 'debug')
    
    server.ldap_password = prop['ldapPass']
    
    wlogger.log(tid, "LDAP Bind password was identifed", 'success')
    
    db.session.commit()


@celery.task(bind=True)
def wizard_step2(self):
    tid = self.request.id

    setup_prop = get_setup_properties()
    
    server = Server.query.filter_by(primary_server=True).first()
    app_conf = AppConfiguration.query.first()
    
    c = RemoteClient(server.hostname, ip=server.ip)

    wlogger.log(tid, "Making SSH Connection")

    try:
        c.startup()
        wlogger.log(tid, "SSH connection established", 'success')
    except:
        wlogger.log(tid, "Can't establish SSH connection",'fail')
        wlogger.log(tid, "Ending changing name.", 'error')
        return
    
    run_cmd , cmd_chroot = get_run_cmd(server)
    makeOpenDjListenIpAddr(tid, c, cmd_chroot, run_cmd, server)
    
    name_changer = ChangeGluuHostname(
            old_host = server.hostname,
            new_host = app_conf.nginx_host,
            cert_city = setup_prop['city'],
            cert_mail = setup_prop['admin_email'], 
            cert_state = setup_prop['state'],
            cert_country = setup_prop['countryCode'],
            server = server.hostname,
            ip_address = server.ip,
            ldap_password = setup_prop['ldapPass'],
            os_type = server.os,
            gluu_version = app_conf.gluu_version,
            local=False,
        )

    name_changer.logger_tid = tid

    r = name_changer.startup()
    if not r:
        wlogger.log(tid, "Name changer can't be started",'fail')
        wlogger.log(tid, "Ending changing name.", 'error')
        return

    wlogger.log(tid, "Cahnging LDAP Applience configurations")
    name_changer.change_appliance_config()
    wlogger.log(tid, "LDAP Applience configurations were changed", 'success')
    
    
    wlogger.log(tid, "Cahnging LDAP Clients entries")
    name_changer.change_clients()
    wlogger.log(tid, "LDAP Applience Clients entries were changed", 'success')

    wlogger.log(tid, "Cahnging LDAP Uma entries")
    name_changer.change_uma()
    wlogger.log(tid, "LDAP Applience Uma entries were changed", 'success')
    
    wlogger.log(tid, "Modifying SAML & Passport")
    name_changer.modify_saml_passport()
    wlogger.log(tid, "SAML & Passport were changed", 'success')

    wlogger.log(tid, "Reconfiguring http")
    name_changer.change_httpd_conf()
    wlogger.log(tid, " LDAP Applience Uma entries were changed", 'success')

    wlogger.log(tid, "Creating certificates")
    name_changer.create_new_certs()
    
    wlogger.log(tid, "Changing /etc/hostname")
    name_changer.change_host_name()
    wlogger.log(tid, "/etc/hostname was changed", 'success')
    
    wlogger.log(tid, "Modifying /etc/hosts")
    name_changer.modify_etc_hosts()
    wlogger.log(tid, "/etc/hosts was modified", 'success')
    
    name_changer.installer.restart_gluu()
    
