import os
import time
import requests
import json

from flask import Flask, request, Response, make_response, render_template,\
                    redirect, url_for, flash





app = Flask(__name__)

from ldap_monitor_options import searchlist
from rrd_functions import get_ldap_monitoring_data, periods


leftmenu = { 'Ldap Monitoring': ('single_graph', ['all']+searchlist.keys()),
             'System Monitoring': ('system', ['cpuinfo',
                                                'loadavg',
                                                'diskusage', 
                                                'memusage']),
            }

@app.route('/')
def index():

    return render_template('intro.html', leftmenu = leftmenu)


def get_chart_data(hosts, funct, opt, period, start_date='', end_date=''):
    
    if start_date== None:
        start_date = ''
    if end_date== None:
        end_date = ''
    
    rrd_data = {}

    legends = {}

    for h in hosts:

        g_data =[]

        req_addr = 'http://{0}:10443/{5}/{1}?startdate={2}&enddate={3}&period={4}'.format(

                                            h, opt,
                                            start_date,
                                            end_date,
                                            period,
                                            funct,
                                            )

        r = requests.get(req_addr)
        
        r_tetx = r.text
        r_tmp = json.loads(r.text)
        r_rrd_data = r_tmp['data']

        start = r_rrd_data["meta"]["start"]
        step = r_rrd_data["meta"]["step"]


        for d in r_rrd_data['data']:
            t = time.localtime(start)
            di_l = []
            for di in d:
                did = str(di) if di else 'null'
                di_l.append(did)
            
            tmp = "[new Date({}, {}, {}, {}, {}), {}],".format(
                        t.tm_year, t.tm_mon, t.tm_mday,
                        t.tm_hour, t.tm_min, ', '.join(di_l))
            g_data.append(tmp)
            start += step
            
        rrd_data[h] = g_data
        legends[h] = r_rrd_data['meta']['legend']
    return rrd_data, legends

@app.route('/singlegraph/<opt>/<period>')
def single_graph(opt, period):

    if opt=='all':
        
        return redirect(url_for('all_ldap', period=period))

    hosts = ('c4.gluu.org',
            'c5.gluu.org',
            #'localhost',
            #'192.168.56.101',
            #'192.168.56.104',
            )

    title = opt.replace('_', ' ').title()
    period_s=periods[period]
    start_date = request.args.get("startdate")
    end_date = request.args.get("enddate")
   
    if end_date < start_date:
       flash("End Date must be greater than Start Date")
       start_date = None
       end_date = None
    
    if start_date:
        period_s='{} - {}'.format(start_date, end_date)

    funct = 'getldapmon'
    rrd_data = get_chart_data(hosts, funct, opt, period, start_date, end_date)
    
    data_dict={ opt: rrd_data[0]}
        
    
    return render_template('graph.html', 
                            leftmenu = leftmenu,
                            options=searchlist,
                            group='single_graph',
                            opt = opt,
                            width=900,
                            height=500,
                            title= title,
                            data=data_dict,
                            opt_list = [opt],
                            period=period_s,
                            periods=periods,
                            )



@app.route('/allldap/<period>')
def all_ldap(period):
    hosts = ('c4.gluu.org','c5.gluu.org')
    opt_list = ['bytes_sent',
                'entries_sent',
                'search_operations',
                'add_operations',
                'delete_operations',
                'modify_operations'
                ]


    period_s=periods[period]
    start_date = request.args.get("startdate")
    end_date = request.args.get("enddate")
   
    if end_date < start_date:
       flash("End Date must be greater than Start Date")
       start_date = None
       end_date = None
    
    if start_date:
        period_s='{} - {}'.format(start_date, end_date)


    data_dict =  {}

    funct = 'getldapmon'

    for opt in opt_list:
        g_data = get_chart_data(hosts, funct, opt, period, start_date, end_date)
        data_dict[opt] = g_data[0]


    return render_template('graph.html', 
                            options=searchlist,
                            leftmenu = leftmenu,
                            group='all_ldap',
                            opt = None,
                            width=550,
                            height=325,
                            title="Multi graph",
                            data=data_dict,
                            opt_list = opt_list,
                            period=period_s,
                            periods=periods,
                            hosts=hosts)

@app.route('/system/<opt>/<period>')
def system(opt, period):

    hosts = ('c4.gluu.org',
            'c5.gluu.org',
            'localhost',
            #'192.168.56.101',
            #'192.168.56.104',
            )

    title = opt.replace('_', ' ').title()
    period_s=periods[period]
    start_date = request.args.get("startdate")
    end_date = request.args.get("enddate")
   
    if end_date < start_date:
       flash("End Date must be greater than Start Date")
       start_date = None
       end_date = None
    
    if start_date:
        period_s='{} - {}'.format(start_date, end_date)

    funct = 'getsysinfo'
    rrd_data = get_chart_data(hosts, funct, opt, period, start_date, end_date)
    
    data_dict={ opt: rrd_data[0] }

    options={'loadavg':(None, None, '5 Mins Load Average'),
             'cpuinfo':(None,None, '%'),
             'diskusage':(None,None, '%'),
             'memusage':(None,None, '%'),

    }

    if opt=='cpuinfo':
        temp = 'graphs.html'
        data_g = data_dict[opt]
        width = 600
        height = 325
        title = 'Cpu Usage'
    elif opt=='diskusage':
        temp = 'graphm.html'
        width = 600
        height = 325
        title = 'Disk Usage'
        data_g = data_dict[opt]
        
    elif opt=='loadavg':
        temp = 'graph.html'
        data_g = data_dict
        title = 'Load Average'
        width = 900
        height = 500
    elif opt=='memusage':
        temp = 'graph.html'
        data_g = data_dict
        title = 'Memory Usage'
        vMax = 100
        width = 900
        height = 500
        

    return render_template(temp, 
                            leftmenu = leftmenu,
                            options = options,
                            legends=rrd_data[1],
                            group='system',
                            opt = opt,
                            width=width,
                            height=height,
                            title= title,
                            data= data_g,
                            period=period_s,
                            opt_list = [opt],
                            periods=periods,
                            )

if __name__ == '__main__':

    app.debug=True #!! WARNING: comment out this line in production !!
    app.secret_key = 'this_is_secret_key_for_gluu_monitoring'
    app.run(host="0.0.0.0")


