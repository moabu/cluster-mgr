import json
import rrdtool
import time
import os
import re

from flask import Flask, request, redirect, url_for
import sqlite3

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


@app.route('/getsqlite/<measurement>/<start>')
def get_sqlite_stats(measurement, start):
    db_file = os.path.join(data_dir, 'gluu_monitoring.sqlite3')
    with sqlite3.connect(db_file) as con:
        cur = con.cursor()
        cur.execute('SELECT * FROM {} WHERE time > {}'.format(measurement, start))
        result = cur.fetchall()
        feilds = [ d[0] for d in cur.description ]
        data = result

    return json.dumps({'data':{'fields':feilds, 'data': data}})




if __name__ == "__main__":
    app.debug = True
    #app.run(ssl_context='adhoc', port=10443)
    app.run(host="0.0.0.0",port=10443)
