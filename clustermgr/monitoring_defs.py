#This script contains definitions for monitoring. It will be imported
#by many scripts

#These are the definitions of menu on the monitoring page
left_menu = { 
    'Ldap Monitoring': (
                        'replication_status',
                        #'gluu_authentications',
                        'add_requests',
                        'modify_requests',
                        'delete_requests',
                        'search_requests',
                    ),


    'System Monitoring': (
                        'cpu_usage',
                        'load_average',
                        'memory_usage',
                        'network_i_o',
                        'disk_usage',
                        )
}

# Each item on the menu may have an endpoint ('end_point), 
# aggregate functions (aggr) to be used, data source (data_source)
# graphic type (chartType) and axis anems
items = {

        'summary': {'end_point': 'monitoring.ldap_all',
                    'vAxis':''},

        'gluu_authentications': {'end_point': 'monitoring.ldap_single',
                    'data_source': 'gluu_auth.*',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'add_requests': {'end_point': 'monitoring.ldap_single',
                    'data_source': 'ldap_mon.addRequests',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'modify_requests': {'end_point': 'monitoring.ldap_single',
                    'data_source': 'ldap_mon.modifyRequests',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'delete_requests': {'end_point': 'monitoring.ldap_single',
                    'data_source': 'ldap_mon.deleteRequests',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'search_requests': {'end_point': 'monitoring.ldap_single',
                    'data_source': 'ldap_mon.searchRequests',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'cpu_usage': {'end_point': 'monitoring.system',
                    'data_source': 'cpu_info.*',
                    'aggr': 'DIF',
                    'chartType': 'AreaChart',
                    'vAxis': '%'},

        'load_average': {'end_point': 'monitoring.system',
                    'data_source': 'load_average.*',
                    'aggr': 'AVG',
                    'chartType': 'LineChart',
                    'vAxis': '5 Mins Load Average'},

        'disk_usage': {'end_point': 'monitoring.system',
                    'data_source': 'disk_usage.*',
                    'aggr': 'AVG',
                    'vAxisMax': 100,
                    'chartType': 'AreaChart',
                    'vAxis': '%'},

        'memory_usage': {'end_point': 'monitoring.system',
                    'data_source': 'mem_usage.*',
                    'aggr': 'AVG',
                    'vAxisMax': 100,
                    'chartType': 'AreaChart',
                    'vAxis': '%'}, 

        'network_i_o': {'end_point': 'monitoring.system',
                    'data_source': 'net_io.*',
                    'aggr': 'DRV',
                    'chartType': 'LineChart',
                    'vAxis': 'bytes in(-)/out(+) per sec'},
                    
        'cpu_percent': {'end_point': 'monitoring.index',
                    'data_source': 'cpu_percent.*',
                    'aggr': 'AVG',
                    'chartType': 'AreaChart',
                    'vAxis': '%'},
                    
        'replication_status': {'end_point': 'monitoring.replication_status'},
        
}


#These are the periods and steps
periods = { 'd': {'title': 'Daily', 'seconds': 86400, 'step': 300},
            'w': {'title': 'Weekly', 'seconds': 604800, 'step': 1800},
            'm': {'title': 'Monthly', 'seconds': 2592000, 'step': 7200},
            'y': {'title': 'Yearly', 'seconds': 31536000, 'step': 86400},
                
        }

#These are openldap monitoring dns
searchlist = {
'total_connections':('cn=Total,cn=Connections,cn=Monitor','monitorCounter'),
'bytes_sent': ('cn=Bytes,cn=Statistics,cn=Monitor','monitorCounter'),
'completed_operations': ('cn=Operations,cn=Monitor','monitorOpCompleted'),
'initiated_operations': ('cn=Operations,cn=Monitor','monitorOpInitiated'),
'referrals_sent': ('cn=Referrals,cn=Statistics,cn=Monitor','monitorCounter'),
'entries_sent': ('cn=Entries,cn=Statistics,cn=Monitor','monitorCounter',),
'bind_operations': ('cn=Bind,cn=Operations,cn=Monitor','monitorOpCompleted',),
'unbind_operations': ('cn=Unbind,cn=Operations,cn=Monitor','monitorOpCompleted',),
'add_operations': ('cn=Add,cn=Operations,cn=Monitor','monitorOpInitiated'),
'delete_operations':  ('cn=Delete,cn=Operations,cn=Monitor','monitorOpCompleted'),
'modify_operations': ('cn=Modify,cn=Operations,cn=Monitor','monitorOpCompleted'),
'compare_operations': ('cn=Compare,cn=Operations,cn=Monitor','monitorOpCompleted'),
'search_operations': ('cn=Search,cn=Operations,cn=Monitor','monitorOpCompleted'),
'write_waiters': ('cn=Write,cn=Waiters,cn=Monitor','monitorCounter'),
'read_waiters': ('cn=Read,cn=Waiters,cn=Monitor','monitorCounter'),
}
