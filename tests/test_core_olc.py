"""This is not strictly a unittest. This uses a live ldapserver to test
and hence destroys the ethos of 'don't communicate over network in uniitest'.

But this was necessary for the development of clustermgr/core/olc.py

Mocking might be done on a later stage when the core foundataion seems solid.
"""
from clustermgr.core.olc import CnManager
from ldap3 import BASE, MODIFY_DELETE

import unittest


class CnManagerTest(unittest.TestCase):
    def setUp(self):
        ip = ''
        port = 389
        ssl = False
        user = ''
        password = ''
        self.repl_template = 'rid={0} provider=ldap://dummy_host:389 bindmethod=simple binddn="cn=directory manager,o=gluu" credentials=password searchbase="o=gluu" schemachecking=on type=refreshAndPersist retry="60 +" logbase="cn=accesslog" logfilter="(&(objectclass=audirWriteObject)(reqResult=0))" syncdata=accesslog'  # noqa

        self.mgr = CnManager(ip, port, ssl, user, password)

    def tearDown(self):
        mod = {'olcSyncrepl': [(MODIFY_DELETE, [])]}
        self.mgr.conn.modify(self.mgr.gluu_db_dn, mod)
        self.mgr.close()

    def test_add_1_syncrepl_entry(self):
        repl = self.repl_template.format(1)
        status = self.mgr.add_olcsyncrepl(repl)
        if not status:
            print self.mgr.recent_result()
        self.assertTrue(status)

        self.mgr.conn.search(self.mgr.gluu_db_dn, '(objectclass=*)',
                             search_scope=BASE, attributes=['olcSyncRepl'])
        self.assertEqual(len(self.mgr.conn.entries[0].olcSyncRepl), 1)

    def test_add_multiple_syncrepl_entry(self):
        repls = [self.repl_template.format(i) for i in range(5)]
        for repl in repls:
            self.assertTrue(self.mgr.add_olcsyncrepl(repl))

        self.mgr.conn.search(self.mgr.gluu_db_dn, '(objectclass=*)',
                             search_scope=BASE, attributes=['olcSyncRepl'])
        self.assertEqual(len(self.mgr.conn.entries[0].olcSyncRepl), 5)

    def test_remove_particular_synrepl_entry(self):
        repls = [self.repl_template.format(i) for i in range(5)]
        for repl in repls:
            self.assertTrue(self.mgr.add_olcsyncrepl(repl))
        # Remove one server
        self.assertTrue(self.mgr.remove_olcsyncrepl(3))

        self.mgr.conn.search(self.mgr.gluu_db_dn, '(objectclass=*)',
                             search_scope=BASE, attributes=['olcSyncRepl'])
        self.assertEqual(len(self.mgr.conn.entries[0].olcSyncRepl), 4)
        # Remove another server
        self.assertTrue(self.mgr.remove_olcsyncrepl(2))
        self.mgr.conn.search(self.mgr.gluu_db_dn, '(objectclass=*)',
                             search_scope=BASE, attributes=['olcSyncRepl'])
        self.assertEqual(len(self.mgr.conn.entries[0].olcSyncRepl), 3)



if __name__ == '__main__':
    unittest.main()
