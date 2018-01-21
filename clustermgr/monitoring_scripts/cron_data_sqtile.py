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


searchlist = {
'total_connections':('cn=Total,cn=Connections,cn=Monitor','monitorCounter', '#'),
'bytes_sent': ('cn=Bytes,cn=Statistics,cn=Monitor','monitorCounter','Bytes'),
'completed_operations': ('cn=Operations,cn=Monitor','monitorOpCompleted', '#'),
'initiated_operations': ('cn=Operations,cn=Monitor','monitorOpInitiated', '#'),
'referrals_sent': ('cn=Referrals,cn=Statistics,cn=Monitor','monitorCounter', '#'),
'entries_sent': ('cn=Entries,cn=Statistics,cn=Monitor','monitorCounter', '#'),
'bind_operations': ('cn=Bind,cn=Operations,cn=Monitor','monitorOpCompleted', '#'),
'unbind_operations': ('cn=Unbind,cn=Operations,cn=Monitor','monitorOpCompleted', '#'),
'add_operations': ('cn=Add,cn=Operations,cn=Monitor','monitorOpInitiated', '#'),
'delete_operations':  ('cn=Delete,cn=Operations,cn=Monitor','monitorOpCompleted', '#'),
'modify_operations': ('cn=Modify,cn=Operations,cn=Monitor','monitorOpCompleted', '#'),
'compare_operations': ('cn=Compare,cn=Operations,cn=Monitor','monitorOpCompleted', '#'),
'search_operations': ('cn=Search,cn=Operations,cn=Monitor','monitorOpCompleted', '#'),
'write_waiters': ('cn=Write,cn=Waiters,cn=Monitor','monitorCounter', '#'),
'read_waiters': ('cn=Read,cn=Waiters,cn=Monitor','monitorCounter', '#'),
}


sql_db_file = os.path.join(data_path, 'gluu_monitoring.sqlite3')

def get_ldap_admin_password():
    gluu_version = open("gluu_version.txt").read().strip()
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
    
    tmpdata = [ str(d) for d in data ]
    
    datas = ', '.join(tmpdata)
    
    if not options:
        options = monitoring_tables[table]
    
    query = 'INSERT INTO {0} (time, {1}) VALUES ({2}, {3})'.format(
                                        table,
                                        ', '.join(options), 
                                        int(time.time()), datas)
    cur.execute(query)

def collect_ldap_monitoring():

    bind_dn = open('bind_dn.txt').read().strip()
    passwd = get_ldap_admin_password()
    server = Server("localhost:1636", use_ssl=True)
    conn = Connection(server, user=bind_dn, password=passwd)
    try:
        conn.bind()
    except:
        print "Can't connect to ldap server"
    else:
        summary = {}



        z = time.gmtime(time.time()-300)
        ct = time.strftime("%Y%m%d%H%M%S.000Z",z)

        count_dict = { 'user_authentication_failure':0, 'user_authentication_success':0}

        for count_t in count_dict:

            result = conn.search(search_base="o=gluu", search_filter='(&(&(objectClass=oxMetric)(creationDate>={0}))(oxMetricType={1}))'.format(ct, count_t), attributes=["oxData"])
    
            if result:
                data_q=conn.response[-1]["attributes"]['oxData']
                if data_q:
                    data = json.loads(data_q[0])
                    count_dict[count_t] = data['count']
        
        execute_query('gluu_auth', [count_dict['user_authentication_success'], count_dict['user_authentication_failure']])
        

        """
        # LDAP Monitoring
        options = monitoring_tables['ldap_mon']

        for key in options:
            b = searchlist[key][0]
            attr = searchlist[key][1]

            conn.search(search_base=b, search_scope=BASE,
                        search_filter='(objectClass=*)',
                        attributes=['+'])

            summary[key]=conn.response[0]['attributes'][attr][0]

        data = [ summary[o] for o in options]
  

        execute_query('ldap_mon', data)

            # GLUU Authentication Monitoring

        z=time.gmtime(time.time()-300)


        ct = time.strftime("%Y%m%d%H%M%S.000Z",z)
        
        conn.search(search_base="o=gluu", search_filter='(&(&(objectClass=oxMetric)(creationDate>={0}))(oxMetricType=user_authentication_failure))'.format(ct), attributes=["oxData"])

        data_s=conn.response[-1]["attributes"]['oxData'][0]
        m=re.search('{"count":(?P<count>\d+)}', data_s)
        failure=m.group('count')

        conn.search(search_base="o=gluu", search_filter='(&(&(objectClass=oxMetric)(creationDate>={0}))(oxMetricType=user_authentication_success))'.format(ct), attributes=["oxData"])
        data_s=conn.response[-1]["attributes"]['oxData'][0]
        m=re.search('{"count":(?P<count>\d+)}', data_s)
        success=m.group('count')
        print success, failure
        #execute_query('gluu_auth', [success, failure])
        """

def collect_cpu_info():
    cpu_times= psutil.cpu_times()
    data = [float(cpu_times.system), float(cpu_times.user), float(cpu_times.nice), float(cpu_times.idle), 
            float(cpu_times.iowait), float(cpu_times.irq), float(cpu_times.softirq), 
            float(cpu_times.steal), float(cpu_times.guest)]
    
    execute_query('cpu_info', data)

def collect_cpu_percent():
    data = [float(psutil.cpu_percent(interval=0.5))]
    execute_query('cpu_percent', data)

def collect_load_average():
    load_avg = os.getloadavg()
    data = [load_avg[0]]
    execute_query('load_average', data)


def collect_disk_usage():
    disks = psutil.disk_partitions()

    cur.execute('SELECT * FROM disk_usage LIMIT 1')

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
    mem_usage = psutil.virtual_memory()
    data = [mem_usage.percent]
    execute_query('mem_usage', data)

def collect_ne_io():

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
    #collect_ldap_monitoring('ldaps://c4.gluu.org:1636', "cn=directory manager,o=gluu", "secret")
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
    