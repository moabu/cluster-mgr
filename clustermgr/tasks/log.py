import json

from celery.utils.log import get_task_logger
from influxdb import InfluxDBClient

from ..core.remote import RemoteClient
from ..extensions import celery

task_logger = get_task_logger(__name__)


def _filebeat_to_influx(log):
    # Example:
    #
    #     {
    #         u'beat': {u'hostname': u'gluu-elk', u'name': u'gluu-elk', u'version': u'5.6.3'},
    #         u'fields': {u'ip': u'172.40.40.40', u'gluu': {u'chroot': True, u'version': u'3.1.1'}, u'os': u'Ubuntu 14.04'},
    #         u'@timestamp': u'2018-01-19T15:09:12.096Z',
    #         u'source': u'/var/log/apache2/access.log',
    #         u'offset': 972,
    #         u'input_type': u'log',
    #         u'message': u'::1 - - [19/Jan/2018:15:09:11 +0000] "GET /g HTTP/1.1" 404 433 "-" "curl/7.35.0"',
    #         u'type': u'httpd',
    #     }
    _log = {}
    _log["time"] = log["@timestamp"]
    _log["measurement"] = "logs"
    _log["tags"] = log["fields"]
    _log["tags"]["hostname"] = log["beat"]["hostname"]
    _log["fields"] = {k: v for k, v in log.iteritems()
                      if k in ("message", "source", "type")}
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
    rc = RemoteClient(host, ip)
    rc.startup()
    _, stdout, stderr = rc.run("cat {}".format(path))

    logs = []
    if not stderr:
        logs = filter(None, [parse_log(log) for log in stdout.splitlines()])

    rc.close()
    return logs


@celery.task
def save_logs(logs, db_host="localhost", db_port=8086, db_name="gluu_logs"):
    influx = InfluxDBClient(host=db_host, port=db_port, database=db_name)
    task_logger.info(logs)
    return influx.write_points(logs)
