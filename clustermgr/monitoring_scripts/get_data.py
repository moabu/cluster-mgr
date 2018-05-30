#This script queries local sqlite database and dumps to standart output as json

import psutil
import time
import os
import re
import json
import sys
import sqlite3

data_dir = '/var/monitoring'

def get_sqlite_stats(measurement):
    start=0
    if len(sys.argv) > 3:
        start = sys.argv[3]
    db_file = os.path.join(data_dir, 'gluu_monitoring.sqlite3')
    with sqlite3.connect(db_file) as con:
        cur = con.cursor()
        cur.execute('SELECT * FROM `{0}` WHERE time > {1}'.format(measurement, start))
        result = cur.fetchall()
        feilds = [ d[0] for d in cur.description ]
        data = result

    print json.dumps({'data':{'fields':feilds, 'data': data}})


def get_age():
    uptime = int(time.time() - psutil.boot_time())
    print json.dumps({'data':{'uptime': uptime}})

if len(sys.argv) > 1:
    if sys.argv[1]=='age':
        get_age()
    if sys.argv[1]=='stats':
        if len(sys.argv) > 2:
            measurement = sys.argv[2]
            get_sqlite_stats(measurement)
