import json
import rrdtool
import time
import os

from flask import Flask, request, redirect, url_for


app = Flask(__name__)

__SECRET_KEY__ = '62cc35df-af28-48ea-a623-79910f6743f8'


data_dir = '/var/monitoring'

#@app.before_request
#def require_authorization():
#    if  request.headers.get('secret') != __SECRET_KEY__:
#        return json.dumps({'data': 'Unauthorized'})


@app.errorhandler(404)
def page_not_found(e):
    return json.dumps({'data': 'Not found'})

def get_start_end_date():
    start_date = request.args.get("startdate")
    end_date = request.args.get("enddate")
    period = request.args.get("period",'d')
    if start_date:
        start_date = start_date + ' 00:00'
        start_date = int(time.mktime(time.strptime(start_date,"%m/%d/%Y %H:%M")))
        if end_date:
            end_date = end_date + ' 23:59'
            end_date = int(time.mktime(time.strptime(end_date,"%m/%d/%Y %H:%M")))
        else:
            end_date = int(time.time())

    return start_date, end_date, period

def get_monitoring_data(rrd_file, options, period='d', start=None, end=None):

    if not start:
        sTime = { 'd': 60*60*24,
                      'w': 60*60*24*7,
                      'm': 60*60*24*30,
                      'y': 60*60*24*365,
                    }

        start=int( time.time() - sTime[period] )
        end = int(time.time())

    data_f = os.path.join(data_dir, rrd_file)
    rrd_args = ['-s', str(start), '-e', str(end)]

    for i, o in enumerate(options):

        rdef = 'DEF:data{0}={1}:{2}:AVERAGE'.format(
                    i,
                    data_f,
                    o
                    )
        rrd_args.append( rdef )

        rxport = "XPORT:data{0}:Data".format(i)
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


if __name__ == "__main__":
    app.debug = True
    #app.run(ssl_context='adhoc', port=10443)
    app.run(port=10443)
