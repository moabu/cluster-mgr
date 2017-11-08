import os
import time
from flask import Flask, request, Response, make_response, render_template, redirect, url_for, flash





app = Flask(__name__)

from ldap_monitor_options import searchlist
from rrd_functions import get_ldap_monitoring_data, periods

@app.route('/')
def index():

    return render_template('intro.html', options=searchlist.keys())

def get_chart_data(hosts, opt, period):
    
    rrd_data = get_ldap_monitoring_data(hosts, opt.replace('_',''), period)

    start = rrd_data["meta"]["start"]
    step = rrd_data["meta"]["step"]

    g_data =[]

    for d in rrd_data['data']:
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
    
    return g_data

@app.route('/singlegraph/<opt>/<period>')
def single_graph(opt, period):

    hosts = ('c4.gluu.org','c5.gluu.org')

    title = opt.replace('_', ' ').title()



    g_data = get_chart_data(hosts, opt, period)
    vaxis = searchlist[opt][2]
    
    return render_template('single_graph.html', 
                            options=searchlist.keys(),
                            title=title,
                            data=g_data,
                            vaxis=vaxis,
                            opt=opt,
                            period=periods[period],
                            periods=periods,
                            hosts=hosts)


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


    data_dict =  {}

    for opt in opt_list:
        g_data = get_chart_data(hosts, opt, period)
        data_dict[opt] = g_data


    return render_template('graph.html', 
                            options=searchlist,
                            title="Multi graph",
                            data=data_dict,
                            opt_list = opt_list,
                            period=periods[period],
                            periods=periods,
                            hosts=hosts)
    
    
if __name__ == '__main__':

    app.debug=True #!! WARNING: comment out this line in production !!
    app.run(host="0.0.0.0")


