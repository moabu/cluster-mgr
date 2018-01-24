import re
import os
import hashlib
import string
import random
import shlex
import subprocess
import uuid

from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

from clustermgr.config import Config

from clustermgr.core.remote import RemoteClient
from clustermgr.models import Server, AppConfiguration


DEFAULT_CHARSET = string.ascii_uppercase + string.digits + string.lowercase


def parse_slapdconf(old_conf=None):
    """Parses the slapd.conf file generated during the installation of
    Gluu server and gets the values necessary for the provider.conf.

    Args:
        old_conf (string) - OPTIONAL Location of the slapd.conf file.
            Defatuls to /opt/symas/etc/openldap/slapd.conf

    Returns:
        dict containing the values for the following
            * openldapSchemaFolder
            * openldapTLSCACert
            * openldapTLSCert
            * openldapTLSKey
            * encoded_ldap_pw
            * BCRYPT - This has {} around it, so an escape value `{BCRYPT}`
    """
    if not old_conf:
        old_conf = '/opt/symas/etc/openldap/slapd.conf'

    f = open(old_conf, 'r')
    values = {}

    for line in f:
        # openldapSchemaFolder
        if 'gluu.schema' in line and re.match('^include*', line):
            path = line.split("\"")[1].replace("/gluu.schema", "")
            values["openldapSchemaFolder"] = path
        # openldapTLSCACert
        if re.match("^TLSCACertificateFile*", line):
            values["openldapTLSCACert"] = line.split("\"")[1]
        # openldapTLSCert
        if re.match("^TLSCertificateFile*", line):
            values["openldapTLSCert"] = line.split("\"")[1]
        # openldapTLSKey
        if re.match("^TLSCertificateKeyFile*", line):
            values["openldapTLSKey"] = line.split("\"")[1]
        # encoded_ldap_pw
        if re.match("^rootpw", line):
            values["encoded_ldap_pw"] = line.split()[1]
    f.close()

    # BCRYPT - This has {} around it so escape this
    values["BCRYPT"] = "{BCRYPT}"

    return values


def ldap_encode(password):
    salt = os.urandom(4)
    sha = hashlib.sha1(password)
    sha.update(salt)
    b64encoded = '{0}{1}'.format(sha.digest(), salt).encode('base64').strip()
    encrypted_password = '{{SSHA}}{0}'.format(b64encoded)
    return encrypted_password


def generate_random_key(length=32):
    """Generates random key.
    """
    return os.urandom(length)


def generate_random_iv(length=8):
    """Generates random initialization vector.
    """
    return os.urandom(length)


def encrypt_text(text, key, iv):
    """Encrypts plain text using Blowfish and CBC.

    Example::

        import os
        # keep the same key and iv for decrypting the text
        key = os.urandom(32)
        iv = os.urandom(8)
        enc_text = encrypt_text("secret-text", key, iv)
    """
    cipher = Cipher(algorithms.Blowfish(key), modes.CBC(iv),
                    backend=default_backend())
    encryptor = cipher.encryptor()

    # CBC requires padding
    padder = padding.PKCS7(algorithms.Blowfish.block_size).padder()
    padded_data = padder.update(text) + padder.finalize()

    # encrypt the text
    encrypted_text = encryptor.update(padded_data) + encryptor.finalize()
    return encrypted_text


def decrypt_text(encrypted_text, key, iv):
    """Decrypts encrypted text using Blowfish and CBC.

    Example::

        # use the same key and iv used in encrypting the text
        text = decrypt_text(enc_text, key, iv)
    """
    cipher = Cipher(algorithms.Blowfish(key), modes.CBC(iv),
                    backend=default_backend())
    decryptor = cipher.decryptor()

    # CBC requires padding
    unpadder = padding.PKCS7(algorithms.Blowfish.block_size).unpadder()
    padded_data = decryptor.update(encrypted_text) + decryptor.finalize()

    # decrypt the encrypted text
    text = unpadder.update(padded_data) + unpadder.finalize()
    return text


def random_chars(size=12, chars=DEFAULT_CHARSET):
    """Returns a string of random alpha-numeric characters.

    Args:
        size (int, optional): the length of the string. Defaults to 12
        chars (string, optional): a selection of characters to pick the random
            ones for the return string

    Returns:
        a string of random characters
    """
    return ''.join(random.choice(chars) for _ in range(size))


def split_redis_cluster_slots(nodes):
    """splits the available 16384 slots in a redis cluster between the given
     number of nodes

    :param nodes: a integer count of the number of nodes
    :return: list of tuples containing the slot range in the form (start, end)
    """
    parts = 16384 / nodes
    allotted = -1
    ranges = []
    for i in xrange(nodes):
        if i == nodes-1:
            ranges.append((allotted+1, 16383))
        else:
            ranges.append((allotted+1, allotted+parts))
        allotted += parts
    return ranges


def exec_cmd(cmd):
    """Executes shell command.

    :param cmd: String of shell command.
    :returns: A tuple consists of stdout, stderr, and return code
              returned from shell command execution.
    """
    args = shlex.split(cmd)
    popen = subprocess.Popen(args,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    stdout, stderr = popen.communicate()
    retcode = popen.returncode
    return stdout, stderr, retcode


def get_mac_addr():
    """Gets MAC address according to standard IEEE EUI-48 format.

    :returns: A string of uppercased MAC address.
    """
    mac_num = hex(uuid.getnode()).replace("0x", "").upper()
    return "-".join(mac_num[i:i + 2] for i in range(0, 11, 2))



def get_quad():
    return str(uuid.uuid4())[:4].upper()


def get_inums():
    """This fuction created inums based on Python's uuid4 function.
    Barrowed from setup.py of gluu installer"""

    base_inum = '@!%s.%s.%s.%s' % tuple([get_quad() for _ in xrange(4)])
    org_two_quads = '%s.%s' % tuple([get_quad() for _ in xrange(2)])
    inum_org = '%s!0001!%s' % (base_inum, org_two_quads)
    appliance_two_quads = '%s.%s' % tuple([get_quad() for _ in xrange(2)])
    inum_appliance = '%s!0002!%s' % (base_inum, appliance_two_quads)
    return inum_org, inum_appliance

def parse_setup_properties(content):
    setup_prop = dict()
    for l in content:
        ls = l.strip()
        if not ls[0] == '#':
            eq_loc = ls.find('=')

            if eq_loc > 0:
                k = ls[:eq_loc]
                v = ls[eq_loc+1:]
                if v == 'True':
                    v = True
                elif v == 'False':
                    v = False
                setup_prop[k] = v

    return setup_prop

def write_setup_properties_file(setup_prop):

    setup_properties_file = os.path.join(Config.DATA_DIR,
                                         'setup.properties')

    with open(setup_properties_file, 'w') as f:
        for k, v in setup_prop.items():
            f.write('{0}={1}\n'.format(k, v))

def get_setup_properties():
    """This fucntion returns properties for setup.properties file."""

    #We are goint to deal with these properties with cluster-mgr
    setup_prop = {
        'hostname': '',
        'orgName': '',
        'countryCode': '',
        'city': '',
        'state': '',
        'jksPass': '',
        'inumOrg': '',
        'inumAppliance': '',
        'admin_email': '',
        'ip': '',
        'installOxAuth':True,
        'installOxTrust':True,
        'installLDAP':True,
        'installHTTPD':True,
        'installJce':True,
        'installSaml':False,
        'installAsimba':False,
        #'installCas':False,
        'installOxAuthRP':False,
        'installPassport':False,
        'ldap_type': 'opendj',
        }

    #Check if there exists a previously created setup.properties file.
    #If exists, modify properties with content of this file.
    setup_properties_file = os.path.join(Config.DATA_DIR, 'setup.properties')

    if os.path.exists(setup_properties_file):
        setup_prop_f = parse_setup_properties(
                                open(setup_properties_file).readlines())

        setup_prop.update(setup_prop_f)

    #Every time this function is called, create new inum
    inum_org, inum_appliance = get_inums()
    setup_prop['inumOrg'] = inum_org
    setup_prop['inumAppliance'] = inum_appliance

    return setup_prop

def get_opendj_replication_status():
    primary_server = Server.query.filter_by(primary_server=True).first()
    app_config = AppConfiguration.query.first()
    
    c = RemoteClient(primary_server.hostname, ip=primary_server.ip)
    chroot = '/opt/gluu-server-' + app_config.gluu_version
    
    cmd_run = '{}'

    if (primary_server.os == 'CentOS 7') or (primary_server.os == 'RHEL 7'):
        chroot = None
        cmd_run = ('ssh -o IdentityFile=/etc/gluu/keys/gluu-console '
                '-o Port=60022 -o LogLevel=QUIET '
                '-o StrictHostKeyChecking=no '
                '-o UserKnownHostsFile=/dev/null '
                '-o PubkeyAuthentication=yes root@localhost "{}"')
    else:
        cmd_run ='chroot %s /bin/bash -c "{}"' % (chroot)

    try:
        c.startup()
    except Exception as e:
        return False, "Cannot establish SSH connection {0}".format(e)


    cmd = ('/opt/opendj/bin/dsreplication status -n -X -h {} '
            '-p 1444 -I admin -w {}').format(
                    primary_server.hostname, 
                    app_config.replication_pw)

    
    cmd = cmd_run.format(cmd)
        
    si,so,se = c.run(cmd)
    
    return True, so
    
