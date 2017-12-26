import unittest
import json

from mock import patch, MagicMock

from clustermgr.weblogger import WebLogger


class WebLoggerTestCase(unittest.TestCase):
    def setUp(self):
        with  patch('clustermgr.weblogger.redis.Redis') as mockredis:
            self.r = mockredis.return_value
            self.wlog = WebLogger()

    def test_log_adds_messages_in_info_level_by_default(self):
        self.wlog.log('id1', 'message 1')
        assert json.loads(self.r.rpush.call_args[0][1])['level'] == 'info'

    def test_log_adds_messages_with_supplied_level(self):
        self.wlog.log('id1', 'message', 'debug')
        assert self.r.rpush.call_args[0][0] == 'weblogger:id1'
        assert json.loads(self.r.rpush.call_args[0][1])['level'] == 'debug'
        assert json.loads(self.r.rpush.call_args[0][1])['msg'] == 'message'

        self.wlog.log('id2', 'message 2', 'warning')
        assert self.r.rpush.call_args[0][0] == 'weblogger:id2'
        assert json.loads(self.r.rpush.call_args[0][1])['level'] == 'warning'

        self.wlog.log('id3', 'message 3', 'danger')
        assert self.r.rpush.call_args[0][0] == 'weblogger:id3'
        assert json.loads(self.r.rpush.call_args[0][1])['level'] == 'danger'

    def test_log_adds_extra_keyword_args_to_entry(self):
        self.wlog.log('id', 'message', 'info', name="test", run=1)
        assert json.loads(self.r.rpush.call_args[0][1])['name'] == 'test'
        assert json.loads(self.r.rpush.call_args[0][1])['run'] == 1

    def test_get_message_returns_empty_list_for_no_messages(self):
        self.r.lrange.return_value = None
        assert self.wlog.get_messages('non existent id') == []

    def test_get_message_returns_list_of_messages(self):
        message = [json.dumps(dict(level="info", msg="test message"))]
        self.r.lrange.return_value = message
        assert len(self.wlog.get_messages('test id')) == 1
        assert self.wlog.get_messages('test id') == [dict(level="info", msg="test message")]

    def test_clean_deletes_all_messages(self):
        self.wlog.clean('test-id')
        self.r.delete.assert_called_with('weblogger:test-id')

    def test_set_meta(self):
        self.wlog.set_meta('dummy_id', total_tasks=10)
        assert self.r.set.call_args[0][0] == 'weblogger:dummy_id:meta:total_tasks'


if __name__ == "__main__":
    unittest.main()