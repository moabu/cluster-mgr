"""A Flask blueprint with the views and the business logic dealing with
the logging server managed in the cluster-manager
"""
import os

from celery import group
from flask import Blueprint
from flask import render_template
from flask import request
from flask import current_app
from flask import flash
from flask import redirect
from flask import url_for
from flask_login import login_required
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError
from requests.exceptions import ConnectionError

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.license import license_required
from ..core.utils import as_boolean, parse_setup_properties
from ..forms import LogSearchForm
from ..models import Server
from ..models import AppConfiguration
from ..tasks.log import collect_logs
from ..tasks.log import setup_filebeat
from ..tasks.log import remove_filebeat
# from ..tasks.log import setup_influxdb

log_mgr = Blueprint('log_mgr', __name__)
log_mgr.before_request(prompt_license)
log_mgr.before_request(license_required)
log_mgr.before_request(license_reminder)


def search_by_filters(dbname, type_="", message="", host="",
                      page=1, per_page=50):
    influx = InfluxDBClient(database=dbname)
    influx.create_database(dbname)

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
@login_required
def index():
    err = ""
    logs = []
    page = request.values.get("page", 1)

    # populate host drop-down
    servers = [("", "")]
    for server in Server.query:
        servers.append((server.ip, "{}/{}".format(server.hostname, server.ip)))

    form = LogSearchForm()
    prop = parse_setup_properties(
            os.path.join(current_app.config['DATA_DIR'], 'setup.properties')
        )

    if as_boolean(prop['installPassport']):
        form.type.choices.append(("passport", "Passport"))
    
    if as_boolean(prop['installSaml']):
        form.type.choices.append(("shibboleth", "Shibboleth IDP"))
    
    form.host.choices = servers
    form.message.data = request.values.get("message")
    form.type.data = request.values.get("type")
    form.host.data = request.values.get("host")

    try:
        logs = search_by_filters(
            current_app.config["INFLUXDB_LOGGING_DB"],
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


@log_mgr.route("/setup/")
@login_required
def setup():
    servers = Server.query.all()
    app_conf = AppConfiguration.query.first()
    
    if not app_conf.monitoring:
        return render_template("log_setup_error.html")
    
    
    if app_conf:
        offline = app_conf.offline
    else:
        offline = False
    return render_template("log_setup.html", servers=servers, offline=offline)


@log_mgr.route("/install_filebeat/")
@login_required
def install_filebeat():
    # checks for existing app config
    if not AppConfiguration.query.count():
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    # checks for existing servers
    servers = Server.get_all()

    if not servers:
        flash("Add servers to the cluster before attempting to manage logs",
              "warning")
        return redirect(url_for('index.home'))

    force_install = as_boolean(request.values.get("force_install", False))

    task = setup_filebeat.delay(force_install=force_install)

    title = 'Install Filebeat'
    nextpage=url_for('log_mgr.index')
    whatNext="Logging Page"

    return render_template('logger_single.html',
                           task_id=task.id, title=title,
                           nextpage=nextpage, whatNext=whatNext,
                           task=task, multiserver=servers)


@log_mgr.route("/collect/")
@login_required
def collect():
    # checks for existing app config
    if not AppConfiguration.query.count():
        flash("The application needs to be configured first. Kindly set the "
              "values before attempting clustering.", "warning")
        return redirect(url_for("index.app_configuration"))

    # checks for existing servers
    servers = Server.get_all()

    if not servers:
        flash("Add servers to the cluster before attempting to manage logs",
              "warning")
        return redirect(url_for('index.home'))

    task = group([
        collect_logs.s(server.id, "/tmp/gluu-filebeat")
        for server in servers
    ])
    task.apply_async()

    flash("Collecting logs from available remote servers may take a while. "
          "Refresh the page after a few seconds.",
          "info")
    return redirect(url_for(".index"))


@log_mgr.route("/uninstall_filebeat")
@login_required
def uninstall_filebeat():
    servers = Server.get_all()
    task = remove_filebeat.delay()

    title = 'Uninstall Filebeat'
    nextpage=url_for('log_mgr.index')
    whatNext="Logging Page"

    return render_template('logger_single.html',
                           task_id=task.id, title=title,
                           nextpage=nextpage, whatNext=whatNext,
                           task=task, multiserver=servers)
