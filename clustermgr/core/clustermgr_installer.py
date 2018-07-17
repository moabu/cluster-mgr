import sys
import os
import re
import select

from clustermgr.extensions import wlogger
from clustermgr.core.remote import RemoteClient

class Installer:
    def __init__(self, conn, gluu_version, server_os=None, logger_task_id=None, server_id=None):
        self.conn = conn
        self.logger_task_id = logger_task_id
        self.gluu_version = gluu_version
        self.server_os = server_os
        self.server_id=server_id

        if self.server_os == 'CentOS 7' or self.server_os == 'RHEL 7':
            self.init_command = '/sbin/gluu-serverd-{0} {1}'.format(
                                self.gluu_version,'{}')
        else:
            self.init_command = '/etc/init.d/gluu-server-{0} {1}'.format(
                                self.gluu_version,'{}')

        if not "RemoteClient" in str(type(conn)):
            self.server_os = conn.os
            self.server_id = conn.id
            self.conn = RemoteClient(conn.hostname, conn.ip)
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
            except:
                self.conn = None
                wlogger.log(
                        self.logger_task_id, 
                        "Can't make SSH connection to {}".format(conn.hostname),
                        'fail',
                        server_id=self.server_id,
                    )
        
        if self.conn and not self.server_os:
            self.get_os_type()
        
        if self.conn and (not hasattr(self.conn, 'fake_remote')):
            
            self.container = '/opt/gluu-server-{}'.format(gluu_version)
        
            if ('Ubuntu' in self.server_os) or ('Debian' in self.server_os):
                self.packager = 'DEBIAN_FRONTEND=noninteractive apt-get install -y {}'
                self.run_command = 'chroot {} /bin/bash -c "{}"'.format(self.container,'{}')
                self.install_command = 'chroot {} /bin/bash -c "DEBIAN_FRONTEND=noninteractive apt-get install -y {}"'.format(self.container,'{}')
            elif ('CentOS' in self.server_os) or ( 'RHEL' in self.server_os):
                self.packager = 'yum install -y {}'
                
                self.run_command = ('ssh -o IdentityFile=/etc/gluu/keys/gluu-console '
                                '-o Port=60022 -o LogLevel=QUIET -o '
                                'StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
                                '-o PubkeyAuthentication=yes root@localhost \'{}\''
                                )

                self.install_command = self.run_command.format('yum install -y {}')
        else:
            self.run_command = '{}'

    def get_os_type(self):
        # 2. Linux Distribution of the server
        print "Installer> Determining os type"
        self.server_os = self.conn.get_os_type()
        return self.server_os

    def log(self, result, error_exception=None):
        if self.logger_task_id:
            if result[1].strip():
                wlogger.log(self.logger_task_id, result[1].strip(), 'debug', server_id=self.server_id)
            if result[2].strip():
                if error_exception:
                    if (error_exception == '__ALL__') or error_exception in result[2]:
                        wlogger.log(self.logger_task_id, result[2].strip(), 'debug', server_id=self.server_id)
                        return

                wlogger.log(self.logger_task_id, result[2].strip(), 'error', server_id=self.server_id)

    def log_command(self, cmd):
        if self.logger_task_id:
            wlogger.log(self.logger_task_id, "Running {}".format(cmd), 'debug', server_id=self.server_id)



    def run(self, cmd, inside=True, error_exception=None):
        if inside:
            run_cmd = self.run_command.format(cmd)
        else:
            run_cmd = cmd

        print "Installer> executing: {}".format(cmd)
        self.log_command(run_cmd)
        result = self.conn.run(run_cmd)
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

        print "Starting channel loop"
        while True:
            if channel.exit_status_ready():
                print "Stopping channel loop"
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
        if ('CentOS' in self.server_os) or ('RHEL' in self.server_os):
            wlogger.log(self.logger_task_id, "Installing epel-release", server_id=self.server_id)
            self.install('epel-release', inside=inside)

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


    def get_file(self, remote):
        print "Installer> Retreiving remote file {}".format(remote)
        wlogger.log(self.logger_task_id, "Getting file {0} from {1}".format(remote, self.hostname), "debug", server_id=self.server_id)
        result = self.conn.get_file(remote)
        if not result[0]:
            wlogger.log(self.logger_task_id, "Can't retreive file {0} from server {1}".format(remote,result[1]), "error", server_id=self.server_id)
            wlogger.log(self.logger_task_id, "Ending up current process.", "error", server_id=self.server_id)
            return False
        wlogger.log(self.logger_task_id, "File {} was retreived.".format(remote), "success", server_id=self.server_id)
        
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

    def enable_service(self, service, inside=True):
        self.run('systemctl enable {}.service'.format(service), inside=inside)

    def stop_service(self, service, inside=True):
        self.run('systemctl stop '+service, inside=inside)

    def start_service(self, service, inside=True):
        self.run('systemctl start '+service, inside=inside)


    def is_gluu_installed(self):
        
        check_file = ('/opt/gluu-server-{}/install/community-edition-setup/'
                  'setup.properties.last').format(
                                                self.gluu_version
                                            )
        print "Installer> Checking existence of file {} for gluu installation".format(check_file)


        return self.conn.exists(check_file)


    def get_install_cmd(self, package, inside=True):
        if inside:
            run_cmd = self.install_command.format(package)
        else:
            run_cmd = self.packager.format(package)
        return run_cmd
        

    def install(self, package, inside=True):

        cmd = self.get_install_cmd(package, inside)

        print "Installer> executing: {}".format(cmd)

        result = self.conn.run(cmd)
        self.log(result)
        
        return result

    def remove(self, package, inside=True):
        if inside:
            run_cmd = self.install_command.replace('install', 'remove').format(package)
        else:
            run_cmd = self.packager.replace('install', 'remove').format(package)

        print "Installer> executing: {}".format(run_cmd)
        self.log_command(run_cmd)
        result = self.conn.run(run_cmd)
        self.log(result)
        
        return result

    def do_init(self, cmd):
        cmd=self.init_command.format(cmd)
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
        """Delted key of identity server

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
