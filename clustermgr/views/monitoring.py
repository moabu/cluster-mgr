# -*- coding: utf-8 -*-
# import os
import time
import json
from datetime import timedelta
import requests

requests.packages.urllib3.disable_warnings()

from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify
# from flask import current_app as app
from influxdb import InfluxDBClient
from clustermgr.core.remote import RemoteClient

# from clustermgr.extensions import celery
from clustermgr.core.license import license_reminder
from clustermgr.core.license import license_required
from clustermgr.core.license import prompt_license

from clustermgr.models import Server, AppConfiguration

from clustermgr.tasks.monitoring import install_monitoring, install_local, \
    remove_monitoring

from clustermgr.monitoring_defs import left_menu, items, periods

from clustermgr.core.utils import get_setup_properties, \
    get_opendj_replication_status

monitoring = Blueprint('monitoring', __name__)
monitoring.before_request(prompt_license)
monitoring.before_request(license_required)
monitoring.before_request(license_reminder)

#Influxdb client
client = InfluxDBClient(
            host='localhost',
            port=8086,
            database='gluu_monitoring'
        )

def get_legend(f):
    """Returns legend for graphics.
    
    Args:
        f (atring): measurmement.
    
    Returns: 
        Either a tuple for multiple legends or strings for single legend
    """
    
    acl = f.find('_')
    if acl:
        return f[:acl], f[acl+1:]
    return f

def get_period_text():
    """Returns periods for statistiscs.
    
    Returns:
        period for statistics
    """
    period = request.args.get('period','d')
    startdate = request.args.get('startdate')
    enddate = request.args.get('enddate')

    if startdate:
        ret_text = startdate + ' - '
        if enddate:
            ret_text += enddate
        else:
            ret_text += 'Now'
    else:
        ret_text = periods[period]['title']


    return ret_text



def get_mean_last(measurement, host):
    """Returns average of measuremet for a host.
    
    Args:
        measurements (string): measurement whose average to be returned
        host (string): server hostname
        
    returns: 
        Average of measurement for host
    """
    querym = 'SELECT mean(*) FROM "{}"'.format(host +'_'+ measurement)
    resultm = client.query(querym, epoch='s')
    queryl = 'SELECT * FROM "{}" ORDER BY DESC LIMIT 1'.format(host +'_'+ measurement)
    resultl = client.query(queryl, epoch='s')

    return resultm.raw['series'][0]['values'][0][1], resultl.raw['series'][0]['values'][0][1]



def getData(item, step=None):

    """Retreives data form influxdb with predefined aggregate functions in
       monitoring_defs.py
    
    Args:
        item (string): measurement
        step (integer): If not provided default step defined in 
                monitoring_defs.py will be used for current period
        
    returns: 
        A compound data will be returned to be visualized by Google graphipcs.
    """

    servers = Server.query.all()


    # Gluu authentications will only be for primary server
    if item == 'gluu_authentications':
        servers = ( Server.query.filter_by(primary_server=True).first() ,)

    # Determine period
    period = request.args.get('period','d')

    startdate = request.args.get('startdate')
    enddate = request.args.get('enddate')

    # If enddate is not given, it is current date
    if not enddate:
        enddate = time.strftime('%m/%d/%Y', time.localtime())

    if startdate:
        # enddate can't be greater than start date
        if enddate < startdate:
            flash("End Date must be greater than Start Date",'warning')
            start = time.time() - periods[period]['seconds']
            end = time.time()
            if not step:
                step = periods[period]['step']
        else:
            #append 00:00 for startdate and 23:59 for end date
            start = startdate + ' 00:00'
            start = int(time.mktime(time.strptime(start,"%m/%d/%Y %H:%M")))
            end = enddate + ' 23:59'
            end = int(time.mktime(time.strptime(end,"%m/%d/%Y %H:%M")))
            #If step is not provied, calculate step
            if not step:
                step = int((end-start)/365)

    else:
        # If enddate and start date is not provided, start date is current time
        # minus period and end date is current time
        start = time.time() - periods[period]['seconds']
        end = time.time()
        if not step:
            step = periods[period]['step']

    measurement, field = items[item]['data_source'].split('.')

    ret_dict = {}


    # retreive data from influxdb wiht aggregate functions
    for server in servers:

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

        measurement_d = server.hostname+'_'+ measurement

        query = ('SELECT {} FROM "{}" WHERE '
                  'time >= {}000000000 AND time <= {}000000000 '
                  'GROUP BY time({}s)'.format(
                    aggr_f,
                    measurement_d,
                    int(start),
                    int(end),
                    step,
                    )
                )

        result = client.query(query, epoch='s')

        data_dict = {}

        data = []

        # Format data to be used by Google graphics
        if measurement == 'cpu_info':
            legends = [
                    'guest', 'idle', 'iowait',
                    'irq', 'nice', 'softirq',
                    'steal', 'system', 'user'
            ]

            for d in result[measurement_d]:
                djformat = 'new Date("{}")'.format(time.ctime(d['time']))
                tmp = [djformat]

                for f in legends:
                    if measurement == 'cpu_info':
                        if  d['difference_'+f] < 0:
                            tmp.append( 0 )
                        else:
                            tmp.append( d['difference_'+f] )
                    else:
                        tmp.append( d['difference_'+f] )

                data.append(tmp)

        else:
            legends = []
            if result.raw.get('series'):
                for s in result.raw['series'][0]['values']:
                    djformat = 'new Date("{}")'.format(time.ctime(s[0]))
                    tmp = [djformat]
                    for f in s[1:]:
                        if f:
                            if item in ['add_requests', 'search_requests',
                                        'modify_requests', 'delete_requests']:
                                tmp.append(abs(f))
                            else:
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
    
    """Retreives uptime for host
    
    Args:
        host (string): hostname of server
        
    returns: 
        Uptime for host
    """
    
    c = RemoteClient(host)
    try:
        c.startup()
    except:
        flash("SSH Connection to host {} could not be established".format(host))
        return
    try:
        #Execute script on the remote server, fetch output and convert json data
        #to Python dictionary
        cmd = 'python /var/monitoring/scripts/get_data.py age'
        result = c.run(cmd)
        data = json.loads(result[1])
        return str(timedelta(seconds=data['data']['uptime']))
    except:
        flash("Uptime information could not be fethced from {}".format(host))


def check_data(hostname):

    """Checks if data ready for hostneme
    
    Args:
        host (string): hostname of server
        
    returns: 
        True if data is ready, otherwise returns False
    """

    result = client.query("SHOW MEASUREMENTS")

    if not 'series' in result.raw:
        return False

    m = hostname+'_cpu_percent'

    if not [m] in result.raw['series'][0]['values']:
        return False

    return True


@monitoring.route('/')
def home():
    
    """This view provides home page of monitoring."""
    
    servers = Server.query.all()

    app_config = AppConfiguration.query.first()

    #If configuration was not done redirect to configuration page
    if not app_config:
        return redirect(url_for("index.app_configuration"))

    #If monitoring components was not installed redirect to monitoring
    #introduction page
    if not app_config.monitoring:
        return render_template('monitoring_intro.html')

    data_ready = None

    #Retreival of data takes a time after monitoring components were installed 
    #both on remote servers and on local machine. Check if and data was
    #fetched from remote servers.
    try:
        data_ready = check_data(servers[-1].hostname)
    except:
        flash("Error getting data from InfluxDB")
        return render_template( 'monitoring_error.html')
    #If data was not reteived, display that data was not retreived yet.
    if not data_ready:
        return render_template('monitoring_nodata.html')

    hosts = []

    for server in servers:
        hosts.append({
                    'name': server.hostname,
                    'id': server.id
                    })

    data = {'uptime':{}}

    #On the monitoring home page, we will display uptime, cpu and memeory usage
    #of servers in cluster.
    try:
        data['cpu']= getData('cpu_percent', step=1200)
        data['mem']= getData('memory_usage', step=1200)
    except:
        flash("Error getting data from InfluxDB")
        return render_template( 'monitoring_error.html')

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


@monitoring.route('/setup')
def setup_index():
    
    """This view provides setting up monitoring"""
    
    servers = Server.query.all()
    return render_template("monitoring_setup.html", servers=servers)



@monitoring.route('/setuplocal')
def setup_local():
    
    """This view provides setting up monitoring components on local machine"""
    server = Server( hostname='localhost', id=0)

    task = install_local.delay()
    return render_template('monitoring_setup_logger.html', step=2,
                           task_id=task.id, servers=[server])



@monitoring.route('/setupservers')
def setup():
    
    """This view provides setting up monitoring components on remote servers"""
    
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

    """This view displays system related statistics"""

    #First get data from influxdb
    try:
        data = getData(item)
    except:
        flash("Error getting data from InfluxDB")
        return render_template( 'monitoring_error.html')

    #Default template is 'monitoring_graphs.html'
    temp = 'monitoring_graphs.html'
    title= item.replace('_', ' ').title()
    data_g = data
    colors={}
    
    #if measurement is not 'cpu_usage', use 'monitoring_graph_system.html'
    #template
    if not item == 'cpu_usage':
        temp = 'monitoring_graph_system.html'

    #colors to be used in giraphics
    line_colors = ('#DC143C', '#DEB887',
                   '#006400', '#E9967A', '#1E90FF')

    #For network IO, me make inbound tarffic as nagitive
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

    #We should determine max and min value for axis so that on the multiple
    #graphics, each servers' axis are the same
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

    """This view displays replication status of ldap servers"""

    prop = get_setup_properties()
    rep_status = get_opendj_replication_status()

    stat = ''
    if not rep_status[0]:
        flash(rep_status[1], "warning")
    else:
        stat = rep_status[1]

    return render_template('monitoring_replication_status.html',
                        left_menu=left_menu,
                        stat=stat,
                        items=items,
                        )



@monitoring.route('/allldap/<item>')
def ldap_all(item):
    """This view will displaye selected ldap statistics on a single page"""
    return "Not Implemented"


@monitoring.route('/ldap/<item>/')
def ldap_single(item):

    """This view displays ldap statistics"""

    try:
        data = getData(item)
    except:
        return render_template( 'monitoring_error.html')

    return render_template( 'monitoring_ldap_single.html',
                            left_menu = left_menu,
                            items=items,
                            width=1200,
                            height=500,
                            title= item.replace('_', ' ').title(),
                            period = get_period_text(),
                            data=data,
                            item=item,
                            periods=periods,
                            )

@monitoring.route('/remove')
def remove():
    """This view will remove monitoring components"""
    
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
    local_id = 100000000
    local_server = Server( hostname='localhost', id=local_id)
    servers.append(local_server)
    
    task = remove_monitoring.delay(local_id=local_id)
    return render_template('monitoring_remove_logger.html', step=1,
                           task_id=task.id, servers=servers)



@monitoring.route('/serverstat')
def get_server_status():

    servers = Server.query.all()

    services = {
                'oxauth': '.well-known/openid-configuration',
                'identity': 'identity/restv1/scim-configuration',
                'shib': 'idp/shibboleth',
                'passport': 'passport'
            }

    status = {}
    active_services = ['oxauth', 'identity']
    prop = get_setup_properties()

    if prop['installSaml']:
        active_services.append('shib')

    if prop['installPassport']:
        active_services.append('passport')


    for server in servers:
        status[server.id] = {}
        for service in active_services:
            try:
                url = 'https://{0}/{1}'.format(server.hostname, services[service])
                r = requests.get(url, verify=False)
                status[server.id][service]=r.ok
            except:
                pass

    return jsonify(status)
