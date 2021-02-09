import sys
import os
import re
import select

from clustermgr.extensions import wlogger
from clustermgr.core.remote import RemoteClient

class Installer:
    def __init__(self, conn, gluu_version, server_os=None, logger_task_id=None, server_id=None, ssh_port=22):
        self.conn = conn
        self.logger_task_id = logger_task_id
        self.gluu_version = gluu_version
        self.server_os = server_os
        self.server_id = server_id
        self.repo_updated = {False:False, True:False}
        self.ssh_port = ssh_port
        self.clone_type = None
        self.hostname = ''

        if conn.__class__.__name__ != "RemoteClient" and conn.__class__.__name__ != 'FakeRemote':
            self.server_os = conn.os
            self.server_id = conn.id
            self.conn = RemoteClient(conn.hostname, conn.ip, ssh_port=self.ssh_port)
            self.hostname = conn.hostname
            self.ip = conn.ip

            wlogger.log(
                        self.logger_task_id, 
                        "Making SSH connection to {} ...".format(conn.hostname),
                        'action',
                        server_id=self.server_id,
                        )
            try:
                print "Installer> Establishing SSH connection to host {}".format(conn.hostname)
                self.conn.startup()
                wlogger.log(
                        self.logger_task_id, 
                        "SSH connection to {} was successful.".format(conn.hostname),
                        'success',
                        server_id=self.server_id,
                        )
    
            except Exception as e:
                print e
                self.conn = None
                if str(e) == 'Pubkey is encrypted.':
                    error_msg = ("Pubkey seems to password protected. "
                        "After setting your passphrase re-submit this form.")
                        
                elif str(e) == 'Could not deserialize key data.':
                    error_msg = ("Password you provided for pubkey did not work. "
                        "After setting your passphrase re-submit this form.")
                else:
                    error_msg = str(e)
            
                wlogger.log(
                        self.logger_task_id, 
                        "Can't make SSH connection to {}. Reason: {}".format(conn.hostname, error_msg),
                        'fail',
                        server_id=self.server_id,
                    )
        
        if self.conn and not self.server_os:
            self.get_os_type()
    
        self.settings()
    
    @property
    def os_version(self):
        return self.server_os.split()[1]
    
    def settings(self):


        self.init_command = '/sbin/gluu-serverd {0}'
        self.service_script = 'systemctl {1} {0}'


        if ('Ubuntu' in self.server_os) or ('Debian' in self.server_os):
            self.clone_type = 'deb'
            self.packager = 'DEBIAN_FRONTEND=noninteractive apt-get install -y {}'
        elif ('CentOS' in self.server_os) or ('RHEL' in self.server_os):
            self.clone_type = 'rpm'
            self.packager = 'yum install -y {}'


        if self.gluu_version and self.gluu_version.startswith('nochroot'):
            self.run_command = '{}'
            self.container = '/'
        elif self.conn.__class__.__name__ != 'FakeRemote':
            self.container = '/opt/gluu-server'

            self.run_command = (
                    'ssh -q -o IdentityFile=/etc/gluu/keys/gluu-console '
                    '-o UserKnownHostsFile=/dev/null '
                    '-o Port=60022 -o StrictHostKeyChecking=no '
                    '-o PubkeyAuthentication=yes root@localhost  "{0}"'
                    )

        else:
            self.run_command = '{}'

        if self.clone_type == 'deb':
            self.install_command = self.run_command.format('DEBIAN_FRONTEND=noninteractive apt-get install -y {}')
        elif self.clone_type == 'rpm':
            self.install_command = self.run_command.format('yum install -y {}')

    def get_os_type(self):
        # 2. Linux Distribution of the server
        print "Installer> Determining OS type"
        self.server_os = self.conn.get_os_type()
        print "Installer> OS type was determined as " + self.server_os
        return self.server_os

    def log(self, result, error_exception=None):
        if self.logger_task_id:
            if result[1].strip():
                wlogger.log(self.logger_task_id, result[1].strip(), 'debug', server_id=self.server_id)
            if result[2].strip() and error_exception:
                if (error_exception == '__ALL__') or error_exception in result[2]:
                    message_type = 'debug'
                else:
                    message_type = 'error'

                wlogger.log(self.logger_task_id, result[2].strip(), message_type, server_id=self.server_id)

    def log_command(self, cmd):
        if self.logger_task_id:
            wlogger.log(self.logger_task_id, "Running {}".format(cmd), 'debug', server_id=self.server_id)



    def run(self, cmd, inside=True, error_exception=None, nolog=False):
        if self.gluu_version and self.gluu_version.startswith('nochroot'):
            inside = False

        if inside:
            run_cmd = self.run_command.format(cmd)
        else:
            run_cmd = cmd

        if self.conn.__class__.__name__ == 'FakeRemote':
            run_cmd = 'sudo '+ cmd

        print "Installer> executing: {}".format(cmd)
        self.log_command(run_cmd)
        result = self.conn.run(run_cmd)
        if not nolog:
            self.log(result, error_exception)

        return result

    def run_channel_command(self, cmd, re_list=[]):
    
        print "Installer> executing channel command: {}".format(cmd)
        wlogger.log(self.logger_task_id, "Running "+cmd, "debug", server_id=self.server_id)
        
        last_debug = False
        log_id = 0
        
        all_cout = []
        
        channel = self.conn.client.get_transport().open_session()
        channel.get_pty()
        channel.exec_command(cmd)

        print "Installer> Starting channel loop"
        while True:
            if channel.exit_status_ready():
                print "Installer> Stopping channel loop"
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
                        all_cout.append(cout)
                        if cout.strip():
                            
                            repeated_line = False
                            for reg in re_list:
                                if reg.search(cout):
                                    repeated_line = True
                                    break
                            if repeated_line:
                                if not last_debug:
                                    cout = cout.strip()
                                    wlogger.log(self.logger_task_id, "...", "debug", log_id="logc-{}".format(log_id), new_log_id=True,  server_id=self.server_id)
                                    last_debug = True
                                wlogger.log(self.logger_task_id, cout, "debugc", log_id="logc-{}".format(log_id),  server_id=self.server_id)
                            else:
                                log_id += 1
                                last_debug = False
                                wlogger.log(self.logger_task_id, cout, "debug",  server_id=self.server_id)

        return '\n'.join(all_cout), log_id


    def epel_release(self, inside=False):
        if self.clone_type == 'rpm':
            wlogger.log(self.logger_task_id, "Installing epel-release", server_id=self.server_id)
            self.run('yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm', inside=inside, error_exception='__ALL__')
            self.run('yum repolist', inside=inside, error_exception="Trying other mirror")

    def upload_file(self, local, remote):
        print "Installer> Uploading local {} to remote {}".format(local, remote)
        wlogger.log(self.logger_task_id, "Uploading local file {0} to remote server as {1}".format(local, remote), "debug", server_id=self.server_id)
        result = self.conn.upload(local, remote)

        if not result[0]:
            wlogger.log(self.logger_task_id, "Can't upload. {0}".format(result[1]), "error", server_id=self.server_id)
            wlogger.log(self.logger_task_id, "Ending up current process.", "error", server_id=self.server_id)
            return False

        wlogger.log(self.logger_task_id, "File {0} was uploaded as {1}.".format(local, remote), "success", server_id=self.server_id)

        return True

    def download_file(self, remote, local):
        print "Installer> Downloading from {} remote {} to local {}".format(self.hostname, remote,local)
        wlogger.log(self.logger_task_id, "Downloading remote file {0} to local {1}".format(remote, local), "debug", server_id=self.server_id)
        result = self.conn.download(remote, local)

        if not result[0]:
            wlogger.log(self.logger_task_id, "Can't download. {0}".format(result[1]), "error", server_id=self.server_id)
            wlogger.log(self.logger_task_id, "Ending up current process.", "error", server_id=self.server_id)
            return False

        wlogger.log(self.logger_task_id, "File {0} was downloaded as {1}.".format(remote, local), "success", server_id=self.server_id)

        return True


    def get_file(self, remote, asio=False):
        print "Installer> Retreiving remote file {}".format(remote)
        wlogger.log(self.logger_task_id, "Getting file {0} from {1}".format(remote, self.hostname), "debug", server_id=self.server_id)
        result = self.conn.get_file(remote)

        if result[0] is False:
            wlogger.log(self.logger_task_id, "Can't retreive file {0} from server {1}".format(remote,result[1]), "error", server_id=self.server_id)
            wlogger.log(self.logger_task_id, "Ending up current process.", "error", server_id=self.server_id)
            return False

        wlogger.log(self.logger_task_id, "File {} was retreived.".format(remote), "success", server_id=self.server_id)
        
        if asio:
            return result[1]

        return result[1].read()
    
    def put_file(self, remote, content):
        print "Installer> Writing remote file {}".format(remote)
        result = self.conn.put_file(remote, content)
        if result[0]:
            wlogger.log(self.logger_task_id, "File {} was sent".format(remote), "success", server_id=self.server_id)
            return True
        else:
            wlogger.log(self.logger_task_id, "Can't send file {0} to server: {1}".format(remote, result[1]), "error", server_id=self.server_id)
            wlogger.log(self.logger_task_id, "Ending up current process.", "error", server_id=self.server_id)
            return False

    def enable_service(self, service, inside=True, enable=True):

        condition = 'enable' if enable else 'disable'

        error_exception =  'Created symlink from' if enable else 'Removed symlink'
        self.run(self.service_script.format(service, condition), inside=inside, error_exception=error_exception)

    def stop_service(self, service, inside=True):
        cmd = self.service_script.format(service, 'stop')
        self.run(cmd, inside=inside)

    def start_service(self, service, inside=True):
        cmd = self.service_script.format(service, 'start')
        self.run(cmd, inside=inside, error_exception='Redirecting to /bin/systemctl')

    def restart_service(self, service, inside=True):
        cmd = self.service_script.format(service, 'restart')
        self.run(cmd, inside=inside, error_exception='Redirecting to /bin/systemctl')


    def is_gluu_installed(self):
        
        check_file = ('/opt/gluu-server/install/community-edition-setup/'
                  'setup.properties.last')

        check_file_enc = ('/opt/gluu-server/install/community-edition-setup/'
                    'setup.properties.last.enc')

        print "Installer> Checking existence of file {} for gluu installation".format(check_file)

        return self.conn.exists(check_file) or self.conn.exists(check_file_enc)

    def get_gluu_version(self, installed=False):
        gluu_version = None
        
        print "Installer> Determining gluu version by using oxauth.war"
        
        oxauth_path = '/opt/gluu/jetty/oxauth/webapps/oxauth.war'
        
        if installed and not self.conn.exists(self.container + oxauth_path):
            oxauth_path = '/opt/dist/gluu/oxauth.war'
            
        
        if self.conn.exists(self.container + oxauth_path):
            result = self.run('''python -c \\"import zipfile;zf=zipfile.ZipFile('{}','r');print zf.read('META-INF/MANIFEST.MF')\\"'''.format(oxauth_path))

            menifest = result[1]

            for l in menifest.split('\n'):
                ls = l.strip()
                if 'Implementation-Version:' in ls:
                    version = ls.split(':')[1].strip()
                    gluu_version = '.'.join(version.split('.')[:3])
                    print "Installer> Gluu version was determined as {0}".format(gluu_version)

        return gluu_version


    def get_install_cmd(self, package, inside=True):
        if inside:
            run_cmd = self.install_command.format(package)
        else:
            run_cmd = self.packager.format(package)
        return run_cmd
        

    def install(self, package, inside=True, error_exception=None):

        if not self.repo_updated[inside]:
            if self.clone_type == 'rpm':
                self.run('yum makecache fast', inside)
                self.run('yum clean all', inside)
                self.run('yum repolist', inside)
            else:
                self.run('DEBIAN_FRONTEND=noninteractive apt-get update', inside)
                self.run('DEBIAN_FRONTEND=noninteractive apt-get install -y apt-utils', inside, error_exception='debconf:')
            self.repo_updated[inside] = True

        if package.endswith('-dev'):
            if self.clone_type == 'rpm':
                package += 'el'

        cmd = self.get_install_cmd(package, inside)

        if self.conn.__class__.__name__ == 'FakeRemote':
            cmd = 'sudo '+ cmd

        print "Installer> executing: {}".format(cmd)

        wlogger.log(self.logger_task_id, "Installing package {0} with command: {1}".format(package, cmd), "debug", server_id=self.server_id)
        
        
        result = self.run(cmd, inside=False, error_exception=error_exception)
        self.log(result)
        
        return result

    def remove(self, package, inside=True):
        if inside:
            run_cmd = self.install_command.replace('install', 'remove').format(package)
        else:
            run_cmd = self.packager.replace('install', 'remove').format(package)

        if self.conn.__class__.__name__ == 'FakeRemote':
            run_cmd = 'sudo '+ run_cmd

        print "Installer> executing: {}".format(run_cmd)
        self.log_command(run_cmd)
        result = self.conn.run(run_cmd)
        self.log(result)
        
        return result

    def do_init(self, cmd):
        cmd = self.init_command.format(cmd)
        print "Installer> executing: {}".format(cmd)
        self.log_command(cmd)
        result = self.conn.run(cmd)
        self.log(result)
        return result
        

    def stop_gluu(self):
        return self.do_init('stop')


    def start_gluu(self):
        return self.do_init('start')

    def restart_gluu(self):
        wlogger.log(self.logger_task_id,'Restarting Gluu Server on server ' + self.hostname, server_id=self.server_id)
        return self.do_init('restart')

    def delete_key(self, suffix, hostname):
        """Delete key of identity server

        Args:
            suffix (string): suffix of the key to be imported
        """
        defaultTrustStorePW = 'changeit'
        defaultTrustStoreFN = '/opt/jre/jre/lib/security/cacerts'
        cert = 'etc/certs/{0}.crt'.format(suffix)

        if self.conn.exists(os.path.join(self.container, cert)):
            cmd=' '.join([
                            '/opt/jre/bin/keytool', "-delete", "-alias",
                            "%s_%s" % (hostname, suffix),
                            "-keystore", defaultTrustStoreFN,
                            "-storepass", defaultTrustStorePW
                            ])
            self.run(cmd)


    def import_key(self, suffix, hostname):
        """Imports key for identity server

        Args:
            suffix (string): suffix of the key to be imported
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

        self.run(cmd, error_exception='Certificate was added to keystore')
