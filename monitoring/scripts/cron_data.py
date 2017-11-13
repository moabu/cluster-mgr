import rrdtool
import os
import time
import psutil

from ldap3 import Server, Connection, BASE

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



data_path = '/var/monitoring'


def query_ldap_and_inject_db(addr, binddn, passwd):
    
    server = Server(addr, use_ssl=True)
    conn = Connection(server, user=binddn, password=passwd)
    conn.bind()

    summary = {}

    for key in searchlist.keys():
        b = searchlist[key][0]
        attr = searchlist[key][1]

        conn.search(search_base=b, search_scope=BASE,
                    search_filter='(objectClass=*)',
                    attributes=['+'])

        summary[key]=conn.response[0]['attributes'][attr][0]

    options = summary.keys()
    options.sort()
    data = [ summary[o] for o in options]
    data.insert(0,'N')
    datas = ':'.join(data)
    
    rrdtool.update(os.path.join(data_path, 'ldap.rrd'), str(datas))

def inject_cpu_info():
    sl=open("/proc/stat").readline()
    user, nice, system, idle, iowait, irq, softirq, steal, guest, guestnice = sl.strip().split()[1:]
    file_path = os.path.join(data_path, 'cpu_info.rrd')
    data = 'N:{0}:{1}:{2}:{3}:{4}:{5}:{6}:{7}:{8}:{9}'.format(
                                        user,
                                        nice,
                                        system,
                                        idle,
                                        iowait,
                                        irq,
                                        softirq,
                                        steal,
                                        guest, 
                                        guestnice,
                                    )


    rrdtool.update(file_path, data)
    
def inject_load_average():  
    file_path = os.path.join(data_path, 'load_average.rrd')
    load_avg = os.getloadavg()
    data = "N:{}".format(int(load_avg[0] * 100))
    rrdtool.update(file_path, data)
    
#query_ldap_and_inject_db('ldaps://localhost:1636', "cn=directory manager,o=gluu", "secret")
#inject_cpu_info()
inject_load_average()
