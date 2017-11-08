import os
import time
from flask import Flask, request, Response, make_response, render_template, redirect, url_for, flash





app = Flask(__name__)

from ldap_monitor_options import searchlist
from rrd_functions import get_ldap_monitoring_data, periods

@app.route('/')
def index():

    return render_template('intro.html', options=searchlist.keys())


def get_start_end_date():
    start_date = request.args.get("startdate")
    end_date = request.args.get("enddate")
    print "START DATE END DATE", start_date, end_date
    if start_date:
        start_date = start_date + ' 00:00'
        start_date = int(time.mktime(time.strptime(start_date,"%m/%d/%Y %H:%M")))
        if end_date:
            end_date = end_date + ' 23:59'
            end_date = int(time.mktime(time.strptime(end_date,"%m/%d/%Y %H:%M")))
        else:
            end_date = int(time.time())

    return start_date, end_date

def get_chart_data(hosts, opt, period, start_date=None, end_date=None):
    
    rrd_data = get_ldap_monitoring_data(hosts, opt.replace('_',''), period, start_date, end_date)

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
    period_s=periods[period]
    start_date, end_date = get_start_end_date()
   
    if end_date < start_date:
       flash("End Date must be greater than Start Date")
       start_date = None
       end_date = None
    
    if start_date:
        period_s='{} - {}'.format(time.ctime(start_date), time.ctime(end_date))

    
    data_dict={ opt: get_chart_data(hosts, opt, period, start_date, end_date)}
        
    
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


    period_s=periods[period]
    start_date, end_date = get_start_end_date()
   
    if end_date < start_date:
       flash("End Date must be greater than Start Date")
       start_date = None
       end_date = None
    
    if start_date:
        period_s='{} - {}'.format(time.ctime(start_date), time.ctime(end_date))


    data_dict =  {}

    for opt in opt_list:
        g_data = get_chart_data(hosts, opt, period)
        data_dict[opt] = g_data


    return render_template('graph.html', 
                            options=searchlist,
                            opt = None,
                            width=600,
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


