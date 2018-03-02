import sys
import os

from clustermgr.extensions import wlogger

class Installer:
    def __init__(self, c, gluu_version, server_os, logger_tid=None):
        self.c = c
        self.logger_tid = logger_tid
        self.gluu_version = gluu_version
        self.server_os = server_os
        if not hasattr(self.c, 'fake_remote'):
            
            self.container = '/opt/gluu-server-{}'.format(gluu_version)
        
            if ('Ubuntu' in self.server_os) or ('Debian' in self.server_os):
                self.run_command = 'chroot {} /bin/bash -c "{}"'.format(self.container,'{}')
                self.install_command = 'chroot {} /bin/bash -c "apt-get install -y {}"'.format(self.container,'{}')
            elif 'CentOS' in self.server_os:
                self.run_command = ('ssh -o IdentityFile=/etc/gluu/keys/gluu-console '
                                '-o Port=60022 -o LogLevel=QUIET -o '
                                'StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
                                '-o PubkeyAuthentication=yes root@localhost \'{}\''
                                )
            
            self.install_command = self.run_command.format('yum install -y {}')
        else:
            self.run_command = '{}'

    def log(self, result):
        if self.logger_tid:
            print "LOGGER", self.logger_tid, result
            if result[1]:
                wlogger.log(self.logger_tid, result[1], 'debug')
            if result[2]:
                wlogger.log(self.logger_tid, result[2], 'debug')

    def log_command(self, cmd):
        if self.logger_tid:
            wlogger.log(self.logger_tid, "Running {}".format(cmd), 'debug')
            


    def run(self, cmd):
        print "Installer> executing:", cmd
        run_cmd = self.run_command.format(cmd)
        self.log_command(run_cmd)
        result = self.c.run(run_cmd)
        self.log(result)
        
        return result

    def install(self, package):
        run_cmd = self.install_command.format(package)
        print "Installer> executing:", run_cmd
        self.log_command(cmd)
        result = self.c.run(run_cmd)
        self.log(result)
        
        return result

    def restart_gluu(self):
        if self.server_os == 'CentOS 7' or self.server_os == 'RHEL 7':
            cmd = '/sbin/gluu-serverd-{0} restart'.format(
                                self.gluu_version)
        else:
            cmd = '/etc/init.d/gluu-server-{0} restart'.format(
                                self.gluu_version)
        
        print "Installer> executing:", cmd
        self.log_command(cmd)
        result = self.c.run(cmd)
        self.log(result)
        return result
