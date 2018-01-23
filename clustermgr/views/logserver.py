"""A Flask blueprint with the views and the business logic dealing with
the logging server managed in the cluster-manager
"""
from celery import group
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


def search_by_filters(type_="", message="", host="", page=1, per_page=10):
    influx = InfluxDBClient(database="gluu_logs")
    influx.create_database("gluu_logs")

    try:
        page = int(page)
    except ValueError:
        page = 1

    if page < 1:
        page = 1

    offset = (page - 1) * per_page

    # queryset
    qs = ["SELECT * FROM logs"]

    tags = {}

    where_clause = []
    if type_:
        where_clause.append("type = '{}'".format(type_))
    if host:
        # IP is chosen because filebeat strips dotted hostname
        where_clause.append("ip = '{}'".format(host))
    if message:
        where_clause.append("message =~ /{}/".format(message))
    if where_clause:
        qs.append("WHERE {}".format(" AND ".join(where_clause)))

    qs.append("ORDER BY time DESC")
    qs.append("LIMIT {}".format(per_page))
    qs.append("OFFSET {}".format(offset))

    rs = influx.query(" ".join(qs))
    return rs.get_points(tags=tags)


@log_mgr.route("/")
def index():
    err = ""
    logs = []
    page = request.values.get("page", 1)

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
            page=page,
        )
    except (InfluxDBClientError, ConnectionError) as exc:
        err = "Unable to connect to InfluxDB"
        current_app.logger.info("{}; reason={}".format(err, exc))
    return render_template("log_index.html", form=form, logs=logs,
                           err=err, page=page)


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
    task = group([
        collect_logs.s(server.hostname, server.ip, "/tmp/gluu-filebeat")
        for server in Server.query
    ])
    task.apply_async()

    flash("Collecting logs from available remote servers may take awhile. "
          "Refresh the page after few seconds.",
          "info")
    return redirect(url_for(".index"))
