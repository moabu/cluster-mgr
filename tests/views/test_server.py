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

    def tearDown(self):
        with self.app.app_context():
            db.drop_all()

    def _add_app_config(self):
        a = AppConfiguration()
        a.replication_dn = 'rep manager'
        a.replication_pw = 'secret'
        with self.app.app_context():
            db.session.add(a)
            db.session.commit()

    def test_index_redirects_to_app_config_page_when_not_configured(self):
        rv = self.client.get('/server/')
        self.assertEqual(rv.status_code, 302)

        self._add_app_config()
        rv = self.client.get('/server/')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('New Server', rv.data)

    def test_index_shows_new_server_page(self):
        with self.app.app_context():
            a = AppConfiguration.query.first()
        if not a:
            self._add_app_config()
        rv = self.client.get('/server/')
        self.assertIn('New Server', rv.data)
        self.assertIn('form', rv.data)

    @patch('clustermgr.views.server.collect_server_details')
    def _add_server(self, mocktask):
        self._add_app_config()
        return self.client.post('/server/', data=dict(
            hostname="server.example.com",
            ip="1.1.1.1",
            ldap_password="secret",
            ldap_password_confirm="secret",
            gluu_server="y",
            primary_server=None,
        ), follow_redirects=True)

    @patch('clustermgr.views.server.collect_server_details')
    def test_index_creates_new_server_on_post(self, mocktask):
        with self.app.app_context():
            self.assertEqual(len(Server.get_all()), 0)
        rv = self._add_server()
        with self.app.app_context():
            self.assertEqual(len(Server.get_all()), 1)

    @patch('clustermgr.views.server.collect_server_details')
    def test_index_calls_collect_server_details_task_on_post(self, mocktask):
        self._add_app_config()
        self.client.post('/server/', data=dict(
            hostname="server.example.com",
            ip="1.1.1.1",
            ldap_password="secret",
            ldap_password_confirm="secret",
            gluu_server="y",
            primary_server=None,
        ), follow_redirects=True)
        mocktask.delay.assert_called_once_with(1)

    @patch('clustermgr.views.server.collect_server_details')
    def test_edit_redirects_for_non_existant_server_id(self, mocktask):
        rv = self.client.get('/server/edit/999/')
        assert rv.status_code == 302

    @patch('clustermgr.views.server.collect_server_details')
    def test_edit_loads_the_page_with_existing_details_on_get(self, mocktask):
        self._add_server()
        rv = self.client.get('/server/edit/1/')
        self.assertIn('server.example.com', rv.data)
        self.assertIn('1.1.1.1', rv.data)

    @patch('clustermgr.views.server.collect_server_details')
    def test_edit_updates_the_server_details_on_post(self, mocktask):
        self._add_server()
        self.client.post('/server/edit/1/', data=dict(
            hostname="hostname.example.com",
            ip="2.2.2.2",
            gluu_server=None,
            primary_server="y"
        ), follow_redirects=True)
        with self.app.app_context():
            s = Server.query.first()
            self.assertEqual(s.hostname, "hostname.example.com")
            self.assertEqual(s.ip, "2.2.2.2")
            self.assertTrue(s.primary_server)
            self.assertFalse(s.gluu_server)

    @patch('clustermgr.views.server.collect_server_details')
    def test_edit_changes_ldap_password_when_supplied(self, mocktask):
        self._add_server()
        self.client.post('/server/edit/1/', data=dict(
            hostname="hostname.example.com",
            ip="2.2.2.2",
            gluu_server=None,
            primary_server="y",
            ldap_password="changed",
            ldap_password_confirm="changed",
        ), follow_redirects=True)

        with self.app.app_context():
            s = Server.query.first()
            self.assertEqual(s.ldap_password, "changed")

    @patch('clustermgr.views.server.collect_server_details')
    def test_edit_preserves_password_when_empty(self, mocktask):
        self._add_server()
        self.client.post('/server/edit/1/', data=dict(
            hostname="hostname.example.com",
            ip="2.2.2.2",
            gluu_server=None,
            ldap_password="",
            ldap_password_confirm="",
            primary_server="y"
        ), follow_redirects=True)

        with self.app.app_context():
            s = Server.query.first()
            self.assertEqual(s.ldap_password, "secret")

    @patch('clustermgr.views.server.remove_provider')
    def test_remove_deletes_the_server(self, mocktask):
        self._add_server()
        with self.app.app_context():
            self.assertEqual(len(Server.get_all()), 1)

        rv = self.client.get("/server/remove/1/")
        self.assertEqual(rv.status_code, 302)  # redirects to home
        with self.app.app_context():
            self.assertEqual(len(Server.get_all()), 0)

    @patch('clustermgr.views.server.remove_provider')
    def test_remove_calls_the_cleanup_tasks(self, mocktask):
        self._add_server()
        with self.app.app_context():
            s = Server.query.first()
            s.mmr = True    # LDAP cleanup called if MMR flag is true
            db.session.commit()
        self.client.get("/server/remove/1/")
        mocktask.delay.assert_called_once_with(1)


if __name__ == '__main__':
    unittest.main()
