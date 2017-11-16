import json
import rrdtool
import time
import os
import re

from flask import Flask, request, redirect, url_for


app = Flask(__name__)

__SECRET_KEY__ = '62cc35df-af28-48ea-a623-79910f6743f8'


data_dir = '/var/monitoring'

#@app.before_request
#def require_authorization():
#    if  request.headers.get('secret') != __SECRET_KEY__:
#        return json.dumps({'data': 'Unauthorized'})


sTime = { 'd': 60*60*24,
              'w': 60*60*24*7,
              'm': 60*60*24*30,
              'y': 60*60*24*365,
            }


def get_rrd_indexes(rrd_file):
    ds_list = []
    inf = rrdtool.info(rrd_file)
    for k in inf:
        rs = re.search('ds\[(?P<ds>[\w?]+)\].index', k)
        if rs:
            ds = rs.group('ds')
            ds_list.append((int(inf[k]), ds))
    
    ds_list.sort()

    return ds_list

@app.errorhandler(404)
def page_not_found(e):
    return json.dumps({'data': 'Not found'})

def get_start_end_date():
    start_date = request.args.get("startdate")
    end_date = request.args.get("enddate")
    period = request.args.get("period",'d')
    if start_date:
        start = start_date + ' 00:00'
        start = int(time.mktime(time.strptime(start,"%m/%d/%Y %H:%M")))
        if end_date:
            end = end_date + ' 23:59'
            end = int(time.mktime(time.strptime(end,"%m/%d/%Y %H:%M")))
        else:
            end = int(time.time())

    else:
        start=int( time.time() - sTime[period] )
        end = int(time.time())

    return start, end, period

def get_monitoring_data(rrd_file, options, period='d', start=None, end=None):

    start, end, period = get_start_end_date()

    data_f = os.path.join(data_dir, rrd_file)
    rrd_args = ['-s', str(start), '-e', str(end)]

    for i, o in enumerate(options):

        rdef = 'DEF:data{0}={1}:{2}:AVERAGE'.format(
                    i,
                    data_f,
                    o
                    )
        rrd_args.append( rdef )

        rxport = "XPORT:data{0}:{1}".format(i,o)
        rrd_args.append( rxport )

    rrd_data=rrdtool.xport(rrd_args)

    return rrd_data

@app.route('/getldapmon/<opt>')
def get_ldap_mon(opt):
    start_date, end_date, period = get_start_end_date()
    
    if opt == 'all':
        opt = ('bytessent',
                'entriessent',
                'searchoperations',
                'addoperations',
                'deleteoperations',
                'modifyoperations'
                )
    else:
        opt = (opt.replace('_',''),)
    
    rrd_data = get_monitoring_data('ldap.rrd', opt, period, start_date, end_date)
    return json.dumps({'data': rrd_data})


@app.route('/getsysinfo/<opt>')
def get_sys_info(opt):
    start, end, period = get_start_end_date()
    
    print start, end, period

    rrd_args = ['-s', str(start), '-e', str(end)]

    if opt == 'cpuinfo':
        db_file = 'cpu_info.rrd'
        fields = ('user', 'nice', 'system', 'idle', 
                    'iowait', 'irq', 'softirq',
                    'steal', 'guest', 'guestnice',)

    elif opt == 'loadavg':
        db_file = 'load_average.rrd'
        fields = ('loadavg',)
    
    elif opt == 'memusage':
        db_file = 'mem_usage.rrd'
        fields = ('memusage',)
    
    elif opt == 'gluuauth':
        db_file = 'gluu_auth.rrd'
        fields = ('success','failure')
    
    
    elif opt== 'diskusage':
        db_file = 'disk_usage.rrd'
        ds_i = get_rrd_indexes(os.path.join(data_dir, db_file))
        fields = [di[1] for di in ds_i]
    elif opt== 'netio':
        db_file = 'net_io.rrd'
        ds_i = get_rrd_indexes(os.path.join(data_dir, db_file))
        fields = [di[1] for di in ds_i]


    data_f = os.path.join(data_dir, db_file)
    
    for i, o in enumerate(fields):
                                
        rdef = 'DEF:data{0}={1}:{2}:AVERAGE'.format(
                    i,
                    data_f,
                    o
                    )
        rrd_args.append( rdef )
        
        rxport = "XPORT:data{0}:{1}".format(i,o)
        rrd_args.append( rxport )

    print rrd_args
    rrd_data=rrdtool.xport(rrd_args)
    
    if opt== 'netio':
        negative_l = []
        for l in rrd_data['meta']['legend']:
            if l.endswith('bytes_recv'):
                negative_l.append(rrd_data['meta']['legend'].index(l))
        
        new_data =[]
                
        print rrd_data['meta']['legend'], negative_l
        
        print rrd_data['data']
        
        for d in rrd_data['data']:
            tmp = list(d)
            for i in negative_l:
                if tmp[i]:
                    tmp[i] = -1*tmp[i]
            new_data.append(tmp)
        rrd_data['data'] = new_data
    
    elif opt== 'gluuauth':
        new_data =[]
        for d in rrd_data['data']:
            tmp = list(d)
            for i in range(len(tmp)):
                if tmp[i]:
                    tmp[i] = int(tmp[i] *  rrd_data['meta']['step'])
            new_data.append(tmp)
            rrd_data['data'] = new_data
    
    return json.dumps({'data': rrd_data})



if __name__ == "__main__":
    app.debug = True
    #app.run(ssl_context='adhoc', port=10443)
    app.run(host="0.0.0.0",port=10443)
