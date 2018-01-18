# -*- coding: utf-8 -*-
import os
import time
import json
from datetime import timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session
from flask import current_app as app
from influxdb import InfluxDBClient
from clustermgr.core.remote import RemoteClient


from clustermgr.core.license import license_reminder
from clustermgr.extensions import celery
from clustermgr.core.license import prompt_license

from clustermgr.models import Server, AppConfiguration

from clustermgr.tasks.monitoring import install_monitoring, install_local


from clustermgr.monitoring_defs import left_menu, items, periods




monitoring = Blueprint('monitoring', __name__)
monitoring.before_request(prompt_license)
monitoring.before_request(license_reminder)



def get_legend(f):
    acl = f.find('_')
    if acl:
        return f[:acl], f[acl+1:]
    return f

def get_period_text():
    period = request.args.get('period','d')
    startdate = request.args.get('startdate')
    enddate = request.args.get('enddate')

    if startdate:
        print ("START DATE",startdate)
        ret_text = startdate + ' - '
        if enddate:
            ret_text += enddate
        else:
            ret_text += 'Now'
    else:
        ret_text = periods[period]['title']
    

    return ret_text



def get_mean_last(measurement, host):

    client = InfluxDBClient(
            host='localhost', 
            port=8086, 
            database='gluu_monitoring'
            )
                            
    querym = 'SELECT mean(*) FROM {}'.format(host.replace('.','_') +'_'+ measurement)
    resultm = client.query(querym, epoch='s')
    queryl = 'SELECT * FROM {}  ORDER BY DESC LIMIT 1'.format(host.replace('.','_') +'_'+ measurement)
    resultl = client.query(queryl, epoch='s')
    
    print resultm.raw, resultl.raw
    
    return resultm.raw['series'][0]['values'][0][1], resultl.raw['series'][0]['values'][0][1]


def getData(item, step=None):

    servers = Server.query.all()


    # Gluu authentications will only be for primary server
    if item == 'gluu_authentications':
        servers = ( Server.query.filter_by(primary_server=True).first() ,)

    period = request.args.get('period','d')
    startdate = request.args.get('startdate')
    enddate = request.args.get('enddate')
    
    if not enddate:
        enddate = time.strftime('%m/%d/%Y', time.localtime())

    if startdate:
        print "Start date"
        if enddate < startdate:
            flash("End Date must be greater than Start Date",'warning')
            start = time.time() - periods[period]['seconds']
            end = time.time()
            if not step:
                step = periods[period]['step']
        else:
            start = startdate + ' 00:00'
            start = int(time.mktime(time.strptime(start,"%m/%d/%Y %H:%M")))
            end = enddate + ' 23:59'
            end = int(time.mktime(time.strptime(end,"%m/%d/%Y %H:%M")))
            print "Calculate step"
            if not step:
                step = int((end-start)/365)
                
    else:
        start = time.time() - periods[period]['seconds']
        end = time.time()
        if not step:
            step = periods[period]['step']
    
    measurement, field = items[item]['data_source'].split('.')

    ret_dict = {}
    
    client = InfluxDBClient(
            host='localhost', 
            port=8086, 
            database='gluu_monitoring'
            )
    
    for server in servers:

        print("AGGR FUNCT", items[item]['aggr'])
        if items[item]['aggr'] == 'DRV':
            aggr_f = 'derivative(mean({}),1s)'.format(field)
        elif items[item]['aggr'] == 'DIF':
            aggr_f = 'DIFFERENCE(FIRST({}))'.format(field)
        elif items[item]['aggr'] == 'AVG':
            aggr_f = 'mean({})'.format(field)
        elif items[item]['aggr'] == 'SUM':
            aggr_f = 'SUM({})'.format(field)
        else:
            aggr_f = 'mean({})'.format(field)

        measurement_d = server.hostname.replace('.','_') +'_'+ measurement
        
        query = ('SELECT {} FROM {} WHERE '
                  'time >= {}000000000 AND time <= {}000000000 '
                  'GROUP BY time({}s)'.format(
                    aggr_f,
                    measurement_d,
                    int(start),
                    int(end),
                    step,
                    )
                )
        print query
        result = client.query(query, epoch='s')

        data_dict = {}

        data = []

        if measurement == 'cpu_info':
            print "ARRANGE"
            legends = [
                    'guest', 'idle', 'iowait',
                    'irq', 'nice', 'softirq',
                    'steal', 'system', 'user'
            ]

            for d in result[measurement_d]:
                tt = time.localtime(d['time'])
                djformat = time.strftime('new Date(%Y, %m, %d, %H, %M)', tt)
                tmp = [djformat]

                for f in legends:
                    tmp.append( d['difference_'+f] )

                data.append(tmp)

        else:
            legends = []
            if result.raw.get('series'):
                for s in result.raw['series'][0]['values']:
                    tt = time.localtime(s[0])
                    djformat = time.strftime('new Date(%Y, %m, %d, %H, %M)', tt)
                    tmp = [djformat]
                    for f in s[1:]:
                        if f:
                            tmp.append(f)
                        else:
                            tmp.append('null')
                    data.append(tmp)
            
                    
                   
                for f in result.raw['series'][0]['columns'][1:]:
                    legends.append( get_legend(f)[1])

        data_dict = {'legends':legends, 'data':data}
        ret_dict[server.hostname]=data_dict

    return ret_dict


def get_uptime(host):
    return

    c = RemoteClient(host)
    try:
        c.startup()
    except:
        flash("SSH Connection to host {} could not be established".format(host))
        return
    try:
        cmd = 'python /var/monitoring/scrpits/get_data.py age'
        result = c.run(cmd)
        data = json.loads(result[1])
        return str(timedelta(seconds=data['data']['uptime']))
    except:
        flash("Uptime information could not be fethced from {}".format(host))


    

@monitoring.route('/')
def home():

    servers = Server.query.all()

    hosts = []
    
    for server in servers:
        hosts.append({
                    'name': server.hostname,
                    'id': server.id
                    })

    data = {'uptime':{}}
    
    
    data['cpu']= getData('cpu_percent', step=1200)
    data['mem']= getData('memory_usage', step=1200)
    
    for host in hosts:
        m,l = get_mean_last('cpu_percent', host['name'])
        data['cpu'][host['name']]['mean']="%0.1f" % m
        data['cpu'][host['name']]['last']="%0.1f" % l
        
        m,l = get_mean_last('mem_usage', host['name'])
        data['mem'][host['name']]['mean']="%0.1f" % m
        data['mem'][host['name']]['last']="%0.1f" % l
        data['uptime'][host['name']] = get_uptime(host['name'])

    return render_template('monitoring_home.html', 
                            left_menu=left_menu,
                            items=items,
                            hosts=hosts,
                            data=data,
                            )



@monitoring.route('/setuplocal')
def setup_local():
    server = Server( hostname='localhost', id=0)
    
    task = install_local.delay()
    return render_template('monitoring_setup_logger.html', step=2,
                           task_id=task.id, servers=[server])



@monitoring.route('/setupservers')
def setup():
    servers = Server.query.all()
    appconf = AppConfiguration.query.first()
    if not appconf:
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    if not servers:
        flash("Add servers to the cluster before attempting to manage cache",
              "warning")
        return redirect(url_for('index.home'))
        
    
    servers = Server.query.all()
    task = install_monitoring.delay()
    return render_template('monitoring_setup_logger.html', step=1,
                           task_id=task.id, servers=servers)



@monitoring.route('/system/<item>')
def system(item):

    data = getData(item)

    temp = 'monitoring_graphs.html'
    title= item.replace('_', ' ').title()
    data_g = data
    colors={}
    if not item == 'cpu_usage':
        temp = 'monitoring_graph_system.html'

    line_colors = ('#DC143C', '#DEB887',
                   '#006400', '#E9967A', '#1E90FF')

    if item == 'network_i_o':
        for host in data:
            for i, lg in enumerate(data[host]['legends']):
                if 'bytes_recv' in lg:
                    for d in data[host]['data']:
                        d[i+1]= -1 * d[i+1]
        for host in data:
            colors[host]=[]

            for i in range(len(data[host]['legends'])/2):
                colors[host].append(line_colors[i])
                colors[host].append(line_colors[i])


    max_value = 0
    min_value = 0
    print "TEST", '%' in items[item]['vAxis']

    if '%' in items[item]['vAxis']:
        max_value = 100
    
    elif items[item].get('vAxisMax'):
        max_value = items[item].get('vAxisMax')
    else:
        for h in data:
            for d in data[h]['data']:
                for v in d[1:]:
                    if not v=='null':
                        if v > max_value:
                            max_value = v
                        if v < min_value:
                            min_value = v
        max_value = int(1.1 * max_value)
        min_value = int(1.1 * min_value)


    return render_template(temp, 
                        left_menu = left_menu,
                        items=items,
                        width=650,
                        height=324,
                        title= title,
                        data= data_g,
                        item=item,
                        period = get_period_text(),
                        periods=periods,
                        v_axis_max = max_value,
                        v_min_value = min_value,
                        colors=colors
                        )

@monitoring.route('/replicationstatus')
def replication_status():
    return "Not Implemented"


@monitoring.route('/allldap/<item>')
def ldap_all(item):
    return "Not Implemented"
    
    
@monitoring.route('/ldap/<item>/')
def ldap_single(item):
    return "Not Implemented"
