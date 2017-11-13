import unittest
import json

from mock import patch

from clustermgr.application import create_app
from clustermgr.extensions import db, wlogger
from clustermgr.models import Server, AppConfiguration


class ServerViewTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.from_object('clustermgr.config.TestingConfig')
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            appconf = AppConfiguration()
            appconf.gluu_version = '3.1.1'
            db.session.add(appconf)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.drop_all()

    def test_index_returns_cluster_management_page_on_get(self):
        rv = self.client.get('/cache/')
        self.assertIn('Cache Management', rv.data)

    @patch('clustermgr.views.cache.get_cache_methods')
    def test_refresh_mthods_runs_celery_task(self, mocktask):
        mocktask.delay.return_value.id = 'taskid'

        rv = self.client.get('/cache/refresh_methods')
        mocktask.delay.assert_called_once()
        self.assertEqual(json.loads(rv.data)['task_id'], 'taskid')

    @patch('clustermgr.views.cache.install_cache_components')
    def test_change_calls_celery_task_if_form_data_is_correct(self, mocktask):
        self.client.post('/cache/change/', data=dict(
            method="CLUSTER"))
        mocktask.delay.assert_called_once_with()

