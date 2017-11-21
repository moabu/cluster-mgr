import os
import time
import requests
import json


from flask import Flask, request, Response, make_response, render_template,\
                    redirect, url_for, flash



from influxdb import InfluxDBClient



from defs import left_menu, items, periods



app = Flask(__name__)



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

def getData(item):

    hosts = ('c4.gluu.org',
            'c5.gluu.org',
            )

    # Gluu authentications will only be for primary server
    if item == 'gluu_authentications':
        hosts = ('c4.gluu.org',)

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
            step = periods[period]['step']
        else:
            start = startdate + ' 00:00'
            start = int(time.mktime(time.strptime(start,"%m/%d/%Y %H:%M")))
            end = enddate + ' 23:59'
            end = int(time.mktime(time.strptime(end,"%m/%d/%Y %H:%M")))
            print "Calculate step"
            step = int((end-start)/365)
                
    else:
        start = time.time() - periods[period]['seconds']
        end = time.time()
        step = periods[period]['step']
    
    measurement, field = items[item]['data_source'].split('.')

    ret_dict = {}
    
    for host in hosts:

        client = InfluxDBClient('localhost', 8086, 'mbaser', 'qwerty',
                                host.replace('.','_'))

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


        query = ('SELECT {} FROM {} WHERE '
                  'time >= {}000000000 AND time <= {}000000000 '
                  'GROUP BY time({}s)'.format(
                    aggr_f,
                    measurement,
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
            legends = ['system', 'user', 'nice', 'idle',
                        'iowait', 'irq', 'softirq', 'steal',
                        'guest', 'guestnice']

            for d in result['cpu_info']:
                tt = time.localtime(d['time'])
                djformat = time.strftime('new Date(%Y, %m, %d, %H, %M)', tt)
                tmp = [djformat]

                for f in legends:
                    tmp.append( d['difference_'+f] )

                data.append(tmp)

        else:
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
        
                legends = []
               
            for f in result.raw['series'][0]['columns'][1:]:
                legends.append( get_legend(f)[1])

        data_dict = {'legends':legends, 'data':data}
        ret_dict[host]=data_dict

    return ret_dict



@app.route('/')
def index():

    return render_template('intro.html', left_menu=left_menu, items=items)


@app.route('/ldap/<item>/')
def ldap_single(item):

    data = getData(item)

    return render_template( 'ldap_single.html', 
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

@app.route('/allldap/<item>')
def ldap_all(item):
    
    measurement_list = ['bytes_sent',
                'entries_sent',
                'search_operations',
                'add_operations',
                'delete_operations',
                'modify_operations'
                ]

    data_dict =  {}

    for measurement in measurement_list:
        g_data = getData(measurement)
        data_dict[measurement] = g_data

    return render_template('graph_multi.html', 
                            left_menu = left_menu,
                            items=items,
                            width=800,
                            height=325,
                            item='summary',
                            title="Multi graph",
                            data=data_dict,
                            period = get_period_text(),
                            periods=periods,
                            opt_list=measurement_list
                            )

@app.route('/system/<item>')
def system(item):

    data = getData(item)

    temp = 'graphs.html'
    title= item.replace('_', ' ').title()
    data_g = data
    colors={}
    if not item == 'cpu_usage':
        temp = 'graph_system.html'

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
                        colors=colors
                        )



if __name__ == '__main__':

    app.debug=True #!! WARNING: comment out this line in production !!
    app.secret_key = 'this_is_secret_key_for_gluu_monitoring'
    app.run(host="0.0.0.0")


