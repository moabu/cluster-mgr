import json
import os
import time
import sys

from clustermgr.extensions import celery
from influxdb import InfluxDBClient
from clustermgr.core.remote import RemoteClient
from clustermgr.monitoring_scripts import sqlite_monitoring_tables
from clustermgr.models import Server, AppConfiguration

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
    print("Writing data to InfluxDB")
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

    if result.raw.get('series'):
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
    #start = 0
    print("Monitoring: last update time {} for measurement {} for host {}".format(start, measurement, host))

    #Execute remote script and fetch standard output
    cmd = 'python3 /var/monitoring/scripts/get_data.py stats {} {}'.format(
                                measurement,
                                start
                                )
    print("Monitoring: executing remote command", cmd)
    s_in, s_out, s_err = c.run(cmd)

    #If nothing bad on the remote server, data on the standard output shoul be
    #in json format
    try:
        data = json.loads(s_out)
    except Exception as e:
        print("Monitoring: Server {} did not return json data. Error {}".format(host, e))
        return

    print("Monitoring: {} records received for measurement {} from host {}".format(len(data['data']['data']), measurement, host))
    
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


    print("Monitoring: fetching uptime for {}".format(host))
    cmd = 'python3 /var/monitoring/scripts/get_data.py age'
    s_in, s_out, s_err = c.run(cmd)

    try:
        data = json.loads(s_out)
        arg_d = {'fields': ['time', 'uptime'], 'data': [[int(time.time()), data['data']['uptime']]]}
    except Exception as e:
        print("Monitoring: server {} did not return json data. Error: {}".format(host, e))
        arg_d = {'fields': ['time', 'uptime'], 'data': [[int(time.time()), 0]]}

    print("Monitoring: uptime {}".format(data['data']))
    write_influx(host, 'uptime', arg_d)

@celery.task
def get_remote_stats():
    print("Monitoring Statistics task")
    app_conf = AppConfiguration.query.first()
    if app_conf:
        if app_conf.monitoring:

            servers = Server.get_all()
            for server in servers:
                c = RemoteClient(server.hostname, ip=server.ip)
                try:
                    print("Monitoring: making ssh connection to server {}".format(server.hostname))
                    c.startup()
                except Exception as e:
                    print("Monitoring: An error occurred while making ssh connection {}".format(e))
                else:
                    print("Monitoring: getting data for derver {}".format(server.hostname))
                    try:
                        get_age(server.hostname, c)
                    except Exception as e:
                        print("Monitoring: An error occurred while retreiveing monitoring data from server {}. Error {}".format(server.hostname, e))
                    for t in sqlite_monitoring_tables.monitoring_tables:
                        try:
                            get_remote_data(server.hostname, t, c)
                        except Exception as e:
                            print("Monitoring: An error occurred while retreiveing {} data from server {}. Error {}".format(t, server.hostname, e))
