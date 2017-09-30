import os
import unittest

from mock import patch

from clustermgr.core.utils import parse_slapdconf, ldap_encode, generate_random_key


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


if __name__ == "__main__":
    unittest.main()
