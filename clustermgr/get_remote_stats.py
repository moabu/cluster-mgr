import json
import os
import time
import sys

from influxdb import InfluxDBClient
from clustermgr.core.remote import RemoteClient
from clustermgr.monitoring_scripts import sqlite_monitoring_tables

client = InfluxDBClient(
                    host='localhost', 
                    port=8086, 
                    database='gluu_monitoring'
                    )

def write_influx(host, measurement, data):

    measurement_suffix = host.replace('.','_')

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

    measurement_suffix = host.replace('.','_')
    
    result = client.query('SELECT * FROM {} order by time desc limit 1'.format(measurement_suffix+'_'+measurement), epoch='s')

    if result.raw.has_key('series'):
        return result.raw['series'][0]['values'][0][0]
    return 0

def get_remote_data(host, measurement, c):

    start = get_last_update_time(host, measurement)

    print "last update time", start, "for measuremenet", measurement, "for host", host
    
                                            
    cmd = 'python /var/monitoring/scripts/get_data.py stats {} {}'.format(
                                measurement,
                                start
                                )
    s_in, s_out, s_err = c.run(cmd)

    try:
        data = json.loads(s_out)
    except:
        print "Server did not return json data"
        return

    print len(data['data']['data']), "records received for measurement", measurement, "from host", host
    write_influx(host, measurement, data['data'])

    
def get_age(host, c):
    print "Getting uptime"
    cmd = 'python /var/monitoring/scripts/get_data.py age'
    s_in, s_out, s_err = c.run(cmd)

    try:
        data = json.loads(s_out)
        arg_d = {u'fields': ['time', u'uptime'], u'data': [[int(time.time()), data['data']['uptime']]]}
    except:
        print "Server did not return json data"
        arg_d = {u'fields': ['time', u'uptime'], u'data': [[int(time.time()), 0]]}
    
    print "Uptime", data['data']
    write_influx(host, 'uptime', arg_d)
    

servers = sys.argv[1:]

for server in servers:
    c = RemoteClient(server)
    c.startup()
    for t in sqlite_monitoring_tables.monitoring_tables:
        get_remote_data(server, t, c)
    #get_age(server, c)