from paramiko.client import SSHClient, AutoAddPolicy
import StringIO


class ClientNotSetupException(Exception):
    """Exception raised when the client is not initialized because
    of connection failures."""
    pass


class RemoteClient(object):
    """Remote Client is a wrapper over SSHClient with utility functions.

    Args:
        host (string): The hostname of the server to connect. It can be an IP
            address of the server also.
        user (string, optional): The user to connect to the remote server. It
            defaults to root

    Attributes:
        host (string): The hostname passed in as a the argument
        user (string): The user to connect as to the remote server
        client (:class:`paramiko.client.SSHClient`): The SSHClient object used
            for all the communications with the remote server.
        sftpclient (:class:`paramiko.sftp_client.SFTPClient`): The SFTP object
            for all the file transfer operations over the SSH.
    """

    def __init__(self, host, user='root'):
        self.host = host
        self.user = user
        self.client = SSHClient()
        self.sftpclient = None
        self.client.set_missing_host_key_policy(AutoAddPolicy())
        self.client.load_system_host_keys()

    def startup(self):
        """Function that starts SSH connection and makes client available for
        carrying out the functions.
        """
        self.client.connect(self.host, port=22, username=self.user)
        self.sftpclient = self.client.open_sftp()

    def download(self, remote, local):
        """Downloads a file from remote server to the local system.

        Args:
            remote (string): location of the file in remote server
            local (string): path where the file should be saved
        """
        if not self.sftpclient:
            raise ClientNotSetupException(
                'Cannot download file. Client not initialized')

        try:
            self.sftpclient.get(remote, local)
        except OSError:
            return "Error: Local file %s doesn't exist." % local
        except IOError:
            return "Error: Remote location %s doesn't exist." % remote
        finally:
            return "Download successful. File at: {0}".format(local)

    def upload(self, local, remote):
        """Uploads the file from local location to remote server.

        Args:
            local (string): path of the local file to upload
            remote (string): location on remote server to put the file
        """
        if not self.sftpclient:
            raise ClientNotSetupException(
                'Cannot upload file. Client not initialized')

        try:
            self.sftpclient.put(local, remote)
        except OSError:
            return "Error: Local file %s doesn't exist." % local
        except IOError:
            return "Error: Remote location %s doesn't exist." % remote
        finally:
            return "Upload successful. File at: {0}".format(remote)

    def exists(self, filepath):
        """Returns whether a file exists or not in the remote server.

        Args:
            filepath (string): path to the file to check for existance

        Returns:
            True if it exists, False if it doesn't
        """
        if not self.client:
            raise ClientNotSetupException(
                'Cannot run procedure. Client not initialized')
        cin, cout, cerr = self.client.exec_command('stat {0}'.format(filepath))
        if len(cout.read()) > 5:
            return True
        elif len(cerr.read()) > 5:
            return False

    def run(self, command):
        """Run a command in the remote server.

        Args:
            command (string): the command to be run on the remote server

        Returns:
            tuple of three strings containing text from stdin, stdout an stderr
        """
        if not self.client:
            raise ClientNotSetupException(
                'Cannot run procedure. Client not initialized')

        buffers = self.client.exec_command(command)
        output = []
        for buf in buffers:
            try:
                output.append(buf.read())
            except IOError:
                output.append('')

        return tuple(output)

    # MB
    def putFile(self,  filename, filecontent):
        """Puts content to a file on remote server

        Args:
            filename (string): name of file to be written on remote server
            filecontent (string): content of file

        Returns:
            tuple: True/False, file size / error

        """
        #renameFile(server, filename, filename+'.%d' % time.time())

        # write content to IO File
        f = StringIO.StringIO()
        f.write(filecontent)
        f.seek(0)

        try:
            r = self.sftpclient.putfo(f, filename)
            return True, r.st_size
        except Exception as err:
            return False, err

    def mkDir(self,  dirname):
        try:
            self.sftpclient.mkdir(dirname)
            return True, dirname
        except Exception as err:
            return False, err

    """

    def chownFile(server, chroot, filenme, user, group):
        cmd = "chroot {} chown {}.{} {}".format(chroot, user, group, filenme)
        print cmd
        server['ssh'].exec_command(cmd)

    def chmodFile(server, filenme, mode):
        server['sftp'].chmod(filenme, mode)

    def mkDir(server, dirname):
        try:
            server['sftp'].mkdir(dirname)
        except:
            pass

    def renameFile(server, filenme, newfilename):
        try:
            server['sftp'].rename(filenme, newfilename)
        except:
            pass


"""

    def close(self):
        """Close the SSH Connection
        """
        self.client.close()
