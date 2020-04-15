import json
import os
import getpass
import time

from clustermgr.models import ConfigParam
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
    
    task_id = self.request.id
    settings = ConfigParam.get('settings')
    servers = ConfigParam.get_servers()
    monitoring_settings = ConfigParam.get('monitoring')

    #create fake remote class that provides the same interface with RemoteClient
    fc = FakeRemote()
    
    installer = Installer(
                conn=fc,
                server_id=0,
                logger_task_id=task_id,
                )
    
    #Determine local OS type
    localos= installer.server_os

    wlogger.log(task_id, "Local OS was determined as {}".format(localos), "success", server_id=0)

    if not localos == 'Alpine':
    
        if settings.data.offline:

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

                if '16' in localos:
                    os_name = 'xenial'
                elif '18' in localos:
                    os_name = 'bionic'

                influx_cmd.append(
                    ('echo "deb https://repos.influxdata.com/ubuntu '
                    '{} stable" | sudo tee '
                    '/etc/apt/sources.list.d/influxdb.list').format(os_name)
                    )

                influx_cmd += [
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get update',
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get install influxdb',
                    'sudo service influxdb start',
                    'sudo pip3 install influxdb',
                    'sudo pip3 install psutil',
                    ]
            
            elif 'Debian' in localos:
                influx_cmd = [
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get update',
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get install -y curl',
                    'curl -sL https://repos.influxdata.com/influxdb.key | '
                    'sudo apt-key add -']

                if '8' in localos:
                    os_name = 'jessie'
                elif '9' in localos:
                    os_name = 'stretch'
                   
                influx_cmd.append(
                    ('echo "deb https://repos.influxdata.com/'
                    'debian {} stable" | sudo tee /etc/apt/sources.list.d/'
                    'influxdb.list').format(os_name)
                    )

                influx_cmd += [
                    'sudo apt-get update',
                    'sudo apt-get -y remove influxdb',
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get -y install influxdb',
                    'sudo service influxdb start',
                    'sudo pip3 install influxdb',
                    'sudo pip3 install psutil',
                    ]

            elif localos in ('CentOS 7', 'RHEL 7'):
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
    if not monitoring_settings:
        monitoring_settings = ConfigParam.new('monitoring')
    monitoring_settings.data.monitoring = True
    monitoring_settings.save()

    return True


@celery.task(bind=True)
def install_monitoring(self):
    
    """Celery task that installs monitoring components to remote server.

    :param self: the celery task

    :return: wether monitoring were installed successfully
    """
    
    task_id = self.request.id
    installed = 0
    
    settings = ConfigParam.get('settings')
    servers = ConfigParam.get_servers()
    monitoring_settings = ConfigParam.get('monitoring')

    for server in servers:
        # 1. Installer
        installer = Installer(
                server, 
                logger_task_id=task_id, 
                server_os=server.data.os
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


        if settings.data.offline:
            # check if psutil and ldap3 was installed on remote server
            for py_mod in ('psutil', 'ldap3', 'pyDes'):
                result = installer.run("python -c 'import {0}'".format(py_mod), inside=False)
                if 'No module named' in result[2]:
                    wlogger.log(
                                task_id, 
                                "{0} module is not installed. Please "
                                "install python-{0} and retry.".format(py_mod),
                                "error", server_id=server.id,
                                )
                    return False

        else:
            installer.epel_release()

            # 5. Installing packages. 
            # 5a. First determine commands for each OS type
            packages = ['gcc', 'python3-dev', 'python3-pip']

            for package in packages:
                installer.install(package, inside=False, error_exception='warning:')

            # 5b. These commands are common for all OS types 
            commands = [
                            'pip3 install ldap3', 
                            'pip3 install psutil',
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
            
        server.data.monitoring = True
        server.save()

    return True

@celery.task(bind=True)
def remove_monitoring(self):
    
    """Celery task that removes monitoring components to remote server.

    :param self: the celery task

    :return: wether monitoring were removed successfully
    """
    task_id = self.request.id
    installed = 0
    servers = ConfigParam.get_servers()

    for server in servers:
        # 1. Installer
        installer = Installer(
                server, 
                logger_task_id=task_id, 
                server_os=server.data.os
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

        server.data.monitoring = False
        server.save()

    # 5. Remove local settings
    
    #create fake remote class that provides the same interface with RemoteClient
    fc = FakeRemote()

    installer = Installer(
            conn=fc,
            server_id=9999,
            logger_task_id=task_id,
            )

    installer.remove('influxdb', inside=False)

    #Flag database that configuration is done for local machine
    monitoring_settings = ConfigParam.get('monitoring')
    if monitoring_settings:
        monitoring_settings.data.monitoring = False
        monitoring_settings.save()

    return True
