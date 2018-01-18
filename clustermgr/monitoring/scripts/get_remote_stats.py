import json
import os
from influxdb import InfluxDBClient
import requests
import time
from sqlite_monitoring_tables import monitoring_tables

def write_influx(host, measurement, data):
    client = InfluxDBClient('localhost', 8086, 'mbaser', 'qwerty', host.replace('.','_'))

    json_body =[]
    for d in data['data']:

        fields = {}
        for i,f in enumerate(data['fields'][1:]):
            fields[f] = d[i+1]
            json_body.append({"measurement": measurement,
                            "time": d[0],
                            "fields": fields,                        
                            })

    client.write_points(json_body, time_precision='s')


def get_last_update_time(host, measurement):
    client = InfluxDBClient('localhost', 8086, 'mbaser', 'qwerty', host.replace('.','_'))
    result = client.query('SELECT * FROM {} order by time desc limit 1'.format(measurement), epoch='s')

    if result.raw.has_key('series'):
        return result.raw['series'][0]['values'][0][0]
    return 0

def get_remote_data(host, measurement):

    start = get_last_update_time(host, measurement)

    print "last update time", start, "for measuremenet", measurement, "for host", host
    
    req_addr = 'http://{0}:10443/getsqlite/{1}/{2}'.format(
                                            host, measurement, start
                                            )
    
    r = requests.get(req_addr)
    datas = r.text
    data = json.loads(datas)

    print len(data['data']['data']), "records received for measurement", measurement, "from host", host
    write_influx(host, measurement, data['data'])


hosts=(
    'c1.gluu.org', 
    #'c5.gluu.org'
    )

for h in hosts:
    
    for t in monitoring_tables:
        get_remote_data(h, t)
        try:
            get_remote_data(h, t)
        except:
            print "Monitoring info from", h, "for measurement", t, "can't be obtained. Hope it works for next time"


