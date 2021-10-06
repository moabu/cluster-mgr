import json
import os
import getpass
import time

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.ldap_functions import DBManager
from clustermgr.core.clustermgr_installer import Installer
from clustermgr.core.remote import FakeRemote



from flask import current_app as app

from influxdb import InfluxDBClient


def fix_influxdb_config():
    conf_file = '/etc/influxdb/influxdb.conf'

    conf = open(conf_file).readlines()
    new_conf = []
    http = False
    
    for l in conf:
        if l.startswith('[http]'):
            http = True
        elif l.strip().startswith('[') and l.strip().endswith(']'):
            http = False
        
        if http:
            if 'bind-address' in l:
                l = '  bind-address = "localhost:8086"\n'
            elif '#enabled' in l.replace(' ',''):
                l = '  enabled = true\n'

        new_conf.append(l)

    with open('/tmp/influxdb.conf','w') as W:
        W.write(''.join(new_conf))
        
    os.system('sudo cp -f /tmp/influxdb.conf /etc/influxdb/influxdb.conf')


@celery.task(bind=True)
def install_local(self):
    
    """Celery task that installs monitoring components of local machine.

    :param self: the celery task

    :return: the number of servers where both stunnel and redis were installed
        successfully
    """
    
    app_conf = AppConfiguration.query.first()
    
    task_id = self.request.id
    servers = Server.get_all()
    
    #create fake remote class that provides the same interface with RemoteClient
    fc = FakeRemote()
    
    installer = Installer(
                conn=fc,
                gluu_version=None,
                server_id=0,
                logger_task_id=task_id,
                )
    
    #Determine local OS type
    localos= installer.server_os

    wlogger.log(task_id, "Local OS was determined as {}".format(localos), "success", server_id=0)

    if not localos == 'Alpine':
    
        if app_conf.offline:

            if not os.path.exists('/usr/bin/influxd'):
                wlogger.log(task_id, 
                            "Influxdb was installed on this machine. "
                            "Please install influxdb", "error", server_id=0)
                return False
        else:
            #commands to install influxdb on local machine for each OS type
            if 'Ubuntu' in localos:
                influx_cmd = [
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get update',
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get install -y curl',
                    'curl -sL https://repos.influxdata.com/influxdb.key | '
                    'sudo apt-key add -'
                    ]
                    
                if '14' in localos:
                    influx_cmd.append(
                    'echo "deb https://repos.influxdata.com/ubuntu '
                    'trusty stable" | sudo tee '
                    '/etc/apt/sources.list.d/influxdb.list')
                elif '16' in localos:
                    influx_cmd.append(
                    'echo "deb https://repos.influxdata.com/ubuntu '
                    'xenial stable" | sudo tee '
                    '/etc/apt/sources.list.d/influxdb.list')
                
                influx_cmd += [
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get update',
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get install influxdb',
                    'sudo service influxdb start',
                    'sudo pip3 install --upgrade setuptools',
                    'sudo pip3 install psutil==5.7.1',
                    'sudo pip3 install influxdb',
                    
                    ]
            
            elif 'Debian' in localos:
                influx_cmd = [
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get update',
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get install -y curl',
                    'curl -sL https://repos.influxdata.com/influxdb.key | '
                    'sudo apt-key add -']
                    
                if '7' in localos:
                    influx_cmd.append(
                    'echo "deb https://repos.influxdata.com/'
                    'debian wheezy stable" | sudo tee /etc/apt/sources.list.d/'
                    'influxdb.list')
                elif '8' in localos:
                    influx_cmd.append(
                    'echo "deb https://repos.influxdata.com/'
                    'debian jessie stable" | sudo tee /etc/apt/sources.list.d/'
                    'influxdb.list')
                
                influx_cmd += [
                    'sudo apt-get update',
                    'sudo apt-get -y remove influxdb',
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get -y install influxdb',
                    'sudo service influxdb start',
                    'sudo pip3 install influxdb',
                    'sudo pip3 install psutil',
                    ]

            elif localos in ('CentOS 8', 'CentOS 7', 'RHEL 7', 'RHEL 8'):
                influx_cmd = [
                                'sudo yum install -y epel-release',
                                'sudo yum repolist',
                                'sudo yum install -y curl',
                                'cat <<EOF | sudo tee /etc/yum.repos.d/influxdb.repo\n'
                                '[influxdb]\n'
                                'name = InfluxDB Repository - RHEL \$releasever\n'
                                'baseurl = https://repos.influxdata.com/rhel/\$releasever/\$basearch/stable\n'
                                'enabled = 1\n'
                                'gpgcheck = 1\n'
                                'gpgkey = https://repos.influxdata.com/influxdb.key\n'
                                'EOF',
                                'sudo yum remove -y influxdb',
                                'sudo yum install -y influxdb',
                                'sudo service influxdb start',
                                'sudo pip3 install psutil',
                            ]

            #run commands to install influxdb on local machine
            for cmd in influx_cmd:
                result = installer.run(cmd, error_exception='__ALL__', inside=False)
    
    wlogger.log(task_id, "Fixing /etc/influxdb/influxdb.conf for InfluxDB listen localhost", server_id=0)
    installer.stop_service('influxdb', inside=False)
    fix_influxdb_config()
    installer.start_service('influxdb', inside=False)
    #wait influxdb to start
    time.sleep(20)
    
    #Statistics will be written to 'gluu_monitoring' on local influxdb server,
    #so we should crerate it.
    try:
        client = InfluxDBClient(
                    host='localhost', 
                    port=8086, 
                    )
        client.create_database('gluu_monitoring')

        wlogger.log(task_id, "InfluxDB database 'gluu_monitoring was created",
                            "success", server_id=0)
    except Exception as e:
        wlogger.log(task_id, "An error occurred while creating InfluxDB database "
                        "'gluu_monitoring': {}".format(e),
                            "fail", server_id=0)

    #Flag database that configuration is done for local machine
    app_conf = AppConfiguration.query.first()
    app_conf.monitoring = True
    db.session.commit()

    return True


@celery.task(bind=True)
def install_monitoring(self):
    
    """Celery task that installs monitoring components to remote server.

    :param self: the celery task

    :return: wether monitoring were installed successfully
    """
    
    task_id = self.request.id
    installed = 0
    servers = Server.get_all()
    app_conf = AppConfiguration.query.first()
    
    for server in servers:
        # 1. Installer
        installer = Installer(
                server, 
                app_conf.gluu_version,
                ssh_port=server.ssh_port,
                logger_task_id=task_id, 
                server_os=server.os
                )

        # 2. create monitoring directory
        installer.run('mkdir -p /var/monitoring/scripts', inside=False)

        # 3. Upload scripts
        
        scripts = (
                    'cron_data_sqtile.py', 
                    'get_data.py', 
                    'sqlite_monitoring_tables.py'
                    )
        
        for script in scripts:
        
            local_file = os.path.join(app.root_path, 'monitoring_scripts', script)
                                        
            remote_file = '/var/monitoring/scripts/'+script

            if not installer.upload_file(local_file, remote_file):
                return False
                
        # 4. Upload crontab entry to collect data in every 5 minutes
        crontab_entry = (
                        '*/5 * * * *    root    python3 '
                        '/var/monitoring/scripts/cron_data_sqtile.py\n'
                        )
                        
        if not installer.put_file('/etc/cron.d/monitoring', crontab_entry):
            return False


        if app_conf.offline:
            # check if psutil and ldap3 was installed on remote server
            for py_mod in ('psutil', 'ldap3', 'pyDes'):
                result = installer.run("python3 -c 'import {0}'".format(py_mod), inside=False)
                if 'No module named' in result[2]:
                    wlogger.log(
                                task_id, 
                                "{0} module is not installed. Please "
                                "install python3-{0} and retry.".format(py_mod),
                                "error", server_id=server.id,
                                )
                    return False

        else:
            installer.epel_release()

            # 5. Installing packages. 
            # 5a. First determine commands for each OS type
            packages = ['gcc']
            if installer.clone_type == 'rpm' and installer.os_version == '8':
                packages += ['python3', 'python3-dev']
            else:
                packages += ['python3-dev']

            for package in packages:
                installer.install(package, inside=False, error_exception='warning:')

            # 5b. These commands are common for all OS types 
            commands = [
                            'curl https://bootstrap.pypa.io/get-pip.py > /tmp/get-pip.py',
                            'python3 /tmp/get-pip.py',
                            'pip3 install --upgrade setuptools',
                            'pip3 install psutil==5.7.1',
                            'pip3 install ldap3', 
                            'pip3 install pyDes',
                            'python3 /var/monitoring/scripts/'
                            'sqlite_monitoring_tables.py'
                            ]

            if installer.clone_type == 'deb':
                commands.append('service cron restart')
            else:
                commands.append('service crond restart')

            # 5c. Executing commands
            wlogger.log(task_id, "Installing Packages and Running Commands", 
                                "info", server_id=server.id)
            
            for cmd in commands:
                
                result = installer.run(cmd, inside=False, error_exception='__ALL__')
            
        server.monitoring = True

    db.session.commit()
    return True

@celery.task(bind=True)
def remove_monitoring(self):
    
    """Celery task that removes monitoring components to remote server.

    :param self: the celery task

    :return: wether monitoring were removed successfully
    """
    task_id = self.request.id
    installed = 0
    servers = Server.get_all()
    app_conf = AppConfiguration.query.first()
    for server in servers:
        # 1. Installer
        installer = Installer(
                server, 
                app_conf.gluu_version,
                ssh_port=server.ssh_port,
                logger_task_id=task_id, 
                server_os=server.os
                )
        
        # 2. remove monitoring directory
        installer.run('rm -r /var/monitoring/', inside=False)

        # 3. remove crontab entry to collect data in every 5 minutes
        installer.run('rm /etc/cron.d/monitoring', inside=False)

        # 4. Restarting crontab
        if installer.clone_type == 'rpm':
            installer.restart_service('crond', inside=False)
        else:
            installer.restart_service('cron', inside=False)

        server.monitoring = False

    # 5. Remove local settings
    
    #create fake remote class that provides the same interface with RemoteClient
    fc = FakeRemote()

    installer = Installer(
            conn=fc,
            gluu_version=None,
            server_id=9999,
            logger_task_id=task_id,
            )

    installer.remove('influxdb', inside=False)

    #Flag database that configuration is done for local machine
    app_conf.monitoring = False
    db.session.commit()

    return True
