# This scrpit is run via crontab entry to fecth statistics from remote
# servers via ssh. Script '/var/monitoring/scripts/get_data.py' on
# the remote server prints json data to stdout.
# Server hostnames should be given as arguments to this script.

import json
import os
import time
import sys

from influxdb import InfluxDBClient
from clustermgr.core.remote import RemoteClient
from clustermgr.monitoring_scripts import sqlite_monitoring_tables


#Python client of influxdb
client = InfluxDBClient(
                    host='localhost', 
                    port=8086, 
                    database='gluu_monitoring'
                    )

def write_influx(host, measurement, data):
    """Writes data to influxdb

    Args:
        host (string): hostname of server
        measurement (string): we use measuremet name to determine table
        data (compund): data to be written to influxdb

    Returns:
        tuple: True/False, file like object / error
    """
    measurement_suffix = host.replace('.','_')

    #Data is written to influxdb table host_name_measurement_name
    json_body =[]
    for d in data['data']:

        fields = {}
        for i,f in enumerate(data['fields'][1:]):
            fields[f] = d[i+1]
            json_body.append({"measurement": measurement_suffix+'_'+measurement,
                            "time": d[0],
                            "fields": fields,
                            })
    
    client.write_points(json_body, time_precision='s')


def get_last_update_time(host, measurement):

    """Returns last update time of measurement of the host

    Args:
        host (string): hostname of server
        measurement (string): measuremet

    Returns:
        string: last update time in unix time stamp
    """

    measurement_suffix = host.replace('.','_')
    
    result = client.query('SELECT * FROM {} order by time desc limit 1'.format(measurement_suffix+'_'+measurement), epoch='s')

    if 'series' in result.raw:
        return result.raw['series'][0]['values'][0][0]
    return 0

def get_remote_data(host, measurement, c):

    """Fetches data from remote host and write to influxdb

    Args:
        host (string): hostname of server
        measurement (string): measuremet
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication

    """

    start = get_last_update_time(host, measurement)

    print("last update time", start, "for measuremenet", measurement, "for host", host)
    
    #Execute remote script and fetch standard output
    cmd = 'python /var/monitoring/scripts/get_data.py stats {} {}'.format(
                                measurement,
                                start
                                )
    s_in, s_out, s_err = c.run(cmd)

    #If nothing bad on the remote server, data on the standard output shoul be
    #in json format
    try:
        data = json.loads(s_out)
    except:
        print("Server did not return json data")
        return

    print(len(data['data']['data']), "records received for measurement", measurement, "from host", host)
    
    #wrtite fetched data to imnfluxdb
    write_influx(host, measurement, data['data'])

    
def get_age(host, c):
    
    """This function isdeprecieated!
    Fetches umptime for host and writes to influxdb

    Args:
        host (string): hostname of server
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
    """

    
    print("Getting uptime")
    cmd = 'python /var/monitoring/scripts/get_data.py age'
    s_in, s_out, s_err = c.run(cmd)

    try:
        data = json.loads(s_out)
        arg_d = {'fields': ['time', 'uptime'], 'data': [[int(time.time()), data['data']['uptime']]]}
    except:
        print("Server did not return json data")
        arg_d = {'fields': ['time', 'uptime'], 'data': [[int(time.time()), 0]]}
    
    print("Uptime", data['data'])
    write_influx(host, 'uptime', arg_d)
    

servers = sys.argv[1:]

if not servers:
    print("Usage: python get_remote_stats.py server1 server2 servser3")

for server in servers:
    server_addr, ssh_port = server.slpit(':')
    c = RemoteClient(server, ssh_port=ssh_port)
    c.startup()
    for t in sqlite_monitoring_tables.monitoring_tables:
        get_remote_data(server, t, c)
    #get_age(server, c)
