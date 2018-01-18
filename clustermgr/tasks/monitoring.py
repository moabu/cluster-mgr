import json
import os
import getpass


from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, wlogger, celery
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import DBManager
from clustermgr.tasks.cluster import get_os_type

from flask import current_app as app

from influxdb import InfluxDBClient

class FakeRemote():
    def run(self, cmd):
        cin, cout, cerr = os.popen3(cmd)

        return '', cout.read(), cerr.read()


def run_and_log(c, cmd, tid, sid):
    
    result = c.run(cmd)
    
    if result[2].strip():
        wlogger.log(tid, "An error occurrued while executing "
                    "{}: {}".format(cmd, result[2]),
                    "error", server_id=sid)
    
    else:
        wlogger.log(tid, "Command was run successfully: {}".format(cmd),
                        "success", server_id=sid)
                                

@celery.task(bind=True)
def install_local(self):
    tid = self.request.id
    servers = Server.query.all()
    
    fc = FakeRemote()
    
    localos= get_os_type(fc)
    

    wlogger.log(tid, "Local OS was determined as {}".format(localos), "success", server_id=0)
    
    wlogger.log(tid, "Installing InfluxDB and Python client", "info", server_id=0)
    

    if 'Ubuntu' in localos:
        influx_cmd = [
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
            'sudo apt-get update',
            'sudo apt-get install influxdb',
            'sudo service influxdb start',
            'sudo pip install influxdb',
            'sudo pip install psutil',
            ]
    
    elif 'Debian' in localos:
        influx_cmd = [
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
            'DEBIAN_FRONTEND=noninteractive sudo apt-get -y install influxdb',
            'sudo service influxdb start',
            'sudo pip install influxdb',
            'sudo pip install psutil',
            ]

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
    
   
    
    

    monitoring_client = os.path.join(app.root_path, 'get_remote_stats.py')
    
    srv_list = [ server.hostname for server in servers]
    
    cur_user = getpass.getuser()
    
    crontab_entry = (
                        '*/5 * * * *    {}    /usr/bin/python '
                        '{} {}\n'
                        )

    crontab_entry = crontab_entry.format(
                                    cur_user, 
                                    monitoring_client,
                                    ' '.join(srv_list)
                                )

    cmd = 'echo "{}" | sudo tee /etc/cron.d/monitoring'.format(crontab_entry)
    
    run_and_log(fc, cmd, tid, 0)
    


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


    cmd = 'sudo service cron restart'

    run_and_log(fc, cmd, tid, 0)

    return True


@celery.task(bind=True)
def install_monitoring(self):
    return True
    """Celery task that installs the redis, stunnel and twemproxy applications
    in the required servers.

    Redis and stunnel are installed in all the servers in the cluster.
    Twemproxy is installed in the load-balancer/proxy server

    :param self: the celery task
    :param method: either STANDALONE, SHARDED

    :return: the number of servers where both stunnel and redis were installed
        successfully
    """
    tid = self.request.id
    installed = 0
    servers = Server.query.all()
    print "installing monitoring task started"

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
        
        result = c.run('mkdir -p /var/monitoring/scrpits')

        ctext = "\n".join(result)
        if ctext.strip():
            wlogger.log(tid, ctext,
                         "debug", server_id=server.id)

        wlogger.log(tid, "Directory /var/monitoring/scrpits directory "
                        "was created", "success", server_id=server.id)
        
        # 2. Upload scripts
        
        scripts = (
                    'cron_data_sqtile.py', 
                    'get_data.py', 
                    'sqlite_monitoring_tables.py'
                    )
        
        for scr in scripts:
        
            local_file = os.path.join(app.root_path, 'monitoring_scripts', scr)
                                        
            remote_file = '/var/monitoring/scrpits/'+scr

            result = c.upload(local_file, remote_file)
            
            if result.startswith("Upload successful"):
                wlogger.log(tid, "File {} was uploaded".format(scr),
                                "success", server_id=server.id)
            else:
                wlogger.log(tid, "File {} could not "
                                "be uploaded: {}".format(scr, result),
                                "error", server_id=server.id)
                return False
        
        
        # 3. Upload crontab entry to collect data in every 5 minutes
        crontab_entry = (
                        '*/5 * * * *    root    python '
                        '/var/monitoring/scrpits/cron_data_sqtile.py\n'
                        )
                        
        result = c.put_file('/etc/cron.d/monitoring', crontab_entry)
        
        
        if not result[0]:
            wlogger.log(tid, "An errorr occurred while uploading crontab entry"
                                ": {}".format(result[1]),
                                "error", server_id=server.id)
        else:
            wlogger.log(tid, "Crontab entry was uploaded",
                                "success", server_id=server.id)
        
        # 4. Installing packages
        if ('CentOS' in server.os) or ('RHEL' in server.os):
            package_cmd = ['yum install -y gcc', 'yum install -y python-devel',
                            'yum install -y python-pip',
                            'service crond restart'
                            ]
                            
        else:
            package_cmd = [ 
                            'apt-get install -y gcc', 
                            'apt-get install -y python-dev',
                            'apt-get install -y python-pip',
                            'service cron restart',
                            ]
            
        package_cmd += [
                        'pip install ldap3', 
                        'pip install psutil',
                        'python /var/monitoring/scrpits/'
                        'sqlite_monitoring_tables.py'
                        
                        ]
        
        wlogger.log(tid, "Installing Packages and Running Commands", 
                            "info", server_id=server.id)
        
        for cmd in package_cmd:
            
            
            result = c.run(cmd)
        
        
            wlogger.log(tid, "\n".join(result), "debug", server_id=server.id)
        
            err = False
        
            if result[2].strip():
                if not "pip install --upgrade pip" in result[2]:
                    wlogger.log(tid, "An error occurrued while executing "
                                "{}: {}".format(cmd, result[2]),
                                "error", server_id=server.id)
                    err = True
            
            if not err:
                wlogger.log(tid, "Command was run successfully: {}".format(cmd),
                                "success", server_id=server.id)



        
        
