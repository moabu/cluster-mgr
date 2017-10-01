import unittest

from mock import patch

from clustermgr.core.ldap_functions import LdapOLC, MODIFY_ADD, MODIFY_DELETE


class LdapOlcTestCase(unittest.TestCase):
    def setUp(self):
        with patch('clustermgr.core.ldap_functions.Connection') as mockconn:
            self.conn = mockconn.return_value
            self.mgr = LdapOLC("0.0.0.0", "cn=config", "secret")
            self.mgr.connect()

    def tearDown(self):
        pass

    def test_add_provider_performs_a_modify_add(self):
        self.mgr.add_provider(1, 'server.example.com', 'cn=rep,o-gluu', 'pass')
        self.mgr.conn.modify.assert_called_once()
        call_args = self.mgr.conn.modify.call_args[0]
        self.assertIn('olcSyncRepl', call_args[1])
        self.assertEqual(MODIFY_ADD, call_args[1]['olcSyncRepl'][0][0])

    def test_add_provider_replaces_syncrepl_conf_if_id_already_exists(self):
        self.mgr.conn.entries = [{"olcSyncRepl": ["rid=1 replicate"]}]
        self.mgr.add_provider(1, 'server.example.com', 'cn=rep,o-gluu', 'pass')
        self.mgr.conn.search.assert_called_once()
        # modify should be called twice, once with delete and another with add
        assert self.mgr.conn.modify.call_count == 2


if __name__ == '__main__':
    unittest.main()
