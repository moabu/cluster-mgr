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

#Fake RemoteClient
class FakeRemote:
    
    """Provides fake remote class with the same run() function.
    """

    def run(self, cmd):
        
        """This method executes cmd as a sub-process.

        Args:
            cmd (string): commands to run locally
        
        Returns:
            Standard input, output and error of command
        
        """
        print cmd
        cin, cout, cerr = os.popen3(cmd)

        return '', cout.read(), cerr.read()


    def put_file(self, filename, filecontent):
        with open(filename, 'w') as f:
            f.write(filecontent)

    def rename(self, oldname, newname):
        os.rename(oldname, newname)

    def get_file(self, filename):
        return True, open(filename)
