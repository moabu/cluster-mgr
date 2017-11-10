import os
import time
import requests
import json

from flask import Flask, request, Response, make_response, render_template,\
                    redirect, url_for, flash





app = Flask(__name__)

from ldap_monitor_options import searchlist
from rrd_functions import get_ldap_monitoring_data, periods

@app.route('/')
def index():

    return render_template('intro.html', options=searchlist.keys())


def get_chart_data(hosts, opt, period, start_date='', end_date=''):
    
    if start_date== None:
        start_date = ''
    if end_date== None:
        end_date = ''
    
    rrd_data = {}

    for h in hosts:

        g_data =[]

        req_addr = 'http://{0}:10443/getldapmon/{1}?startdate={2}&enddate={3}&period={4}'.format(

                                            h, opt,
                                            start_date,
                                            end_date,
                                            period,
                                            )
        print(req_addr)
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
    
    return rrd_data

@app.route('/singlegraph/<opt>/<period>')
def single_graph(opt, period):

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

    rrd_data = get_chart_data(hosts, opt, period, start_date, end_date)
    
    data_dict={ opt: rrd_data}
        
    
    return render_template('graph.html', 
                            options=searchlist,
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

    for opt in opt_list:
        g_data = get_chart_data(hosts, opt, period, start_date, end_date)
        data_dict[opt] = g_data


    return render_template('graph.html', 
                            options=searchlist,
                            opt = None,
                            width=650,
                            height=350,
                            title="Multi graph",
                            data=data_dict,
                            opt_list = opt_list,
                            period=period_s,
                            periods=periods,
                            hosts=hosts)
    
    
if __name__ == '__main__':

    app.debug=True #!! WARNING: comment out this line in production !!
    app.secret_key = 'this_is_secret_key_for_gluu_monitoring'
    app.run(host="0.0.0.0")


