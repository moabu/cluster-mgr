# -*- coding: utf-8 -*-

import os
import re
import time
import subprocess

from flask import current_app as app

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import wlogger, db, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.config import Config


from clustermgr.core.clustermgr_installer import Installer
from clustermgr.core.utils import get_setup_properties



@celery.task(bind=True)
def install_gluu_server_step_1(self, server_id):

    tid = self.request.id


    server = Server.query.get(server_id)
    primary_server = Server.query.filter_by(primary_server=True).first()

    appconf = AppConfiguration.query.first()

    # local setup properties file path
    setup_properties_file = os.path.join(Config.DATA_DIR, 'setup.properties')


    # get setup properties
    setup_prop = get_setup_properties()


    # If os type of this server was not idientified, return to home
    if not server.os:
        wlogger.log(tid, "OS type has not been identified.", 'fail')
        return False


    # If this is not primary server, we will download setup.properties
    # file from primary server
    if not server.primary_server:
        wlogger.log(tid, "Check if Primary Server is Installed", 'head')

        primary_server_installer = Installer(
                                primary_server,
                                appconf.gluu_version,
                                logger_tid=tid
                            )

        if not primary_server_installer.c:
            wlogger.log(tid, "Primary server is not installed.", "fail")
            return False
        else:
            wlogger.log(tid, "Primary server is installed.", "success")


    wlogger.log(tid, "Preparing Server for installation", 'head')
    installer = Installer(server, appconf.gluu_version, logger_tid=tid)
    if not installer.c:
        return False

    #add gluu server repo and imports signatures
    if ('Ubuntu' in server.os) or ('Debian' in server.os):

        if server.os == 'Ubuntu 14':
            dist = 'trusty'
        elif server.os == 'Ubuntu 16':
            dist = 'xenial'


        if 'Ubuntu' in server.os:
            cmd = 'curl https://repo.gluu.org/ubuntu/gluu-apt.key | apt-key add -'
        elif 'Debian' in server.os:
            cmd = 'curl https://repo.gluu.org/debian/gluu-apt.key | apt-key add -'

        installer.run(cmd)

        if 'Ubuntu' in server.os:
            cmd = ('echo "deb https://repo.gluu.org/ubuntu/ {0}-devel main" '
               '> /etc/apt/sources.list.d/gluu-repo.list'.format(dist))
        elif 'Debian' in server.os:
            cmd = ('echo "deb https://repo.gluu.org/debian/ stable main" '
               '> /etc/apt/sources.list.d/gluu-repo.list')

        installer.run(cmd)

        cmd = 'DEBIAN_FRONTEND=noninteractive apt-get update'
        cin, cout, cerr = installer.run(cmd)
        
        if 'dpkg --configure -a' in cerr:
            cmd = 'dpkg --configure -a'
            wlogger.log(tid, cmd, 'debug')
            installer.run(cmd)

    elif 'CentOS' in server.os or 'RHEL' in server.os:
        if not installer.c.exists('/usr/bin/wget'):
            installer.install('wget')

        if server.os == 'CentOS 6':
            cmd = 'wget https://repo.gluu.org/centos/Gluu-centos6.repo -O /etc/yum.repos.d/Gluu.repo'
        elif server.os == 'CentOS 7':
            
            cmd = 'wget https://repo.gluu.org/centos/Gluu-centos7.repo -O /etc/yum.repos.d/Gluu.repo'            
            
        elif server.os == 'RHEL 7':
            cmd = 'wget https://repo.gluu.org/rhel/Gluu-rhel7.repo -O /etc/yum.repos.d/Gluu.repo'

        installer.run(cmd, error_exception='__ALL__')

        cmd = 'wget https://repo.gluu.org/centos/RPM-GPG-KEY-GLUU -O /etc/pki/rpm-gpg/RPM-GPG-KEY-GLUU'
        installer.run(cmd, error_exception='__ALL__')

        cmd = 'rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-GLUU'
        installer.run(cmd, error_exception='__ALL__')

        cmd = 'yum clean all'
        installer.run(cmd, error_exception='__ALL__')
