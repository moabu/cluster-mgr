import json

from celery.utils.log import get_task_logger
from flask import current_app
from flask import render_template
from influxdb import InfluxDBClient

from ..core.remote import RemoteClient
from ..extensions import celery
from ..extensions import wlogger
from ..models import AppConfiguration
from ..models import Server

task_logger = get_task_logger(__name__)


_ELASTIC_YUM_REPO = """[elastic-6.x]
name=Elastic repository for 6.x packages
baseurl=https://artifacts.elastic.co/packages/6.x/yum
gpgcheck=1
gpgkey=https://artifacts.elastic.co/GPG-KEY-elasticsearch
enabled=1
autorefresh=1
type=rpm-md
"""


def _filebeat_to_influx(log):
    # Example:
    #
    #     {
    #         u'beat': {u'hostname': u'gluu-elk', u'name': u'gluu-elk', u'version': u'5.6.3'},
    #         u'fields': {u'ip': u'172.40.40.40', u'gluu': {u'chroot': True, u'version': u'3.1.1'}, u'os': u'Ubuntu 14.04', u'type': u'httpd'},
    #         u'@timestamp': u'2018-01-19T15:09:12.096Z',
    #         u'source': u'/var/log/apache2/access.log',
    #         u'offset': 972,
    #         u'input_type': u'log',
    #         u'message': u'::1 - - [19/Jan/2018:15:09:11 +0000] "GET /g HTTP/1.1" 404 433 "-" "curl/7.35.0"',
    #     }
    _log = {}
    _log["time"] = log["@timestamp"]
    _log["measurement"] = "logs"
    _log["tags"] = log["fields"]
    _log["tags"]["hostname"] = log["beat"]["hostname"]
    _log["fields"] = {k: v for k, v in log.iteritems() if k in ("message", "source")}
    return _log


def parse_log(log, influx_fmt=True):
    json_log = None

    try:
        json_log = json.loads(log)
        if influx_fmt:
            json_log = _filebeat_to_influx(json_log)
    except ValueError as exc:
        # something is wrong when converting string into dict
        task_logger.warn("unable to parse the log; reason={}".format(exc))
    return json_log


@celery.task
def collect_logs(host, ip, path, influx_fmt=True):
    dbname = current_app.config["INFLUXDB_LOGGING_DB"]
    logs = []
    rc = RemoteClient(host, ip)

    try:
        rc.startup()
        _, stdout, stderr = rc.run("cat {}".format(path))
        if not stderr:
            logs = filter(None, [parse_log(log) for log in stdout.splitlines()])
    except Exception as exc:
        task_logger.warn("Unable to collect logs from remote server;"
                         " reason={}".format(exc))
    finally:
        rc.close()

    influx = InfluxDBClient(database=dbname)
    influx.create_database(dbname)
    return influx.write_points(logs)


def _install_filebeat(task_id, server, rc):
    """Installs filebeat.

    Docs at https://www.elastic.co/guide/en/beats/filebeat/current/setup-repositories.html.
    """
    stdout = ""
    stderr = ""
    opsys = (server.os or "").lower()

    if opsys.startswith("ubuntu"):
        cmd_list = [
            "export DEBIAN_FRONTEND=noninteractive",
            "apt-get install -y apt-transport-https",
            "wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | apt-key add -",
            "echo 'deb https://artifacts.elastic.co/packages/6.x/apt stable main' | tee /etc/apt/sources.list.d/elastic-6.x.list",
            "apt-get update && apt-get install -y filebeat",
            "update-rc.d filebeat defaults 95 10",
        ]
    elif opsys.startswith("centos"):
        cmd_list = [
            "rpm --import https://packages.elastic.co/GPG-KEY-elasticsearch",
            "echo '{}' > /etc/yum.repos.d/elastic.repo".format(_ELASTIC_YUM_REPO),
            "yum install -y filebeat",
            "chkconfig --add filebeat",
        ]
    else:
        cmd_list = []
        task_logger.warn("Unable to determine underlying OS")

    for cmd in cmd_list:
        wlogger.log(task_id, cmd, "info", server_id=server.id)
        _, stdout, stderr = rc.run(cmd)
        if stderr:
            return stdout, stderr
    return stdout, stderr


def _render_filebeat_config(task_id, server, rc):
    # render filebeat.yml and upload to server
    appconf = AppConfiguration.query.first()

    with current_app.app_context():
        ctx = {
            "ip": server.ip,
            "os": server.os,
            "chroot": "true" if server.gluu_server is True else "",
            "chroot_path": "/opt/gluu-server-{}".format(appconf.gluu_version) if server.gluu_server else "",
            "gluu_version": appconf.gluu_version,
        }
        txt = render_template("filebeat/filebeat.yml", **ctx)
        wlogger.log(task_id, "uploading filebeat.yml to remote server", "info", server_id=server.id)
        status, maybe_err = rc.put_file("/etc/filebeat/filebeat.yml", txt)
        return status, maybe_err


def _restart_filebeat(task_id, server, rc):
    opsys = (server.os or "").lower()

    if opsys in ("centos 6", "ubuntu 14"):
        cmd = "service filebeat restart"
    elif opsys in ("centos 7", "ubuntu 16"):
        cmd = "systemctl enable filebeat && systemctl restart filebeat"
    else:
        task_logger.warn("Unable to determine underlying OS")
        return "", ""

    wlogger.log(task_id, cmd, "info", server_id=server.id)
    _, stdout, stderr = rc.run(cmd)
    return stdout, stderr


@celery.task(bind=True)
def setup_components(self):
    tid = self.request.id
    servers = Server.query.all()

    for server in servers:
        # establishes SSH connection
        wlogger.log(
            tid,
            "Making SSH connection to the server {}.".format(server.hostname),
            "info",
            server_id=server.id,
        )

        rc = RemoteClient(server.hostname, server.ip)
        try:
            rc.startup()

            # installs filebeat
            _, stderr = _install_filebeat(tid, server, rc)
            if stderr:
                wlogger.log(
                    tid,
                    "Cannot install filebeat component; reason={}".format(stderr),
                    "warning",
                    server_id=server.id,
                )

            # renders filebeat config
            uploaded, stderr = _render_filebeat_config(tid, server, rc)
            if not uploaded:
                wlogger.log(
                    tid,
                    "Cannot render/upload filebeat.yml; reason={}".format(stderr),
                    "warning",
                    server_id=server.id,
                )

            # restarts filebeat service
            # note, restarting filebeat service may gives unwanted output,
            # hence we skip checking the result of running command
            _restart_filebeat(tid, server, rc)
        except Exception as exc:
            wlogger.log(
                tid,
                "Cannot establish SSH connection {}".format(exc),
                "warning",
                server_id=server.id,
            )
            wlogger.log(
                tid,
                "Ending server setup process.",
                "error",
                server_id=server.id,
            )
            return False
        finally:
            rc.close()
    return True


@celery.task(bind=True)
def setup_influxdb(self):
    tid = self.request.id

    # @TODO: do we need to install influxdb locally?
    dbname = current_app.config["INFLUXDB_LOGGING_DB"]

    wlogger.log(
        tid,
        "Creating InfluxDB database {}".format(dbname),
        "info",
    )

    influx = InfluxDBClient(database=dbname)
    influx.create_database(dbname)
    return True
