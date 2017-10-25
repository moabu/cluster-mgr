import yaml

from uuid import uuid4

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, celery, wlogger
from clustermgr.core.remote import RemoteClient, ClientNotSetupException
from clustermgr.core.utils import get_os_type
from clustermgr.core.constants import *


class YAMLTask(object):
    def __init__(self, name=None, command=None, expect=None, fail=None):
        self.id = str(uuid4())[0:8]
        self.name = name
        self.command = command
        self.expect = expect
        self.fail = fail
        self.output = ""
        self.error = ""
        self.state = None

    def from_dict(self, indict):
        self.name = indict['name']
        self.command = indict['command']
        self.expect = indict['expect'] if 'expect' in indict else None
        self.fail = indict['fail'] if 'fail' in indict else None
        return self

    def to_dict(self):
        return dict(id=self.id, action=self.command, output=self.output,
                    error=self.error, state=self.state)

    def execute(self, client, parent_id=None):
        cin, out, err = client.run(self.command)
        self.output = out
        self.error = err

        self.state = COMPLETE
        if self.expect and self.expect in out:
            self.state = SUCCESS
        if self.fail and (self.fail in err or self.fail in out):
            self.state = FAIL

        if parent_id:
            wlogger.log_raw(parent_id, self.to_dict())

    def execute_s(self, client, parent_id=None):
        if not parent_id:
            self.state=RUNNING
            for out in client.run_s(self.command):
                self.output += out
            self.state=COMPLETE

        if parent_id:
            self.state=RUNNING
            wlogger.log_raw(parent_id, self.to_dict())
            for out in client.run_s(self.command):
                self.output += out
                wlogger.update_log(parent_id, self.to_dict())

            self.state = COMPLETE
            if self.expect and self.expect in self.output:
                self.state = SUCCESS
            if self.fail and self.fail in self.output:
                self.state = FAIL
            wlogger.update_log(parent_id, self.to_dict())

    def __repr__(self):
        return '<YAMLTask {0}>'.format(self.name)


class YAMLTaskRunner(object):
    def __init__(self, yaml_file, hostname, ip=None, user='root'):
        self.yaml_file = yaml_file
        self.hostname = hostname
        self.ip = ip
        self.user = user
        self.rc = RemoteClient(hostname, ip, user)
        self.tasks = []

    def run_tasks(self, weblog_id=None, async=True):
        yaml_fo = open(self.yaml_file)
        task_map = yaml.load(yaml_fo.read(), Loader=Loader)
        try:
            self.rc.startup()
        except ClientNotSetupException as e:
            print e
            return False

        os = get_os_type(self.rc)
        self.tasks = [YAMLTask().from_dict(item) for item in task_map[os]['tasks']]
        print self.tasks
        for task in self.tasks:
            if async:
                task.execute(self.rc, weblog_id)
            else:
                task.execute_s(self.rc, weblog_id)
