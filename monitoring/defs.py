left_menu = { 
    'Ldap Monitoring': (
                        'replication_status',
                        'summary',
                        'gluu_authentications',
                        'completed_operations',
                        'read_waiters',
                        'compare_operations',
                        'referrals_sent',
                        'search_operations',
                        'total_connections',
                        'unbind_operations',
                        'add_operations',
                        'entries_sent',
                        'delete_operations',
                        'bytes_sent',
                        'bind_operations',
                        'modify_operations',
                        'write_waiters',
                        'initiated_operations',
                    ),
                


    'System Monitoring': (
                        'cpu_usage',
                        'load_average',
                        'memory_usage',
                        'network_i_o',
                        'disk_usage',
                        )
}


items = {

        'summary': {'end_point': 'ldap_all',
                    'vAxis':''},

        'gluu_authentications': {'end_point': 'ldap_single',
                    'data_source': 'gluu_auth.*',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'completed_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.completed_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'read_waiters': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.read_waiters',
                    'aggr': 'SUM',
                    'vAxis': '#'},

        'compare_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.compare_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'referrals_sent': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.referrals_sent',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'search_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.search_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'total_connections': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.total_connections',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'unbind_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.unbind_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'add_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.add_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'entries_sent': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.entries_sent',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'delete_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.delete_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'bytes_sent': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.bytes_sent',
                    'aggr': 'DRV',
                    'vAxis': 'Bytes per Second'},

        'bind_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.bind_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'modify_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.modify_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'write_waiters': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.write_waiters',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'initiated_operations': {'end_point': 'ldap_single',
                    'data_source': 'ldap_mon.initiated_operations',
                    'aggr': 'DIF',
                    'vAxis': '#'},

        'cpu_usage': {'end_point': 'system',
                    'data_source': 'cpu_info.*',
                    'aggr': 'DIF',
                    'chartType': 'AreaChart',
                    'vAxis': '%'},

        'load_average': {'end_point': 'system',
                    'data_source': 'load_average.*',
                    'aggr': 'AVG',
                    'chartType': 'LineChart',
                    'vAxis': '5 Mins Load Average'},

        'disk_usage': {'end_point': 'system',
                    'data_source': 'disk_usage.*',
                    'aggr': 'AVG',
                    'vAxisMax': 100,
                    'chartType': 'AreaChart',
                    'vAxis': '%'},

        'memory_usage': {'end_point': 'system',
                    'data_source': 'mem_usage.*',
                    'aggr': 'AVG',
                    'vAxisMax': 100,
                    'chartType': 'AreaChart',
                    'vAxis': '%'}, 

        'network_i_o': {'end_point': 'system',
                    'data_source': 'net_io.*',
                    'aggr': 'DRV',
                    'chartType': 'LineChart',
                    'vAxis': 'bytes in(-)/out(+) per sec'},
                    
        'cpu_percent': {'end_point': 'index',
                    'data_source': 'cpu_percent.*',
                    'aggr': 'AVG',
                    'chartType': 'AreaChart',
                    'vAxis': '%'},
                    
        'replication_status': {'end_point': 'replication_status'},
        
}



periods = { 'd': {'title': 'Daily', 'seconds': 86400, 'step': 300},
            'w': {'title': 'Weekly', 'seconds': 604800, 'step': 1800},
            'm': {'title': 'Monthly', 'seconds': 2592000, 'step': 7200},
            'y': {'title': 'Yearly', 'seconds': 31536000, 'step': 86400},
                
        }


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
