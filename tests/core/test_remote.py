import unittest

from mock import patch, MagicMock
from paramiko import SSHException

from clustermgr.core.remote import RemoteClient, ClientNotSetupException


class RemoteClientTestCase(unittest.TestCase):
    def setUp(self):
        with patch("clustermgr.core.remote.SSHClient") as mock_client:
            self.sshclient = mock_client.return_value
            # self.sshclient.open_sftp.return_value = MagicMock(name="sftp")
            self.rc = RemoteClient('server')
            self.rc.startup()

    @patch('clustermgr.core.remote.SSHClient')
    def test_starup_falls_back_to_ip(self, mock_client):
        instance = mock_client.return_value
        instance.connect = MagicMock(side_effect=[SSHException, None])
        RemoteClient('server', ip='0.0.0.0').startup()
        instance.connect.assert_called_with('0.0.0.0', port=22, username='root')

    def test_download_calls_sftpclient_get(self):
        rv = self.rc.download('remote', 'local')
        self.rc.sftpclient.get.assert_called_with('remote', 'local')
        assert "successful" in rv

    def test_download_returns_errors_when_get_throws_errors(self):
        self.rc.sftpclient.get.side_effect = OSError
        rv = self.rc.download('remote', 'local_1')
        self.assertIn('Error: Local', rv)

        self.rc.sftpclient.get.side_effect = IOError
        rv = self.rc.download('remote', 'local_2')
        self.assertIn('Error: Remote', rv)

    def test_upload_calls_sftpclient_put(self):
        rv = self.rc.upload('local', 'remote')
        self.rc.sftpclient.put.assert_called_with('local', 'remote')
        assert "successful" in rv

    def test_upload_returns_errors_when_put_throws_errors(self):
        self.rc.sftpclient.put.side_effect = IOError
        rv = self.rc.upload('local', 'remote')
        self.assertIn('Error: Remote', rv)

        self.rc.sftpclient.put.side_effect = OSError
        rv = self.rc.upload('local_2', 'remote_2')
        self.assertIn('Error: Local', rv)

    def test_upload_and_download_throws_error_if_sftpclient_is_none(self):
        self.rc.sftpclient = None
        with self.assertRaises(ClientNotSetupException):
            self.rc.upload('s', 't')
        with self.assertRaises(ClientNotSetupException):
            self.rc.download('s', 't')

    def test_exists_and_run_throws_error_if_client_is_none(self):
        self.rc.client = None
        with self.assertRaises(ClientNotSetupException):
            self.rc.exists('s')
        with self.assertRaises(ClientNotSetupException):
            self.rc.run('s')


if __name__ == '__main__':
    unittest.main()
