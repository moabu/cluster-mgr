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

    def test_change_cache_loads_cache_clustering_form(self):
        rv = self.client.get('/cache/change/')
        self.assertIn('Cache Clustering', rv.data)
        self.assertIn('form', rv.data)

    def test_change_rejects_post_if_method_or_list_of_servers_is_missing(self):
        # both method and servers are missing
        rv = self.client.post('/cache/change/', follow_redirects=True)
        # self.assertIn('No clustering method', rv.data)
        self.assertIn('No servers have been selected', rv.data)

        # only method is missing
        # rv = self.client.post('/cache/change/', data=dict(servers=[1,2,3]),
        #                       follow_redirects=True)
        # self.assertIn('No clustering method', rv.data)

        # only servers are missing
        rv = self.client.post('/cache/change/', data=dict(method='CLUSTER'),
                              follow_redirects=True)
        self.assertIn('No servers have been selected', rv.data)

    @patch('clustermgr.views.cache.install_cache_components')
    def test_change_calls_celery_task_if_form_data_is_correct(self, mocktask):
        self.client.post('/cache/change/', data=dict(
            method="CLUSTER", servers=[1,2,3]))
        mocktask.delay.assert_called_once_with([1,2,3])

