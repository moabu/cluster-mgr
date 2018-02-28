import sys
import os

class Installer:
    def __init__(self, c, gluu_version, server_os):
        self.c = c
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

    def run(self, cmd):
        print "Installer> executing:", cmd
        run_cmd = self.run_command.format(cmd)
        return self.c.run(run_cmd)

    def install(self, package):
        run_cmd = self.install_command.format(package)
        print "Installer> executing:", run_cmd
        return self.c.run(run_cmd)

