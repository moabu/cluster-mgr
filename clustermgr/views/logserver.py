"""A Flask blueprint with the views and the business logic dealing with
the logging server managed in the cluster-manager
"""

from celery import chord
from flask import Blueprint
from flask import render_template
from flask import request
from flask import current_app
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError

from ..core.license import license_reminder
from ..forms import LogSearchForm
from ..models import Server

from ..tasks.log import collect_logs
from ..tasks.log import save_logs

log_mgr = Blueprint('log_mgr', __name__)
log_mgr.before_request(license_reminder)


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

    err = ""

    form = LogSearchForm()
    form.host.choices = servers
    form.message.data = request.values.get("message")
    form.type.data = request.values.get("type")
    form.host.data = request.values.get("host")

    try:
        logs = search_by_filters(
            type_=form.type.data,
            message=form.message.data,
            host=form.host.data,
        )
    except InfluxDBClientError as exc:
        err = exc
        current_app.logger.info(exc)
        logs = []
    return render_template("log_index.html", form=form, logs=logs, err=err)


@log_mgr.route("/setup/")
def setup():
    return "Logging Setup"


@log_mgr.route("/collect/")
def collect():
    servers = ["172.40.40.40"]
    task = chord(collect_logs.s(server, server, "/tmp/gluu-filebeat")
                 for server in servers)(save_logs.s())
    task.get()
    return "Collecting Logs"
