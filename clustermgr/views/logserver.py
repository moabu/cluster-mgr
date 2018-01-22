"""A Flask blueprint with the views and the business logic dealing with
the logging server managed in the cluster-manager
"""

from flask import Blueprint
from flask import render_template
from flask import request
from flask import current_app
from flask import flash
from flask import redirect
from flask import url_for
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError
from requests.exceptions import ConnectionError

from ..core.license import license_reminder
from ..forms import LogSearchForm
from ..models import Server
from ..models import AppConfiguration

from ..tasks.log import collect_logs
from ..tasks.log import setup_components
from ..tasks.log import setup_influxdb

log_mgr = Blueprint('log_mgr', __name__)
log_mgr.before_request(license_reminder)


def search_by_filters(type_="", message="", host="", limit=25, offset=0):
    influx = InfluxDBClient(database="gluu_logs")
    influx.create_database("gluu_logs")

    # queryset
    qs = ["SELECT * FROM logs"]

    tags = {}
    if type_:
        tags["type"] = type_.lower()
    if host:
        # IP is chosen because filebeat strips dotted hostname
        tags["ip"] = host
    if message:
        qs.append("WHERE message =~ /{}/".format(message))

    qs.append("ORDER BY time DESC")
    # @TODO: pagination
    qs.append("LIMIT {}".format(limit))
    qs.append("OFFSET {}".format(offset))

    rs = influx.query(" ".join(qs))
    return rs.get_points(tags=tags)


@log_mgr.route("/")
def index():
    err = ""
    logs = []

    # populate host drop-down
    servers = [("", "")]
    for server in Server.query:
        servers.append((server.ip, "{}/{}".format(server.hostname, server.ip)))

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
    except (InfluxDBClientError, ConnectionError) as exc:
        err = "Unable to connect to InfluxDB"
        current_app.logger.info("{}; reason={}".format(err, exc))
    return render_template("log_index.html", form=form, logs=logs, err=err)


@log_mgr.route("/setup_remote/")
def setup_remote():
    # checks for existing app config
    appconf = AppConfiguration.query.first()

    if not appconf:
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    # checks for existing servers
    servers = Server.query.all()

    if not servers:
        flash("Add servers to the cluster before attempting to manage logs",
              "warning")
        return redirect(url_for('index.home'))

    task = setup_components.delay()
    return render_template("log_setup.html", step=1,
                           task_id=task.id, servers=servers)


@log_mgr.route("/setup_local/")
def setup_local():
    # checks for existing app config
    appconf = AppConfiguration.query.first()

    if not appconf:
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    # checks for existing servers
    servers = [Server(id=0, hostname="localhost")]

    if not servers:
        flash("Add servers to the cluster before attempting to manage logs",
              "warning")
        return redirect(url_for('index.home'))

    task = setup_influxdb.delay()
    return render_template("log_setup.html", task_id=task.id, step=2, servers=servers)


@log_mgr.route("/collect/")
def collect():
    for server in Server.query:
        collect_logs.delay(server.hostname, server.ip, "/tmp/gluu-filebeat")
    return redirect(url_for(".index"))
