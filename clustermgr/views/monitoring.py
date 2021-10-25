# -*- coding: utf-8 -*-
# import os
import time
import json
from datetime import timedelta
import requests

from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify
from flask_login import login_required

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
    get_opendj_replication_status, port_status_cmd, get_enabled_services

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
    querym = 'SELECT mean(*) FROM "{}"'.format(host.replace('.','_') +'_'+ measurement)
    resultm = client.query(querym, epoch='s')
    queryl = 'SELECT * FROM "{}"  ORDER BY DESC LIMIT 1'.format(host.replace('.','_') +'_'+ measurement)
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

    servers = Server.get_all()


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

        measurement_d = server.hostname.replace('.','_') +'_'+ measurement

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


def get_uptime(host, ssh_port):
    
    """Retreives uptime for host
    
    Args:
        host (string): hostname of server
        
    returns: 
        Uptime for host
    """
    
    c = RemoteClient(host, ssh_port=ssh_port)
    try:
        c.startup()
    except:
        flash("SSH Connection to host {} could not be established".format(host))
        return
    try:
        #Execute script on the remote server, fetch output and convert json data
        #to Python dictionary
        cmd = 'python3 /var/monitoring/scripts/get_data.py age'
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

    m = hostname.replace('.','_')+'_cpu_percent'

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
    except Exception as e:
        flash("Error getting data from InfluxDB: " + str(e))
        return render_template( 'monitoring_error.html')
    #If data was not reteived, display that data was not retreived yet.
    if not data_ready:
        return render_template('monitoring_nodata.html')

    hosts = []
    ssh_ports = {}
    for server in servers:
        hosts.append({
                    'name': server.hostname,
                    'id': server.id
                    })
        ssh_ports[server.id] = server.ssh_port
    data = {'uptime':{}}

    #On the monitoring home page, we will display uptime, cpu and memeory usage
    #of servers in cluster.
    try:
        data['cpu']= getData('cpu_percent', step=1200)
        data['mem']= getData('memory_usage', step=1200)
    except Exception as e:
        flash("Error getting data from InfluxDB: " + str(e))
        return render_template( 'monitoring_error.html')

    for host in hosts:
        m,l = get_mean_last('cpu_percent', host['name'])
        data['cpu'][host['name']]['mean']="%0.1f" % m
        data['cpu'][host['name']]['last']="%0.1f" % l

        m,l = get_mean_last('mem_usage', host['name'])
        data['mem'][host['name']]['mean']="%0.1f" % m
        data['mem'][host['name']]['last']="%0.1f" % l
        data['uptime'][host['name']] = get_uptime(host['name'], ssh_ports[host['id']])


    return render_template('monitoring_home.html',
                            left_menu=left_menu,
                            items=items,
                            hosts=hosts,
                            data=data,
                            )


@monitoring.route('/setup')
@login_required
def setup_index():
    
    """This view provides setting up monitoring"""
    
    servers = Server.query.all()
    return render_template("monitoring_setup.html", servers=servers)



@monitoring.route('/setuplocal')
@login_required
def setup_local():
    
    """This view provides setting up monitoring components on local machine"""
    server = Server( hostname='localhost', id=0)

    steps = ['Install Components on Servers', 'Setup Local Server']

    title = "Install Monitoring Componenets"
    whatNext = "Monitoring Page"
    nextpage = url_for('monitoring.home')

    task = install_local.delay()
    
    return render_template('logger_single.html',
                           title=title,
                           steps=steps,
                           task=task,
                           cur_step=2,
                           auto_next=False,
                           multiserver=[server],
                           nextpage=nextpage,
                           whatNext=whatNext
                           )


@monitoring.route('/setupservers')
@login_required
def setup():
    
    """This view provides setting up monitoring components on remote servers"""
    
    servers = Server.get_all()
    appconf = AppConfiguration.query.first()
    if not appconf:
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    if not servers:
        flash("Add servers to the cluster before attempting to manage cache",
              "warning")
        return redirect(url_for('index.home'))

    steps = ['Install Components on Servers', 'Setup Local Server']

    title = "Install Monitoring Componenets"
    whatNext = steps[1]
    nextpage = url_for('monitoring.setup_local')
    servers = Server.get_all()
    task = install_monitoring.delay()
    
    return render_template('logger_single.html',
                           title=title,
                           steps=steps,
                           task=task,
                           cur_step=1,
                           auto_next=False,
                           multiserver=servers,
                           nextpage=nextpage,
                           whatNext=whatNext
                           )

@monitoring.route('/system/<item>')
@login_required
def system(item):

    """This view displays system related statistics"""

    #First get data from influxdb
    try:
        data = getData(item)
    except Exception as e:
        flash("Error getting data from InfluxDB: " + str(e))
        return render_template( 'monitoring_error.html')

    #Default template is 'monitoring_graphs.html'
    temp = 'monitoring_graphs.html'
    title= item.replace('_', ' ').title()
    data_g = data
    colors={}
    
    #if measurement is not 'cpu_usage', use 'monitoring_graph_system.html'
    #template
    if item != 'cpu_usage':
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

            for i in range(int(len(data[host]['legends'])/2)):
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
                    if isinstance(v, float) or isinstance(v, int):
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
@login_required
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
@login_required
def ldap_all(item):
    """This view will displaye selected ldap statistics on a single page"""
    return "Not Implemented"


@monitoring.route('/ldap/<item>/')
@login_required
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
@login_required
def remove():
    """This view will remove monitoring components"""
    
    servers = Server.get_all()
    app_conf = AppConfiguration.query.first()
    if not app_conf:
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    title = "Uninstall Monitoring"
    whatNext = "Monitoring Home"
    nextpage = url_for('monitoring.home')
    servers = Server.get_all()
    task = remove_monitoring.delay()

    local_server = Server( hostname='localhost', id=9999)
    servers.append(local_server)
    
    return render_template('logger_single.html',
                           title=title,
                           task=task,
                           cur_step=1,
                           auto_next=False,
                           multiserver=servers,
                           nextpage=nextpage,
                           whatNext=whatNext
                           )

@monitoring.route('/serverstat')
@login_required
def get_server_status():

    servers = Server.get_all()


    status = {}
    active_services = get_enabled_services()

    app_conf = AppConfiguration.query.first()


    if app_conf.gluu_version.replace('nochroot-','') < '4.2.1':

        services = {
                'oxauth': '.well-known/openid-configuration',
                'identity': 'identity/restv1/scim-configuration',
                'saml': 'idp/shibboleth',
                'casa': 'casa/enrollment-api.yaml',
            }

        cmd =  '''python3 -c "import urllib2,ssl; print urllib2.urlopen('https://localhost/{}', context= ssl._create_unverified_context()).getcode()"'''

        for server in servers:
            status[server.id] = {}

            c = RemoteClient(server.hostname, ssh_port=server.ssh_port)
            c.ok = False
            try:
                c.startup()
                c.ok = True
            except Exception as e:
                pass

            for service in active_services:
                status[server.id][service] = False

                if c.ok:
                    if service == 'passport':
                        passport_cmd = port_status_cmd.format('localhost', 8090)
                        r = c.run(passport_cmd)
                        if r[1].strip()=='0':
                            status[server.id][service] = True
                    elif service == 'oxd':
                        passport_cmd = port_status_cmd.format('localhost', 8443)
                        r = c.run(passport_cmd)
                        if r[1].strip()=='0':
                            status[server.id][service] = True
                    else:
                        if service in services:
                            try:
                                run_cmd = cmd.format(services[service])
                                result = c.run(run_cmd)
                                if result[1].strip() == '200':
                                    status[server.id][service] = True
                            except Exception as e:
                                print("Error getting service status of {0} for {1}. ERROR: {2}".format(server.hostname,service, e))
    else:
        remote_cmd_raw = '''python3 -W ignore -c "import requests;r=requests.get('{}',verify=False);'''
        remote_cmd = remote_cmd_raw + '''print( 1 if r.json()['status']=='running' else 0)"'''
        remote_cmd = remote_cmd_raw + '''print( 1 if r.json()['status']=='running' else 0)"'''
        remote_sml_cmd = remote_cmd_raw + '''print( 1 if '<ds:X509Certificate>' in r.text else 0)"'''
        remote_casa_cmd = remote_cmd_raw + '''print( 1 if r.text.lower()=='ok' else 0)"'''
        remote_passport_cmd = remote_cmd_raw + '''print( 1 if r.text.lower()=='ok' else 0)"'''
        remote_passport_cmd = remote_cmd_raw + '''print( 1 if r.json().get('token_') else 0)"'''

        services = {
                'oxauth': 'http://localhost:8081/oxauth/restv1/health-check',
                'identity': 'http://localhost:8082/identity/restv1/health-check',
                'saml': 'http://localhost:8086/idp/shibboleth',
                'casa': 'http://localhost:8099/casa/health-check',
                'passport': 'http://localhost:8090/passport/token',
                'scim': 'http://localhost:8087/scim/restv1/health-check',
                'oxd': 'https://localhost:8443/health-check',
            }

        for server in servers:
            status[server.id] = {}
            c = RemoteClient(server.hostname, ssh_port=server.ssh_port)
            c.ok = False
            try:
                c.startup()
                c.ok = True
            except Exception as e:
                print(e)
                pass

            for service in active_services:
                    status[server.id][service] = False

                    service_url = services[service]
                    if c.ok:
                        if service == 'saml':
                            rcmd = remote_sml_cmd
                        elif service == 'casa':
                            rcmd = remote_casa_cmd
                        elif service == 'passport':
                            rcmd = remote_passport_cmd
                        else:
                            rcmd = remote_cmd
                        rcmd = rcmd.format(service_url)
                        print(service, rcmd)

                        r = c.run(rcmd)
                        if r[1].strip()=='1':
                            status[server.id][service] = True

    
    return jsonify(status)
