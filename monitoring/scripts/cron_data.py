import rrdtool
import os
import time

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

        conn.search(search_base=b, search_scope=BASE, search_filter='(objectClass=*)', attributes=['+'])

        summary[key]=conn.response[0]['attributes'][attr][0]

    options = summary.keys()
    options.sort()
    data = [ summary[o] for o in options]
    data.insert(0,'N')
    datas = ':'.join(data)
    rrdtool.update(os.path.join(data_path, 'ldap.rrd'), str(datas))

query_ldap_and_inject_db('ldaps://c4.gluu.org:1636', "cn=directory manager,o=gluu", "secret")
