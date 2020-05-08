import json
import os
import getpass
import re

from clustermgr.models import ConfigParam
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.utils import run_and_log
from clustermgr.core.clustermgr_installer import Installer
from clustermgr.config import Config
from clustermgr.core.utils import get_setup_properties, \
        write_setup_properties_file
from clustermgr.core.change_gluu_host import ChangeGluuHostname
from clustermgr.tasks.server import make_opendj_listen_world
from flask import current_app as app



@celery.task(bind=True)
def wizard_step1(self):
    
    """Celery task that collects information about server.

    :param self: the celery task

    :return: the number of servers where both stunnel and redis were installed
        successfully
    """
    
    task_id = self.request.id

    wlogger.log(task_id, "Analayzing Current Server")

    server = ConfigParam.get_primary_server()

    installer = Installer(
                server, 
                '', 
                logger_task_id=task_id, 
                )

    os_type = installer.server_os
    server.data.os = os_type
    server.save()

    wlogger.log(task_id, "OS type was determined as {}".format(os_type), 'success')

    gluu_version = installer.get_gluu_version()

    if not gluu_version:
        wlogger.log(task_id, "Gluu Server is not installed on this server", 'fail')
        wlogger.log(task_id, "Ending analyzation of server.", 'error')
        return False

    settings = ConfigParam.get_or_new('settings',
            data={
                  "service_update_period": 300,
                  "modify_hosts": True,
                  "gluu_archive": "",
                  "offline": False,
                  "gluu_version": gluu_version,
                  "use_ldap_cache": True
                }
                )

    settings.save()
 
    wlogger.log(task_id, "Gluu version was determined as {}".format(gluu_version), 'success')
    
    installer.settings()

    ldap_prop_file = installer.get_file('/opt/gluu-server/etc/gluu/conf/gluu-ldap.properties')

    for l in ldap_prop_file.splitlines():
        ls = l.strip()
        if ls.startswith('bindPassword'):
            n = ls.find(':')
            en_password = ls[n+1:].strip()
            break

    pw_result = installer.run('/opt/gluu/bin/encode.py -D ' + en_password, inside=True, nolog=True)
    ldap_password = pw_result[1].strip()

    server.data.ldap_password = ldap_password
    server.save()

    setup_properties_last = os.path.join(installer.container, 
                        'install/community-edition-setup/setup.properties.last')

    if installer.conn.exists(setup_properties_last + '.enc'):
        cmd_unenc = "openssl enc -d -aes-256-cbc -in /install/community-edition-setup/setup.properties.last.enc -out /install/community-edition-setup/setup.properties.last -pass pass:$'{}'".format(server.data.ldap_password)
        installer.run(cmd_unenc, inside=True)

    setup_properties_local = os.path.join(Config.DATA_DIR, 'setup.properties')
    
    result = installer.download_file(setup_properties_last, setup_properties_local)
    
    if not result:
        wlogger.log(task_id, "setup.properties.last could not be dowloade. Ending analization of server.", 'error')
        return False

    load_balancer = ConfigParam.get('load_balancer')
    prop = get_setup_properties()
    prop['hostname'] = load_balancer.data.hostname
    write_setup_properties_file(prop)

    server.ldap_password = prop['ldapPass']
    wlogger.log(task_id, "LDAP Bind password was identifed", 'success')
    make_opendj_listen_world(server, installer)

@celery.task(bind=True)
def wizard_step2(self):
    tid = self.request.id

    setup_prop = get_setup_properties()

    server = ConfigParam.get_primary_server()
    settings = ConfigParam.get('settings')
    load_balancer = ConfigParam.get('load_balancer')

    c = RemoteClient(server.data.hostname, ip=server.data.ip)

    wlogger.log(tid, "Making SSH Connection")

    try:
        c.startup()
        wlogger.log(tid, "SSH connection established", 'success')
    except:
        wlogger.log(tid, "Can't establish SSH connection",'fail')
        wlogger.log(tid, "Ending changing name.", 'error')
        return

    name_changer = ChangeGluuHostname(
            old_host = server.data.hostname,
            new_host = load_balancer.data.hostname,
            cert_city = setup_prop['city'],
            cert_mail = setup_prop['admin_email'], 
            cert_state = setup_prop['state'],
            cert_country = setup_prop['countryCode'],
            server = server.data.hostname,
            ip_address = server.data.ip,
            ldap_password = setup_prop['ldapPass'],
            os_type = server.data.os,
            gluu_version = settings.data.gluu_version
        )

    name_changer.logger_tid = tid
    name_changer.server_id = server.id

    r = name_changer.startup()
    if not r:
        wlogger.log(tid, "Name changer can't be started",'fail')
        wlogger.log(tid, "Ending changing name.", 'error')
        return


    wlogger.log(tid, "Cahnging LDAP Entries")
    name_changer.change_ldap_entries()
    wlogger.log(tid, "LDAP Entries were changed", 'success')
    
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

    server.data.gluu_server = True
    server.save()

    name_changer.installer.restart_gluu()
    
