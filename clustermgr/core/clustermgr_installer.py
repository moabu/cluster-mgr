import sys
import os

from clustermgr.extensions import wlogger
from clustermgr.core.remote import RemoteClient

class Installer:
    def __init__(self, c, gluu_version, server_os=None, logger_tid=None, server_id=None):
        self.c = c
        self.logger_tid = logger_tid
        self.gluu_version = gluu_version
        self.server_os = server_os
        self.server_id=server_id
        
        if not "RemoteClient" in str(type(c)):
            self.server_os = c.os
            self.server_id = c.id
            self.c = RemoteClient(c.hostname, c.ip)


            wlogger.log(
                        self.logger_tid, 
                        "Making SSH connection to {} ...".format(c.hostname),
                        'action',
                        server_id=self.server_id,
                        )

            
            try:
                self.c.startup()
                wlogger.log(
                        self.logger_tid, 
                        "SSH connection to {} was successful.".format(c.hostname),
                        'success',
                        server_id=self.server_id,
                        )
            except:
                self.c = None
                wlogger.log(
                        self.logger_tid, 
                        "Can't make SSH connection to {}".format(c.hostname),
                        'fail',
                        server_id=self.server_id,
                    )
                
        if self.c and (not hasattr(self.c, 'fake_remote')):
            
            self.container = '/opt/gluu-server-{}'.format(gluu_version)
        
            if ('Ubuntu' in self.server_os) or ('Debian' in self.server_os):
                self.run_command = 'chroot {} /bin/bash -c "{}"'.format(self.container,'{}')
                self.install_command = 'chroot {} /bin/bash -c "DEBIAN_FRONTEND=noninteractive apt-get install -y {}"'.format(self.container,'{}')
            elif ('CentOS' in self.server_os) or ( 'RHEL' in self.server_os):
                self.run_command = ('ssh -o IdentityFile=/etc/gluu/keys/gluu-console '
                                '-o Port=60022 -o LogLevel=QUIET -o '
                                'StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
                                '-o PubkeyAuthentication=yes root@localhost \'{}\''
                                )
            
            self.install_command = self.run_command.format('yum install -y {}')
        else:
            self.run_command = '{}'

    def log(self, result, error_exception):
        if self.logger_tid:
            if result[1].strip():
                wlogger.log(self.logger_tid, result[1].strip(), 'debug', server_id=self.server_id)
            if result[2].strip():
                if error_exception:
                    if (error_exception == '__ALL__') or error_exception in result[2]:
                        wlogger.log(self.logger_tid, result[2].strip(), 'debug', server_id=self.server_id)
                        return

                wlogger.log(self.logger_tid, result[2].strip(), 'error', server_id=self.server_id)

    def log_command(self, cmd):
        if self.logger_tid:
            wlogger.log(self.logger_tid, "Running {}".format(cmd), 'debug', server_id=self.server_id)



    def run(self, cmd, error_exception=None):
        print "Installer> executing: {}".format(cmd)
        run_cmd = self.run_command.format(cmd)
        self.log_command(run_cmd)
        result = self.c.run(run_cmd)
        self.log(result, error_exception)
        
        return result

    def is_gluu_installed(self):
        
        check_file = ('/opt/gluu-server-{}/install/community-edition-setup/'
                  'setup.properties.last').format(
                                                self.gluu_version
                                            )
        print "Installer> Checking existence of file {} for gluu installation".format(check_file)


        return self.c.exists(check_file)


    def install(self, package):
        run_cmd = self.install_command.format(package)
        print "Installer> executing: {}".format(run_cmd)
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
        
        print "Installer> executing: {}".format(cmd)
        self.log_command(cmd)
        result = self.c.run(cmd)
        self.log(result)
        return result
