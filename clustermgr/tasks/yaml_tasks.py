import json
import os
import re
import logging

from yaml import load, dump

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import db, celery, wlogger
from clustermgr.core.remote import RemoteClient, ClientNotSetupException
from clustermgr.core.utils import get_os_type


class YAMLTaskRunner(object):
    def __init__(self, yaml_file, hostname, ip=None, user='root'):
        self.yaml_file = yaml_file
        self.hostname = hostname
        self.ip = ip
        self.user = user
        self.rc = RemoteClient(hostname, ip, user)

    def run_tasks(self, weblog_id=None, async=True):
        yaml_fo = open(self.yaml_file)
        task_map = load(yaml_fo.read(), Loader=Loader)
        try:
            self.rc.startup()
        except ClientNotSetupException as e:
            print e
            return False

        os = get_os_type(self.rc)
        tasks = task_map[os]['tasks']
        for task_id, task in enumerate(tasks):
            if async:
                self._execute_task(task_id, task, weblog_id)
            else:
                self._exceute_task_s(task_id, task, weblog_id)

    def _execute_task(self, task_id, task, log_id=None):
        """

        :param task:  dict containing task {name: name_string, command: ...}
        :return:
        """
        command = task['command']
        cin, cout, cerr = self.rc.run(command)
        print("$ "+command)
        print(cout)
        print(cerr)

    def _exceute_task_s(self, task_id, task, log_id=None):
        command = task['command']
        for out in self.rc.run_s(command):
            print out



if __name__ == '__main__':
    runner = YAMLTaskRunner('install_redis_stunnel.yaml', 'dummy', '45.55.208.192')
    runner.run_tasks(async=False)




