import json
import os
import time
import sys
import sqlite3

from influxdb import InfluxDBClient

from paramiko import SSHException
from paramiko.client import SSHClient, AutoAddPolicy
from paramiko.ssh_exception import PasswordRequiredException 

server_time = None

#Python client of influxdb
client = InfluxDBClient(
                    host='localhost', 
                    port=8086, 
                    database='gluu_monitoring'
                    )


DATABASE_FILE = "{}/clustermgr.dev.db".format(os.path.join(os.path.expanduser("~"), ".clustermgr"))

if not os.path.exists(DATABASE_FILE):
    error_text =  "Database file {} does not exist. Are you running this script with the same user as clustermgr?".format(DATABASE_FILE)
    sys.exit(error_text)

conn = sqlite3.connect(DATABASE_FILE)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

monitoring_tables = ['ldap_mon', 'cpu_info', 'disk_usage', 'load_average', 'net_io', 'cpu_percent', 'mem_usage']


def exec_remote_cmd(ssh_client, cmd):
    print "Executing command '{0}' on server and fecthing output.".format(cmd)
    buffers = ssh_client.exec_command(cmd)
    stdout = buffers[1].read()
    stderr = buffers[2].read()

    if stderr:
        sys.exit(">>> Some text fetched from standard error, this should not happen. Here is error:" +stderr)

    return stdout


def check_data_generated_on_server(ssh_client):
    print "Checking if script can generate monitoring data on server"
    cmd = 'python /var/monitoring/scripts/cron_data_sqtile.py'
    stdout = exec_remote_cmd(ssh_client, cmd)
    


    print "Here is output of the command. Each line should be in JSON format"
    print stdout

    if not stdout.strip():
        sys.exit(">>> It seems script on the server did not generate data")
    else:
        lines = stdout.strip().split('\n')
        if not lines:
            print "Fethced output does not contain enough data"
        else:
            error = False
            for line in lines:
                try:
                    tmp_data = json.loads(line)
                except  Exception as e:
                    error = True
                    print ">>> The following line is not in JSON format, this shoul not be."
                    print line
                    print ">>> The error is:", e
                    
                for key, value in tmp_data.items():
                    if not key in monitoring_tables:
                        error = True
                        print ">>> Unknown key: {0}, this should not happen".format(key)
                    if len(value)==0:
                        error = True
                        print ">>> Data for key {0} is empty, this should not happen".format(key)

            if not error:
                print "Output is analayzed and it seems scrpit on the server successfully generates data"
            else:
                sys.exit()

def check_database_populated(ssh_client): 
    print "Checking if sqlite database on server is populated"

    cmd = "python -c \"import sqlite3; print sqlite3.connect('/var/monitoring/gluu_monitoring.sqlite3').cursor().execute('select * from mem_usage where time > {0}').fetchone()\"".format(server_time - 60*6)
    stdout = exec_remote_cmd(ssh_client, cmd)

    if not stdout.strip():
        print ">>> Output of the command is empty, this should not happen."
        sys.exit(">>> It seems sqlite database is not populated by script /var/monitoring/scripts/cron_data_sqtile.py")

    else:
        tmp_data = eval(stdout.strip())
        print "Memory usage of the server on {0} is {1}%".format(time.ctime(float(tmp_data[0])), tmp_data[1])
        print "It seems sqlite database is populated successfully"

def check_data_could_fetched(ssh_client):
    print "Checking if data could be fetched from server"
    cmd = 'python /var/monitoring/scripts/get_data.py age'
    stdout = exec_remote_cmd(ssh_client, cmd)
    try:
        tmp_data = json.loads(stdout)
        m, s  = divmod(tmp_data['data']['uptime'],60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        print "Uptime of the server is {0} days {1} hours {2} minutes".format(d,h,m)
    except  Exception as e:
        error = True
        print ">>> The following line is not in JSON format, this shoul not be."
        print line
        sys.exit(">>> The error is:" + e)


    for measurement in monitoring_tables:

        print "Fething monitoring data from server for measurement {0}".format(measurement)
        
    
        cmd = 'python /var/monitoring/scripts/get_data.py stats {} {}'.format(
                                measurement,
                                server_time - 60*6
                                )

        stdout = exec_remote_cmd(ssh_client, cmd)
    
        error = False
        try:
            data = json.loads(stdout)

            print "{0} statistics on {1}:".format(measurement, time.ctime(data['data']['data'][0][0]))
            for i, field in enumerate(data['data']['fields'][1:]):
                print field,':', data['data']['data'][0][i+1]
            print
            
        except Exception as e:
            print "Data fetched from server is not in JSON format. Error {}".format(e)
            error = True

    if not error:
        print "It seems data could be fetched successfully from server"
        
    else:
        sys.exit()

def get_server_time(ssh_client):
    global server_time
    print "Getting server time"
    cmd = 'date +%s'
    stdout = exec_remote_cmd(ssh_client, cmd)
    server_time = int(stdout)
    print "Server time is {0}".format(time.ctime(server_time))

def check_influxdb(hostname):
    print "Querying influxdb for gluu_monitoring database"
    result = client.query("show databases")

    for v in result.raw['series'][0]['values']:
        if v[0] == 'gluu_monitoring':
            print "gluu_monitoring exists on influxdb"
            break
    else:
        sys.exit(">>> gluu_monitoring does not exist on influxdb")

    print "Querying influxdb for gluu_monitoring tables"
    result = client.query("show measurements")
    tables = []
    for t in result.raw['series'][0]['values']:
        tables.append(t[0])

    hostname_ = hostname.replace('.','_')

    for mt in monitoring_tables:
        mth = hostname_+'_'+mt
        if not  mth in tables:
            sys.exit(">>> Table {} does not exist".format(mth))
            break
    else:
         print "All tables exist in database"


    print "Querying sample data"
    result = client.query("select * from {} order by time desc limit 5".format(mth))
    

    if len(result.raw['series'][0]['values']) >= 5:
        print "Last five row from table {}".format(mth)
        for r in result.raw['series'][0]['values']:
            print r[0]
        print "\n*********** Everything seems OK for {} ************".format(hostname)
    else:
        sys.exit(">>> Could not fecth last five row form {}".format(mth))
    
def check_servers():
    cursor.execute('SELECT * FROM appconfig')
    app_conf = cursor.fetchone()

    if app_conf['monitoring']:
        cursor.execute('SELECT * FROM server')
        servers = cursor.fetchall()
        for server in servers:
            ssh_client = SSHClient()
            ssh_client.set_missing_host_key_policy(AutoAddPolicy())
            ssh_client.load_system_host_keys()
            print "********** Checking server {0} **********".format(server['hostname'])
            print "Making SSH Connection to server {0}".format(server['hostname'])
            ssh_client.connect(server['hostname'], port=22, username='root')
            print "SSH connection is successful."
            get_server_time(ssh_client)
            check_data_generated_on_server(ssh_client)
            check_database_populated(ssh_client)
            check_data_could_fetched(ssh_client)
            check_influxdb(server['hostname'])
            print "-"*50,'\n'


check_servers()
