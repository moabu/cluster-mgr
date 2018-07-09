# This script collects data and writes local sqlite database
import os
import time
import psutil
import re
import sqlite3
from ldap3 import Server, Connection, BASE
from pyDes import *
import base64
import json

from sqlite_monitoring_tables import monitoring_tables

data_path = '/var/monitoring'


attr_list = ["addRequests", "modifyRequests", "deleteRequests", "searchRequests"]

sql_db_file = os.path.join(data_path, 'gluu_monitoring.sqlite3')

def get_ldap_admin_password():
    
    """Retreives ldap directory manager password from gluu installation
    
    Returns:
        string: ldap directory manager password
    """
    
    gluu_version = open(os.path.join(data_path, 'scripts', 'gluu_version.txt')).read().strip()
    salt_file = open('/opt/gluu-server-{0}/etc/gluu/conf/salt'.format(gluu_version)).read()
    salt = salt_file.split('=')[1].strip()
    ox_ldap_properties_file = '/opt/gluu-server-{0}/etc/gluu/conf/ox-ldap.properties'.format(gluu_version)
    for l in open(ox_ldap_properties_file):
        if l.startswith('bindPassword'):
            s = l.split(':')[1].strip()
            engine = triple_des(salt, ECB, pad=None, padmode=PAD_PKCS5)
            cipher = triple_des(salt)
            decrypted = cipher.decrypt(base64.b64decode(s), padmode=PAD_PKCS5)
            return decrypted


def execute_query(table, data, options=None):
    
    """Writes data to sqlite database

    Args:
        tables (string): table name
        data: compound data to be written to database
    """
    print json.dumps({table: data})
    
    tmpdata = [ str(d) for d in data ]
    
    datas = ', '.join(tmpdata)
    
    if not options:
        options = monitoring_tables[table]
    
    options = ['`{0}`'.format(o) for o in options]
    
    query = 'INSERT INTO `{0}` (`time`, {1}) VALUES ({2}, {3})'.format(
                                        table,
                                        ', '.join(options), 
                                        int(time.time()), datas)
    cur.execute(query)

def collect_ldap_monitoring():

    """Qury LDAP for monitoring statistics and writes data to local sqlite
    database
    """

    bind_dn = 'cn=directory manager'
    passwd = get_ldap_admin_password()
    server = Server("localhost:1636", use_ssl=True)
    conn = Connection(server, user=bind_dn, password=passwd)
    try:
        conn.bind()
    except:
        print "Can't connect to ldap server"
    else:

        conn.search(
                search_base="cn=LDAPS Connection Handler 0.0.0.0 port 1636 Statistics,cn=monitor",
                search_filter='(objectClass=*)',
                search_scope=BASE,
                attributes=attr_list,
                )
        resp = conn.response
        if resp:
            execute_query('ldap_mon', [resp[0]['raw_attributes'][a][0] for a in attr_list])


def collect_cpu_info():
    """Collects CPU times and writes to local sqlite database
    """
    cpu_times= psutil.cpu_times()
    data = [float(cpu_times.system), float(cpu_times.user), float(cpu_times.nice), float(cpu_times.idle), 
            float(cpu_times.iowait), float(cpu_times.irq), float(cpu_times.softirq), 
            float(cpu_times.steal), float(cpu_times.guest)]
    
    execute_query('cpu_info', data)

def collect_cpu_percent():
    """Collects CPU usage and writes to local sqlite database
    """
    data = [float(psutil.cpu_percent(interval=0.5))]
    execute_query('cpu_percent', data)

def collect_load_average():
    """Collects load average and writes to local sqlite database
    """
    load_avg = os.getloadavg()
    data = [load_avg[0]]
    execute_query('load_average', data)


def collect_disk_usage():
    
    """Collects disk usage (per partition) and write to local sqlite database
    """
    
    disks = psutil.disk_partitions()

    cur.execute('SELECT * FROM disk_usage LIMIT 1')

    #partitions
    dnames = [desc[0] for desc in cur.description]
    dnames.remove('time')

    data = []

    for d in dnames:
        for di in disks:
            if di.device == d.replace('_','/'):
                mp = di.mountpoint
                du = psutil.disk_usage(mp)
                data.append(float(du.percent))
                break
        else:
            data.append(0.0)
    
    execute_query('disk_usage', data, dnames)
    

def collect_mem_usage():  
    """Collects memory usage and write to local sqlite database
    """
    mem_usage = psutil.virtual_memory()
    data = [mem_usage.percent]
    execute_query('mem_usage', data)

def collect_ne_io():
    """Collects network IO and write to local sqlite database
    """
    cur.execute('SELECT * FROM net_io LIMIT 1')

    nifnames = []
    
    for desc in cur.description:
        if not desc[0]=='time':
            nif = desc[0][:desc[0].find('_')]
        
            if not nif in nifnames:
                nifnames.append(nif)

    net = psutil.net_io_counters(pernic=True)
    data = []
    for n in nifnames:
        data.append(net[n].bytes_sent)
        data.append(net[n].bytes_recv)
    execute_query('net_io', data)

def do_collect():
    collect_cpu_info()
    collect_cpu_percent()
    collect_load_average()
    collect_disk_usage()
    collect_mem_usage()
    collect_ne_io()
    collect_ldap_monitoring()

if __name__ == '__main__':
    sql_con = sqlite3.connect(sql_db_file)
    cur=sql_con.cursor()
    do_collect()
    sql_con.commit()
    sql_con.close()
    
