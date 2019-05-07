import re
import os
import hashlib
import string
import random
import shlex
import subprocess
import uuid
import base64

from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

from clustermgr.config import Config

from clustermgr.core.remote import RemoteClient
from clustermgr.models import Server, AppConfiguration, CacheServer
from clustermgr.extensions import wlogger
from flask import current_app as app


import logging
import traceback
from logging.handlers import RotatingFileHandler


DEFAULT_CHARSET = string.ascii_uppercase + string.digits + string.lowercase



handler = RotatingFileHandler(Config.LOG_FILE, maxBytes= 5*1024*1024, backupCount=3)
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)
logger.addHandler(handler)


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
        if ls:
            if not ls[0] == '#':
                eq_loc = ls.find('=')

                if eq_loc > 0:
                    k = ls[:eq_loc]
                    v = ls[eq_loc+1:]
                    v=v.replace('\\=','=')
                    v=v.replace("\\'","'")
                    v=v.replace('\\"','"')
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

def get_setup_properties(createNew=False):
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
        'installOxAuthRP':False,
        'installPassport':False,
        'ldap_type': 'opendj',
        'application_max_ram': 3072,
        }

    #Check if there exists a previously created setup.properties file.
    #If exists, modify properties with content of this file.
    setup_properties_file = os.path.join(Config.DATA_DIR, 'setup.properties')

    if os.path.exists(setup_properties_file):
        setup_prop_f = parse_setup_properties(
                                open(setup_properties_file).readlines())

        setup_prop.update(setup_prop_f)

    if createNew:
        #Every time this function is called, create new inum
        inum_org, inum_appliance = get_inums()
        setup_prop['inumOrg'] = inum_org
        setup_prop['inumAppliance'] = inum_appliance

    return setup_prop

def get_opendj_replication_status():
    
    """Retreives opendj replication status form primary server

    :returns: A string that shows replication status
    """
    
    primary_server = Server.query.filter_by(primary_server=True).first()
    app_config = AppConfiguration.query.first()

    #Make ssh connection to primary server
    c = RemoteClient(primary_server.hostname, ip=primary_server.ip)
    chroot = '/opt/gluu-server-' + app_config.gluu_version

    cmd_run = '{}'

    #determine execution environment for differetn OS types
    if primary_server.os in ('CentOS 7', 'RHEL 7', 'Ubuntu 18'):
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

    #This command queries server for replication status
    cmd = ('OPENDJ_JAVA_HOME=/opt/jre /opt/opendj/bin/dsreplication status -n -X -h {} '
            '-p 4444 -I admin -w $\'{}\'').format(
                    primary_server.ip,
                    app_config.replication_pw.replace("'","\\'"))

    print "executing", cmd
    cmd = cmd_run.format(cmd)

    si,so,se = c.run(cmd)

    return True, so


def as_boolean(val, default=False):
    truthy = set(('t', 'T', 'true', 'True', 'TRUE', '1', 1, True))
    falsy = set(('f', 'F', 'false', 'False', 'FALSE', '0', 0, False))

    if val in truthy:
        return True
    if val in falsy:
        return False
    return default

def modify_etc_hosts(host_ip, old_hosts):

    hosts = {
            'ipv4':{'127.0.0.1':['localhost']},
            'ipv6':{'::1':['ip6-localhost', 'ip6-loopback']},
            }

    for l in old_hosts:
        ls=l.strip()
        if ls:
            if not ls[0]=='#':
                if ls[0]==':':
                    h_type='ipv6'
                else:
                    h_type='ipv4'

                lss = ls.split()
                ip_addr = lss[0]
                if not ip_addr in hosts[h_type]:
                    hosts[h_type][ip_addr]=[]
                for h in lss[1:]:
                    if not h in hosts[h_type][ip_addr]:
                        hosts[h_type][ip_addr].append(h)

    for h,i in host_ip:
        if h in hosts['ipv4']['127.0.0.1']:
            hosts['ipv4']['127.0.0.1'].remove(h)

    for h,i in host_ip:
        if h in hosts['ipv6']['::1']:
            hosts['ipv6']['::1'].remove(h)
            
    for h,i in host_ip:
        if i in hosts['ipv4']:
            if not h in hosts['ipv4'][i]:
                hosts['ipv4'][i].append(h)
        else:
            hosts['ipv4'][i] = [h]

    hostse = ''

    for iptype in hosts:
        for ipaddr in hosts[iptype]:
            host_list = [ipaddr] + hosts[iptype][ipaddr]
            hl =  "\t".join(host_list)
            hostse += hl +'\n'

    return hostse


def encode(key, clear):
    enc = []
    for i in range(len(clear)):
        key_c = key[i % len(key)]
        enc_c = chr((ord(clear[i]) + ord(key_c)) % 256)
        enc.append(enc_c)
    return base64.urlsafe_b64encode("".join(enc))

def decode(key, enc):
    dec = []
    enc = base64.urlsafe_b64decode(enc)
    for i in range(len(enc)):
        key_c = key[i % len(key)]
        dec_c = chr((256 + ord(enc[i]) - ord(key_c)) % 256)
        dec.append(dec_c)
    return "".join(dec)


def run_and_log(c, cmd, tid, sid):
    
    """Shorthand for FakeRemote.run(). This function automatically logs
    the commands output to be shared in the web frontend.

    Args:
        c (:object:`FakeRemote`): class to be used to run cammand
        cmd (string): the command to be run on local server
        tid (string): task id of the task to store the log
        sid (integer): id of the server

    Returns:
        the output of the command or the err thrown by the command as a string
    """
    
    wlogger.log(tid, "Running {}".format(cmd))

    result = c.run(cmd)
    
    if result[2].strip():
        if "Redirecting to /bin/systemctl" in result[2]:
            wlogger.log(tid,result[2].strip(), "debug", server_id=sid)
        else:
            wlogger.log(tid, "An error occurrued while executing "
                    "{}: {}".format(cmd, result[2]),
                    "error", server_id=sid)
    
    else:
        wlogger.log(tid, "Command was run successfully: {}".format(cmd),
                        "success", server_id=sid)
                                

    return result

def get_redis_config(f):
    addr_list = []

    for l in f:
        ls=l.strip()
        if ls:
            if ls.startswith('connect'):
                n = ls.find('=')
                addr_port = ls[n+1:].strip()
                addr_port_s = addr_port.split(':')
                addr_list.append(addr_port_s[0])

    return addr_list

def make_proxy_stunnel_conf(exception=None):

    tmp_conf = [
        'cert = /etc/stunnel/cert.pem',
        'pid = /var/run/stunnel.pid',
        'output = /var/log/stunnel4/stunnel.log',
        ]

    servers = Server.query.all()
    app_config = AppConfiguration.query.first()
    
    if app_config.external_load_balancer:
        cache_ip = app_config.cache_ip
    else:
        cache_ip = app_config.nginx_ip
    
    
    for server in servers:
        if (server.id != exception) and server.redis:
            tmp_conf += [
                            '[redis{}]'.format(server.id),
                            'client = yes',
                            'accept = 127.0.0.1:700{}'.format(server.id),
                            'connect = {}:7777'.format(server.ip),
                        ]

    tmp_conf += [
                    '[twemproxy]',
                    'client = no',
                    'accept = {}:8888'.format(cache_ip),
                    'connect = 127.0.0.1:2222',
                ]
    
    return tmp_conf
    
def make_twem_proxy_conf(exception=None):
    
    twemproxy_conf_tmp_file = os.path.join(
                                    app.root_path,
                                    'templates',
                                    'stunnel',
                                    'nutcracker.yml'
                                )

    twemproxy_conf = open(twemproxy_conf_tmp_file).read()

    servers = Server.query.all()

    for server in servers:
        if (server.id != exception) and server.redis:
            twemproxy_conf += '   - 127.0.0.1:{0}:1\n'.format(7000+server.id)
    
    
    return twemproxy_conf
    
def make_nginx_proxy_conf(exception=None):
    servers = Server.query.all()
    app_config = AppConfiguration.query.first()
    nginx_backends = []

    server_list = []

    #read local nginx.conf template
    nginx_tmp_file = os.path.join(app.root_path, "templates", "nginx",
                           "nginx.temp")
    nginx_tmp = open(nginx_tmp_file).read()

    #add all gluu servers to nginx.conf
    for s in servers:
        if s.id != exception:
            nginx_backends.append('  server {0}:443 max_fails=2 fail_timeout=10s;'.format(s.hostname))
            server_list.append(s.hostname)
        
    nginx_tmp = nginx_tmp.replace('{#NGINX#}', app_config.nginx_host)
    nginx_tmp = nginx_tmp.replace('{#SERVERS#}', '\n'.join(nginx_backends))
    nginx_tmp = nginx_tmp.replace('{#PINGSTRING#}', ' '.join(server_list))

    return nginx_tmp


def get_cache_servers():
    
    cache_servers = CacheServer.query.all()


    return cache_servers
