import os
import time
import rrdtool

from ldap_monitor_options import searchlist
import ldap_functions


cur_dir=os.path.dirname(os.path.realpath(__file__))
#change this to app path
app_path = cur_dir
output_path = cur_dir

periods = { 'd': 'Daily',
            'w': 'Weekly',
            'm': 'Monthly',
            'y': 'Yearly' }


def get_file_path(hostname):
    file_name = 'ldap_{0}.rrd'.format(hostname.replace('.','_'))
    file_path = os.path.join(app_path, file_name)
    return file_path


def create_ldasp_rrd_db(hostname):

    file_path = get_file_path(hostname)

    args = [
        file_path,
        "--start", 'N',
        "--step", "300",
        ]
    options = searchlist.keys()
    options.sort()

    for opt in options:
        args.append('DS:{0}:COUNTER:600:U:U'.format(opt.replace('_','')))
        args.append('RRA:MIN:0.5:1:576')
        args.append('RRA:MAX:0.5:1:576')
        args.append('RRA:MIN:0.5:6:432')
        args.append('RRA:MAX:0.5:6:432')
        args.append('RRA:MIN:0.5:24:540')
        args.append('RRA:MAX:0.5:24:540')
        args.append('RRA:MIN:0.5:288:450')
        args.append('RRA:MAX:0.5:288:450')
        args.append('RRA:AVERAGE:0.5:1:576')
        args.append('RRA:AVERAGE:0.5:6:432')
        args.append('RRA:AVERAGE:0.5:24:540')
        args.append('RRA:AVERAGE:0.5:288:450')

    rrdtool.create(args)

#create_ldasp_rrd_db('c5.gluu.org')


def query_ldap_and_inject_db(addr, binddn, passwd):
        hostname, port = ldap_functions.get_host_port(addr)
        ldp = ldap_functions.LdapOLC(addr, binddn, passwd)
        ldp.connect()
        summary = ldp.getLDAPMonitorInfo()
        options = summary.keys()
        options.sort()
        data = [ summary[o] for o in options]
        data.insert(0,'N')
        file_path = get_file_path(hostname)
        datas = ':'.join(data)
        rrdtool.update(file_path, str(datas))


def get_ldap_monitoring_data(hosts, option, period='d', start=None, end=None):

    if not start:
        sTime = { 'd': 60*60*24,
                      'w': 60*60*24*7,
                      'm': 60*60*24*30,
                      'y': 60*60*24*365,
                    }

        start=int( time.time() - sTime[period] )
        end = int(time.time())

    rrd_args = ['-s', str(start), '-e', str(end)]

    for i, h in enumerate(hosts):

        data_f = os.path.join(app_path, 'ldap_'+h.replace('.','_'))
        
        rdef = 'DEF:data{0}={1}.rrd:{2}:AVERAGE'.format(
                    i,
                    data_f,
                    option
                    )
        rrd_args.append( rdef )

        rxport = "XPORT:data{0}:Data".format(i)
        rrd_args.append( rxport )

    print "RRD ARGS", rrd_args
    rrd_data=rrdtool.xport(rrd_args)

    return rrd_data

#query_ldap_and_inject_db('ldaps://mb1.mygluu.org:636', "cn=directory manager,o=gluu", "secret")

#create_ldap_graphs(['mb1.mygluu.org', 'u1.mygluu.org'])
