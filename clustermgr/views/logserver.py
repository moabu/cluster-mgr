"""A Flask blueprint with the views and the business logic dealing with
the logging server managed in the cluster-manager
"""
import json

from flask import Blueprint
from flask import render_template
from flask import request
from influxdb import InfluxDBClient

from ..core.license import license_reminder
from ..core.remote import RemoteClient
from ..forms import LogSearchForm
from ..models import Server

log_mgr = Blueprint('log_mgr', __name__)
log_mgr.before_request(license_reminder)


def collect_remote_logs(influx_fmt=True):
    rc = RemoteClient("172.40.40.40", "172.40.40.40")
    rc.startup()
    _, stdout, stderr = rc.run("cat /tmp/gluu-filebeat")

    logs = []
    if not stderr:
        if influx_fmt:
            logs = [filebeat_to_influx(json.loads(log))
                    for log in stdout.splitlines()]
        else:
            logs = [json.loads(log) for log in stdout.splitlines()]
    rc.close()

    for log in logs:
        yield log


def filebeat_to_influx(log):
    # {
    #     u'beat': {u'hostname': u'gluu-elk', u'name': u'gluu-elk', u'version': u'5.6.3'},
    #     u'fields': {u'ip': u'172.40.40.40', u'gluu': {u'chroot': True, u'version': u'3.1.1'}, u'os': u'Ubuntu 14.04'},
    #     u'@timestamp': u'2018-01-19T15:09:12.096Z',
    #     u'source': u'/var/log/apache2/access.log',
    #     u'offset': 972,
    #     u'input_type': u'log',
    #     u'message': u'::1 - - [19/Jan/2018:15:09:11 +0000] "GET /g HTTP/1.1" 404 433 "-" "curl/7.35.0"',
    #     u'type': u'httpd',
    # }
    _log = {}
    _log["time"] = log["@timestamp"]
    _log["measurement"] = "logs"
    _log["tags"] = log["fields"]
    _log["tags"]["hostname"] = log["beat"]["hostname"]
    _log["fields"] = {k: v for k, v in log.iteritems()
                      if k in ("message", "source", "type")}
    return _log


def search_by_filters(type_="", message="", host="", limit=25, offset=0):
    influx = InfluxDBClient(database="gluu_logs")

    # queryset
    qs = ["SELECT * FROM logs"]

    tags = {}
    if type_:
        tags["type"] = type_.lower()
    if host:
        tags["hostname"] = host
    if message:
        qs.append("WHERE message =~ /{}/".format(message))

    qs.append("ORDER BY time DESC")
    qs.append("LIMIT {}".format(limit))
    qs.append("OFFSET {}".format(offset))

    rs = influx.query(" ".join(qs))
    return rs.get_points(tags=tags)


@log_mgr.route("/")
def index():
    # populate host drop-down
    servers = [("", "")]
    for server in Server.query:
        servers.append((server.hostname, server.hostname))
    servers.append(("gluu-elk", "gluu-elk"))  # dummy

    form = LogSearchForm()
    form.host.choices = servers
    form.message.data = request.values.get("message")
    form.type.data = request.values.get("type")
    form.host.data = request.values.get("host")

    logs = search_by_filters(
        type_=form.type.data,
        message=form.message.data,
        host=form.host.data,
    )
    return render_template("log_index.html", form=form, logs=logs)


@log_mgr.route("/setup/")
def setup():
    return "Logging Setup"
