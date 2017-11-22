data_dir = '/var/monitoring'
import sqlite3
import os
import psutil

disks = psutil.disk_partitions()
net = psutil.net_io_counters(pernic=True)

net_fields = []

for d in net:
    net_fields.append('{}_bytes_sent'.format(d))
    net_fields.append('{}_bytes_recv'.format(d))

monitoring_tables = {

    'cpu_info': ['system', 'user', 'nice', 'idle',
                 'iowait', 'irq', 'softirq', 'steal',
                 'guest', 'guestnice'],

    'cpu_percent': ['cpu_percent'],

    'ldap_mon': ['completed_operations', 'read_waiters',
                 'compare_operations', 'referrals_sent',
                 'search_operations', 'total_connections',
                 'unbind_operations', 'add_operations',
                 'entries_sent', 'delete_operations',
                 'bytes_sent', 'bind_operations',
                 'modify_operations', 'write_waiters',
                 'initiated_operations'],

    'load_average':['load_avg'],

    'disk_usage': [d.device.replace('/','_') for d in disks],

    'mem_usage': ['mem_usage'],

    'net_io': net_fields,

    'gluu_auth': ['success', 'failure'],
    

    }

text_fields = []
real_fields = ['load_avg', 'mem_usage']

if __name__ == '__main__':

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
                tmp = '`{}` {}'.format(c, f_type)
                columns_l.append(tmp)
            columns = ', '.join(columns_l)
            cmd = 'CREATE TABLE IF NOT EXISTS `{}` ({})'.format(t, columns)
            cur.execute(cmd)
