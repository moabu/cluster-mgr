import unittest
import json

from mock import patch

from clustermgr.application import create_app
from clustermgr.extensions import db, wlogger
from clustermgr.models import Server, AppConfiguration

class IndexViewTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.from_object('clustermgr.config.TestingConfig')
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.drop_all()

    def test_empty_db_returns_intro_page(self):
        rv = self.client.get('/')
        self.assertIn('Replication Manager', rv.data)
        self.assertIn('Add Server', rv.data)

    def test_db_with_data_loads_dashboard(self):
        s1 = Server()
        s1.hostname = 'test.example.com'
        s1.gluu_server = True
        s1.ip = '0.0.0.0'
        with self.app.app_context():
            db.session.add(s1)
            db.session.commit()

        rv = self.client.get('/')
        self.assertIn('Dashboard', rv.data)
        self.assertIn('test.example.com', rv.data)

    def _add_app_config(self, url=None):
        if not url:
            url = '/configuration/'
        return self.client.post(url, data=dict(
            gluu_version='3.1.0',
            replication_dn='rep manager',
            replication_pw='secret',
            replication_pw_confirm='secret',
            nginx_host='nginx.example.com',
            use_ip=False,
            update=True,
        ), follow_redirects=True)

    def test_app_configuration_saves_form_submitted_data(self):
        with self.app.app_context():
            a = AppConfiguration.query.all()
            self.assertEqual(len(a), 0)
        rv = self._add_app_config()
        with self.app.app_context():
            a = AppConfiguration.query.all()
            self.assertEqual(len(a), 1)

    def test_app_configuration_redirect_to_next_page_after_saving_data(self):
        rv = self._add_app_config('/configuration/?next=/')
        self.assertIn('Add Server', rv.data)

    def test_app_configuration_returns_with_set_value(self):
        a = AppConfiguration()
        a.gluu_version = '3.1.0'
        a.replication_dn = 'replication manager'
        a.nginx_host = 'nginx.example.com'
        with self.app.app_context():
            db.session.add(a)
            db.session.commit()

        rv = self.client.get('/configuration/')
        self.assertIn('replication manager', rv.data)
        self.assertIn('nginx.example.com', rv.data)

    @patch('clustermgr.views.index.wlogger')
    @patch('clustermgr.views.index.AsyncResult')
    def test_get_log_returns_the_messages_as_json(self, mockresult, mocklogger):
        instance = mockresult.return_value
        instance.state = 'PENDING'
        mocklogger.get_messages.return_value = [{'level': 'info', 'msg': 'Message 1'},
                                                {'level': 'debug', 'msg': 'Message 2'}]
        rv = self.client.get('/log/dummy-id')
        self.assertIn("Message 1", rv.data)
        self.assertIn("Message 2", rv.data)

    @patch('clustermgr.views.index.wlogger')
    @patch('clustermgr.views.index.AsyncResult')
    def test_get_log_cleans_messages_when_task_completes(self, mockresult, mocklogger):
        instance = mockresult.return_value
        instance.state = 'SUCCESS'
        instance.result = 5
        mocklogger.get_messages.return_value = [{'level': 'info', 'msg': 'message 1'}]
        self.client.get('/log/test-id')
        mocklogger.clean.assert_called_once()


    @patch('clustermgr.views.index.wlogger')
    @patch('clustermgr.views.index.AsyncResult')
    def test_get_log_returns_the_task_result_when_task_ends(self, mockresult, mocklogger):
        instance = mockresult.return_value
        instance.state = 'PENDING'
        mocklogger.get_messages.return_value = [{'level': 'info', 'msg': 'message 1'}]
        rv = self.client.get('/log/test-id')
        assert json.loads(rv.data)['result'] == 0

        instance.state = 'SUCCESS'
        instance.result = 'TASK RESULT'
        mocklogger.get_messages.return_value = [{'level': 'info', 'msg': 'message 1'}]
        rv = self.client.get('/log/test-id')
        self.assertEqual(json.loads(rv.data)['result'], 'TASK RESULT')


if __name__ == '__main__':
    unittest.main()
