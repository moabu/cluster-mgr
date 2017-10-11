import os
import unittest

from mock import patch

from clustermgr.core.utils import parse_slapdconf, ldap_encode, \
    generate_random_key, split_redis_cluster_slots


class SlapdConfParseTest(unittest.TestCase):
    def test_parser(self):
        current_dir = os.path.dirname(os.path.realpath(__file__))
        conf = os.path.join(current_dir, "data", "slapd.conf")
        values = parse_slapdconf(conf)
        self.assertEquals(values["openldapSchemaFolder"],
                          "/opt/gluu/schema/openldap")
        self.assertEquals(values["openldapTLSCACert"],
                          "/etc/certs/openldap.pem")
        self.assertEquals(values["openldapTLSCert"],
                          "/etc/certs/openldap.crt")
        self.assertEquals(values["openldapTLSKey"],
                          "/etc/certs/openldap.key")
        self.assertEquals(values["encoded_ldap_pw"],
                          "{SSHA}NtdgEfn/RjKonrJcvi2Qqn4qrk8ccedb")
        self.assertEquals(values["BCRYPT"], "{BCRYPT}")


class LDAPEncodeTestCase(unittest.TestCase):
    def test_ldap_encode(self):
        assert "{SSHA}" in ldap_encode('A Password')

    @patch('clustermgr.core.utils.os.urandom')
    def test_ldap_encode_uses_a_random_salt(self, mockur):
        mockur.return_value = 'asdf'
        ldap_encode('password')
        mockur.assert_called_once_with(4)


class GenerateRandomKeyTestCase(unittest.TestCase):
    def test_gen_rand_key_returns_random_string_of_requested_length(self):
        key = generate_random_key(10)
        assert len(key) == 10

    def test_gen_rand_key_returns_a_default_length_of_32(self):
        assert len(generate_random_key()) == 32

    @patch('clustermgr.core.utils.os.urandom')
    def test_gen_rand_key_uses_os_urandom(self, mockur):
        mockur.return_value = 'asdf'
        generate_random_key(10)
        mockur.assert_called_once_with(10)


class SplitRedisSlotsTestCase(unittest.TestCase):
    def test_expected(self):
        ranges = split_redis_cluster_slots(1)
        self.assertEqual(ranges, [(0, 16383)])
        ranges = split_redis_cluster_slots(2)
        self.assertEqual(ranges, [(0, 8191), (8192, 16383)])
        ranges = split_redis_cluster_slots(3)
        self.assertEqual(ranges, [(0, 5460), (5461, 10921), (10922, 16383)])
        ranges = split_redis_cluster_slots(4)
        self.assertEqual(ranges, [(0, 4095), (4096, 8191), (8192, 12287),
                                  (12288, 16383)])
        ranges = split_redis_cluster_slots(5)
        self.assertEqual(ranges, [(0, 3275), (3276, 6551), (6552, 9827),
                                  (9828, 13103), (13104, 16383)])



if __name__ == "__main__":
    unittest.main()
