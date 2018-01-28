#This script contains infromation about sqlite database tables, if run
#creates database and defined tables

data_dir = '/var/monitoring'
import sqlite3
import os
import psutil
import time

disks = psutil.disk_partitions()
disk_parts = []
for d in disks:
    p = d.device.replace('/','_')
    if not p in disk_parts:
        disk_parts.append(p)

net = psutil.net_io_counters(pernic=True)


net_fields = []

for d in net:
    net_fields.append('{0}_bytes_sent'.format(d))
    net_fields.append('{0}_bytes_recv'.format(d))

monitoring_tables = {

    'cpu_info': ['system', 'user', 'nice', 'idle',
                 'iowait', 'irq', 'softirq', 'steal',
                 'guest'],

    'cpu_percent': ['cpu_percent'],

    'ldap_mon': ['addRequests', 'modifyRequests', 'deleteRequests', 'searchRequests'],

    'load_average':['load_avg'],

    'disk_usage': disk_parts,

    'mem_usage': ['mem_usage'],

    'net_io': net_fields,

    'gluu_auth': ['success', 'failure'],
    

    }

text_fields = []
real_fields = ['cpu_percent', 'load_avg', 'mem_usage', 'system', 'user', 'nice', 'idle',
                 'iowait', 'irq', 'softirq', 'steal',
                                  'guest']
for d in disks:
    real_fields.append(d.device.replace('/','_'))

if __name__ == '__main__':

    if not os.path.exists(data_dir):
        os.mkdir(data_dir)

    db_file = os.path.join(data_dir, 'gluu_monitoring.sqlite3')

    with sqlite3.connect(db_file) as con:
        cur = con.cursor()
        for t in monitoring_tables:
            columns_l=['`time` INTEGER ']
            for c in monitoring_tables[t]:
                if c in text_fields:
                    f_type = 'TEXT'
                elif c in real_fields:
                    f_type = 'REAL'
                else:
                    f_type = 'INTEGER'
                tmp = '`{0}` {1}'.format(c, f_type)
                columns_l.append(tmp)
            columns = ', '.join(columns_l)
            cmd = 'CREATE TABLE IF NOT EXISTS `{0}` ({1})'.format(t, columns)
            cur.execute(cmd)
