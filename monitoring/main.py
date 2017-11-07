import os
import time
from flask import Flask, request, Response, make_response, render_template, redirect, url_for, flash





app = Flask(__name__)

from ldap_monitor_options import searchlist
from rrd_functions import get_ldap_monitoring_data

@app.route('/')
def index():

    return render_template('intro.html', options=searchlist.keys())


    
@app.route('/singlegraph/<opt>/<dtype>')
def single_graph(opt, dtype):

    hosts = ('c4.gluu.org','c5.gluu.org')

    title = opt.replace('_', ' ').title()


    rrd_data = get_ldap_monitoring_data(hosts, opt.replace('_',''), 'd')

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

    vaxis = searchlist[opt][2]

    return render_template('single_graph.html', 
                            options=searchlist.keys(),
                            title=title,
                            data=g_data,
                            vaxis=vaxis,
                            hosts=hosts)
    
if __name__ == '__main__':

    app.debug=True #!! WARNING: comment out this line in production !!
    app.run(host="0.0.0.0")


