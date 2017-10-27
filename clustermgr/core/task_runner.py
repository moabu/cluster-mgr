import yaml
import uuid

from clustermgr.extensions import wlogger
from clustermgr.core.remote import RemoteClient, ClientNotSetupException
from clustermgr.core.utils import get_os_type
from clustermgr.core.constants import *


class YAMLTask(object):
    """Task defining the extracted information from YAML file

    :param name: name of the task
    :param command: the command to be executed in the remote server
    :param expect: string that indicates that task completed successfully
    :param fail: sting that indicates that task failed to complete
    """
    def __init__(self, name=None, command=None, expect=None, fail=None):
        self.id = str(uuid.uuid4())[0:8]
        self.name = name
        self.command = command
        self.expect = expect
        self.fail = fail
        self.output = ""
        self.error = ""
        self.state = None

    @classmethod
    def from_dict(cls, indict):
        """ Create a new YAMLTask object from a dictionary

        :param indict: dictionary containing the init values for the object
        :return: YAMLTask object
        """
        return cls(indict['name'], indict['command'], indict.get('expect'),
                   indict.get('fail'))

    def to_dict(self):
        """
        :return: a dict containing the information about the task
        """
        return dict(id=self.id, action=self.command, output=self.output,
                    error=self.error, state=self.state)

    def execute(self, client, parent_id=None):
        """Executes the command of the task via the supplied client

        :param client: RemoteClient object to run the command
        :param parent_id: the ID to add logs via WebLogger
        :return: None
        """
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
        """Executes the command of the task via the supplied client in a
        synchronous manner. It updates the log in real-time as the command
        executes.

        :param client: :class:`clustermgr.core.remote.RemoteClient` object to
            run the command
        :param parent_id: the ID to add logs via WebLogger
        :return: None
        """
        if not parent_id:
            self.state = RUNNING
            for out in client.run_s(self.command):
                self.output += out
            self.state = COMPLETE

        if parent_id:
            self.state = RUNNING
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
        return '<YAMLTask: {0}>'.format(self.name)


class YAMLTaskRunner(object):
    """Task runner that reads a YAML file containing the tasks and runs
        the commands on the host specified.

    :param yaml_file: location of the file
    :param hostname: hostname of the server where the tasks are to be run
    :param ip: OPTIONAL - IP Address of the server for fallback if
        hostname doesn't resolve
    :param user: OPTIONAL - username for logging into the server; defaults
        to root
    """
    def __init__(self, yaml_file, hostname, ip=None, user='root'):
        self.yaml_file = yaml_file
        self.hostname = hostname
        self.ip = ip
        self.user = user
        self.rc = RemoteClient(hostname, ip, user)
        self.tasks = []

    def run_tasks(self, weblog_id=None, async=False, chdir=None):
        """Runs the tasks in the YAML file

        :param weblog_id: id in which the command's output should be logged to
            the weblogger
        :param async: run the command asynchronously, i.e., each task has to
            complete in the server before the output is available for usage.
            If set *True* it provides real time logging of command's output
        :param chdir: the location of the chroot container if the tasks have
            to be run inside the container
        :return: None
        """
        task_map = yaml.safe_load(open(self.yaml_file).read())
        try:
            self.rc.startup()
        except ClientNotSetupException as e:
            print e
            return False

        os = get_os_type(self.rc)
        self.tasks = [YAMLTask.from_dict(item) for item in
                      task_map[os]['tasks']]

        for task in self.tasks:
            if chdir:
                task.command = 'chroot {0} /bin/bash -c "{1}"'.format(
                    chdir, task.command)
            if async:
                task.execute(self.rc, weblog_id)
            else:
                task.execute_s(self.rc, weblog_id)

    def __repr__(self):
        return "<YAMLTaskRunner based on {0}>".format(self.yaml_file)
