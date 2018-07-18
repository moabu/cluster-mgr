import json
import os
import getpass

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.ldap_functions import DBManager
from clustermgr.core.clustermgr_installer import Installer
from clustermgr.core.utils import is_debian_clone
from clustermgr.core.remote import FakeRemote



from flask import current_app as app

from influxdb import InfluxDBClient



@celery.task(bind=True)
def install_local(self):
    
    """Celery task that installs monitoring components of local machine.

    :param self: the celery task

    :return: the number of servers where both stunnel and redis were installed
        successfully
    """
    
    task_id = self.request.id
    servers = Server.query.all()
    
    #create fake remote class that provides the same interface with RemoteClient
    fc = FakeRemote()
    
    installer = Installer(
                conn=fc,
                gluu_version=None,
                server_id=0,
                logger_task_id=task_id,
                )
    
    #Getermine local OS type
    localos= installer.server_os

    

    wlogger.log(task_id, "Local OS was determined as {}".format(localos), "success", server_id=0)

    if not localos == 'Alpine':
    
        wlogger.log(task_id, "Installing InfluxDB and Python client", "info", server_id=0)
        
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
                'sudo pip install influxdb',
                'sudo pip install psutil',
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
                'sudo pip install influxdb',
                'sudo pip install psutil',
                ]

        elif localos == 'CentOS 7':
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
                            'sudo pip install psutil',
                        ]

        #run commands to install influxdb on local machine
        for cmd in influx_cmd:
        
            result = installer.run(cmd, error_exception='__ALL__', inside=False)
            
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
        wlogger.log(tid, "An error occurred while creating InfluxDB database "
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
    servers = Server.query.all()
    app_conf = AppConfiguration.query.first()
    
    for server in servers:
        # 1. Installer
        installer = Installer(
                server, 
                app_conf.gluu_version, 
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
        
        # 4. Upload gluu version, no need to determine gluu version each time
        
        installer.put_file('/var/monitoring/scripts/gluu_version.txt', app_conf.gluu_version)
        
        # 5. Upload crontab entry to collect data in every 5 minutes
        crontab_entry = (
                        '*/5 * * * *    root    python '
                        '/var/monitoring/scripts/cron_data_sqtile.py\n'
                        )
                        
        if not installer.put_file('/etc/cron.d/monitoring', crontab_entry):
            return False


        installer.epel_release()

        # 6. Installing packages. 
        # 6a. First determine commands for each OS type
        packages = ['gcc', 'python-dev', 'python-pip']

        for package in packages:
            installer.install(package, inside=False)

        # 6b. These commands are common for all OS types 
        commands = [
                        'pip install ldap3', 
                        'pip install psutil',
                        'pip install pyDes',
                        'python /var/monitoring/scripts/'
                        'sqlite_monitoring_tables.py'
                        ]

        if is_debian_clone(server.os):
            commands.append('service cron restart')
        else:
            commands.append('service crond restart')

        # 6c. Executing commands
        wlogger.log(task_id, "Installing Packages and Running Commands", 
                            "info", server_id=server.id)
        
        for cmd in commands:
            
            result = installer.run(cmd, inside=False, error_exception='__ALL__')
        
        server.monitoring = True

    db.session.commit()
    return True

@celery.task(bind=True)
def remove_monitoring(self, local_id):
    
    """Celery task that removes monitoring components to remote server.

    :param self: the celery task

    :return: wether monitoring were removed successfully
    """
    tid = self.request.id
    installed = 0
    servers = Server.query.all()
    app_config = AppConfiguration.query.first()
    for server in servers:
        # 1. Make SSH Connection to the remote server
        wlogger.log(tid, "Making SSH connection to the server {0}".format(
            server.hostname), "info", server_id=server.id)

        c = RemoteClient(server.hostname, ip=server.ip)
        try:
            c.startup()
        except Exception as e:
            wlogger.log(
                tid, "Cannot establish SSH connection {0}".format(e), 
                "warning",  server_id=server.id)
            wlogger.log(tid, "Ending server setup process.", 
                                "error", server_id=server.id)
            return False
        
        # 2. remove monitoring directory
        result = c.run('rm -r /var/monitoring/')

        ctext = "\n".join(result)
        if ctext.strip():
            wlogger.log(tid, ctext,
                         "debug", server_id=server.id)

        wlogger.log(tid, "Directory /var/monitoring/ directory "
                        "were removed", "success", server_id=server.id)
        
        # 3. remove crontab entry to collect data in every 5 minutes

        c.run('rm /etc/cron.d/monitoring')
        wlogger.log(tid, "Crontab entry was removed", 
                            "info", server_id=server.id)
   
        
        if ('CentOS' in server.os) or ('RHEL' in server.os):
            package_cmd = [ 
                            'service crond restart'
                            ]
                            
        else:
            package_cmd = [ 
                            'service cron restart',
                            ]
        # 4. Executing commands
        wlogger.log(tid, "Restarting crontab", 
                            "info", server_id=server.id)
        
        
        for cmd in package_cmd:
            result = c.run(cmd)
            rtext = "\n".join(result)
            if rtext.strip():
                wlogger.log(tid, rtext, "debug", server_id=server.id)
        
        server.monitoring = False
    # 5. Remove local settings
    
    #create fake remote class that provides the same interface with RemoteClient
    fc = FakeRemote()
    
    #Getermine local OS type
    localos= fc.get_os_type()

    

    if 'Ubuntu' or 'Debian' in localos:
        influx_cmd = ['sudo apt-get -y remove influxdb',]

    elif localos == 'CentOS 7':
        influx_cmd = ['sudo yum remove -y influxdb',]
        
        
    #run commands to install influxdb on local machine
    for cmd in influx_cmd:
        
        result = fc.run(cmd)
        
        rtext = "\n".join(result)
        if rtext.strip():
            wlogger.log(tid, rtext, "debug", server_id=local_id)


    #Flag database that configuration is done for local machine
    app_config = AppConfiguration.query.first()
    app_config.monitoring = False
    db.session.commit()

    return True
