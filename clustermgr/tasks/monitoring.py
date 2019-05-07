import json
import os
import getpass
import time

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import DBManager
from clustermgr.tasks.cluster import get_os_type

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
            
        if http:
            if l.strip().startswith('bind-address'):
                l = '  bind-address = "localhost:8086"\n'

        new_conf.append(l)

    with open('/tmp/influxdb.conf','w') as W:
        W.write(''.join(new_conf))
        
    os.system('sudo cp -f /tmp/influxdb.conf /etc/influxdb/influxdb.conf')


class FakeRemote():
    
    """Provides fake remote class with the same run() function.
    """
    
    def run(self, cmd):
        
        """This method executes cmd as a sub-process.

        Args:
            cmd (string): commands to run locally
        
        Returns:
            Standard input, output and error of command
        
        """

        cin, cout, cerr = os.popen3(cmd)

        return '', cout.read(), cerr.read()


def run_and_log(c, cmd, tid, sid):
    
    """Shorthand for FakeRemote.run(). This function automatically logs
    the commands output to be shared in the web frontend.

    Args:
        c (:object:`FakeRemote`): class to be used to run cammand
        cmd (string): the command to be run on local server
        tid (string): task id of the task to store the log
        sid (integer): id of the server

    Returns:
        the output of the command or the err thrown by the command as a string
    """
    
    wlogger.log(tid, "Running {}".format(cmd))

    result = c.run(cmd)
    
    if result[2].strip():
        if "Redirecting to /bin/systemctl" in result[2]:
            wlogger.log(tid,result[2].strip(), "debug", server_id=sid)
        else:
            wlogger.log(tid, "An error occurrued while executing "
                    "{}: {}".format(cmd, result[2]),
                    "error", server_id=sid)
    
    else:
        wlogger.log(tid, "Command was run successfully: {}".format(cmd),
                        "success", server_id=sid)
                                

    return result

@celery.task(bind=True)
def install_local(self):
    
    """Celery task that installs monitoring components of local machine.

    :param self: the celery task

    :return: the number of servers where both stunnel and redis were installed
        successfully
    """
    
    tid = self.request.id
    servers = Server.query.all()
    
    app_config = AppConfiguration.query.first()
    
    #create fake remote class that provides the same interface with RemoteClient
    fc = FakeRemote()
    
    #Getermine local OS type
    localos= get_os_type(fc)


    wlogger.log(tid, "Local OS was determined as {}".format(localos), "success", server_id=0)


    if app_config.offline:

        if not os.path.exists('/usr/bin/influxd'):
            wlogger.log(tid, "Influxdb was installed on this machine. Please install influxdb", "error", server_id=0)
            return False

    else:

        if not localos == 'Alpine':
        
            wlogger.log(tid, "Installing InfluxDB and Python client", "info", server_id=0)
            
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
                elif '16' in localos:
                    influx_cmd.append(
                    'echo "deb https://repos.influxdata.com/ubuntu '
                    'bionic stable" | sudo tee '
                    '/etc/apt/sources.list.d/influxdb.list')
                
                influx_cmd += [
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get update',
                    'DEBIAN_FRONTEND=noninteractive sudo apt-get install influxdb',
                    'sudo service influxdb start',
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
                    ]

            elif localos in ('CentOS 7', 'RHEL 7'):
                influx_cmd = [
                                'sudo yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm',
                                'yum --enablerepo=epel repolist',
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
                            ]

            #run commands to install influxdb on local machine
            for cmd in influx_cmd:
            
                result = fc.run(cmd)
                
                rtext = "\n".join(result)
                if rtext.strip():
                    wlogger.log(tid, rtext, "debug", server_id=0)
            
                err = False
            
                if result[2].strip():
                    if not "pip install --upgrade pip" in result[2]:
                        wlogger.log(tid, "An error occurrued while executing "
                                    "{}: {}".format(cmd, result[2]),
                                    "error", server_id=0)
                        err = True
                
                if not err:
                    wlogger.log(tid, "Command was run successfully: {}".format(cmd),
                                    "success", server_id=0)
    
    wlogger.log(tid, "Fixing /etc/influxdb/influxdb.conf for InfluxDB listen localhost", server_id=0)
    fc.run('sudo systemctl stop influxdb')
    fix_influxdb_config()
    fc.run('sudo systemctl start influxdb')
    #wait influxdb to start
    time.sleep(10)

    #Statistics will be written to 'gluu_monitoring' on local influxdb server,
    #so we should crerate it.
    try:
        client = InfluxDBClient(
                    host='localhost', 
                    port=8086, 
                    )
        client.create_database('gluu_monitoring')

        wlogger.log(tid, "InfluxDB database 'gluu_monitoring was created",
                            "success", server_id=0)
    except Exception as e:
        wlogger.log(tid, "An error occurred while creating InfluxDB database "
                        "'gluu_monitoring': {}".format(e),
                            "fail", server_id=0)

    #Flag database that configuration is done for local machine
    
    app_config.monitoring = True
    db.session.commit()

    return True


@celery.task(bind=True)
def install_monitoring(self):
    
    """Celery task that installs monitoring components to remote server.

    :param self: the celery task

    :return: wether monitoring were installed successfully
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


        if app_config.offline:
            # check if psutil and ldap3 was installed on remote server
            for py_mod in ('psutil', 'ldap3'):            
                result = c.run("python -c 'import {0}'".format(py_mod))
                if 'No module named' in result[2]:
                    wlogger.log(
                                tid, 
                                "{0} module is not installed. Please "
                                "install python-{0} and retry.".format(py_mod),
                                "error", server_id=server.id,
                                )
                    return False

        # 2. create monitoring directory
        result = c.run('mkdir -p /var/monitoring/scripts')

        ctext = "\n".join(result)
        if ctext.strip():
            wlogger.log(tid, ctext,
                         "debug", server_id=server.id)

        wlogger.log(tid, "Directory /var/monitoring/scripts directory "
                        "was created", "success", server_id=server.id)
        
        # 3. Upload scripts
        scripts = (
                    'pyDes.py',
                    'cron_data_sqtile.py', 
                    'get_data.py', 
                    'sqlite_monitoring_tables.py'
                    )

        for scr in scripts:
            local_file = os.path.join(app.root_path, 'monitoring_scripts', scr)
            remote_file = '/var/monitoring/scripts/'+scr
            result = c.upload(local_file, remote_file)
            
            if result.startswith("Upload successful"):
                wlogger.log(tid, "File {} was uploaded".format(scr),
                                "success", server_id=server.id)
            else:
                wlogger.log(tid, "File {} could not "
                                "be uploaded: {}".format(scr, result),
                                "error", server_id=server.id)
                return False
        
        # 4. Upload gluu version, no need to determine gluu version each time
        result = c.put_file('/var/monitoring/scripts/gluu_version.txt', app_config.gluu_version)

        # 5. Upload crontab entry to collect data in every 5 minutes
        crontab_entry = (
                        '*/5 * * * *    root    python '
                        '/var/monitoring/scripts/cron_data_sqtile.py\n'
                        )
                        
        result = c.put_file('/etc/cron.d/monitoring', crontab_entry)

        if not result[0]:
            wlogger.log(tid, "An errorr occurred while uploading crontab entry"
                                ": {}".format(result[1]),
                                "error", server_id=server.id)
        else:
            wlogger.log(tid, "Crontab entry was uploaded",
                                "success", server_id=server.id)


        if not app_config.offline:
            # 6. Installing packages. 
            # 6a. First determine commands for each OS type
            if ('CentOS' in server.os) or ('RHEL' in server.os):
                package_cmd = [ 'rpm -U --force https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm',
                                'yum --enablerepo=epel repolist',
                                'yum install -y gcc', 
                                'yum install -y python-devel',
                                'yum install -y python-pip',
                                ]

            else:
                package_cmd = [ 'DEBIAN_FRONTEND=noninteractive apt-get update', 
                                'DEBIAN_FRONTEND=noninteractive apt-get install -y gcc', 
                                'DEBIAN_FRONTEND=noninteractive apt-get install -y python-dev',
                                'DEBIAN_FRONTEND=noninteractive apt-get install -y python-pip',
                                ]

            # 6b. These commands are common for all OS types 
            package_cmd += [
                            'pip install ldap3', 
                            'pip install psutil',
                            'pip install pyDes',
                            ]

            # 6c. Executing commands
            wlogger.log(tid, "Installing Packages and Running Commands", 
                                "info", server_id=server.id)

            for cmd in package_cmd:
                result = c.run(cmd)
                wlogger.log(tid, "\n".join(result), "debug", server_id=server.id)
                err = False

                if result[2].strip():
                    print "Writing error", cmd
                    if not ("pip install --upgrade pip" in result[2] or 'Redirecting to /bin/systemctl' in result[2]):
                        wlogger.log(tid, "An error occurrued while executing "
                                    "{}: {}".format(cmd, result[2]),
                                    "error", server_id=server.id)
                        err = True

                if not err:
                    wlogger.log(tid, "Command was run successfully: {}".format(cmd),
                                    "success", server_id=server.id)

        if ('CentOS' in server.os) or ('RHEL' in server.os):
            cmd_list = ['service crond restart']
        else:
            cmd_list = ['service cron restart']

        cmd_list += ['python /var/monitoring/scripts/sqlite_monitoring_tables.py']

        for cmd in cmd_list:
            wlogger.log(tid, "Executing "+cmd, "debug", server_id=server.id)
            result = c.run(cmd)
            r = "\n".join(result)
            if r.strip():
                wlogger.log(tid, r, "debug", server_id=server.id)

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
    localos= get_os_type(fc)

    

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
