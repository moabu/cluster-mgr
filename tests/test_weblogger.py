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

    def test_log_raw_stores_different_types(self):
        d = dict(name='test', count='10')
        l = ['one', 2, 'three']
        s = "hello"

        self.wlog.log_raw('id', d)
        assert json.loads(self.r.rpush.call_args[0][1])['name'] == 'test'

        self.wlog.log_raw('id2', l)
        self.r.rpush.assert_called_with('weblogger:id2', '["one", 2, "three"]')

        self.wlog.log_raw('id3', s)
        self.r.rpush.assert_called_with('weblogger:id3', '"hello"')

    def test_update_log_replaces_item_as_expected(self):
        items = [json.dumps(dict(id=i, name="item {0}".format(i))) for i in xrange(5)]
        self.r.lrange.return_value = items

        new_item = dict(id=3, name="new item")
        self.wlog.update_log("id", new_item)
        self.r.lset.assert_called_with("weblogger:id", 3, json.dumps(new_item))


if __name__ == "__main__":
    unittest.main()