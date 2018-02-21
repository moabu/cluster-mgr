import sys
import os

sys.path.append("..")
from clustermgr.core.remote import RemoteClient

import json

from ldap3 import Server, Connection, SUBTREE, BASE, LEVEL, \
    MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE

old_host = 'c3.gluu.org'
new_host = 'c2.gluu.org'

def get_appliance_inum():
    conn.search(search_base='ou=appliances,o=gluu',
                search_filter='(objectclass=*)',
                search_scope=SUBTREE, attributes=['inum'])
    
    for r in conn.response:
        if r['attributes']['inum']:
            return r['attributes']['inum'][0]


def get_base_inum():
    conn.search(search_base='o=gluu',
                search_filter='(objectclass=gluuOrganization)',
                search_scope=SUBTREE, attributes=['o'])

    for r in conn.response:
        if r['attributes']['o']:
            return r['attributes']['o'][0]




def change_appliance_config():
    appliance_inum = get_appliance_inum()

    config_dn = 'ou=configuration,inum={},ou=appliances,o=gluu'.format(
                    appliance_inum)


    for dns, cattr in (
                ('oxauth', 'oxAuthConfDynamic'),
                ('oxidp', 'oxConfApplication'),
                ('oxtrust', 'oxTrustConfApplication'),
                ):

        dn = 'ou={},{}'.format(dns, config_dn)

        conn.search(search_base=dn,
                    search_filter='(objectClass=*)',
                    search_scope=BASE, attributes=[cattr])

        config_data = json.loads(conn.response[0]['attributes'][cattr][0])

        for k in config_data:
            kVal = config_data[k]
            if type(kVal) == type(u''):
                if old_host in kVal:
                    kVal=kVal.replace(old_host, new_host)
                    config_data[k]=kVal
                    
        config_data = json.dumps(config_data)
        conn.modify(dn, {cattr: [MODIFY_REPLACE, config_data]})


def change_clients():
    dn = "ou=clients,o={},o=gluu".format(base_inum)
    conn.search(search_base=dn,
                search_filter='(objectClass=oxAuthClient)',
                search_scope=SUBTREE, attributes=[
                                            'oxAuthPostLogoutRedirectURI',
                                            'oxAuthRedirectURI',
                                            'oxClaimRedirectURI',
                                            ])
    
    result = conn.response[0]['attributes']

    dn = conn.response[0]['dn']

    for atr in result:
        for i in range(len(result[atr])):
            changeAttr = False
            if  old_host in result[atr][i]:
                changeAttr = True
                result[atr][i] = result[atr][i].replace(old_host, new_host)
                conn.modify(dn, {atr: [MODIFY_REPLACE, result[atr]]})



def change_uma():


    for ou, cattr in (
                ('resources','oxResource'),
                ('scopes', 'oxId'),
                ):

        dn = "ou={},ou=uma,o={},o=gluu".format(ou,base_inum)

        conn.search(search_base=dn, search_filter='(objectClass=*)', search_scope=SUBTREE, attributes=[cattr])
        result = conn.response 

        for r in result:
            for i in range(len( r['attributes'][cattr])):
                changeAttr = False
                if old_host in r['attributes'][cattr][i]:
                    r['attributes'][cattr][i] = r['attributes'][cattr][i].replace(old_host, new_host)
                    conn.modify(r['dn'], {cattr: [MODIFY_REPLACE, r['attributes'][cattr]]})

class server:
    hostname = 'c2.gluu.org'
    os = 'CentOS 7'
    ip = '159.89.43.71'
    
chane_ldap_entries = False

if chane_ldap_entries:
    server = Server("ldaps://c2.gluu.org:1636", use_ssl=True)
    conn = Connection(server, user="cn=directory manager", password="Gluu1234")
    conn.bind()
    
    base_inum = get_base_inum()
    
    change_uma()
    change_appliance_config()
    change_clients()


class Installer:
    def __init__(self, c, gluu_version, server_os):
        self.c = c
        self.gluu_version = gluu_version
        self.server_os = server_os
        self.container = '/opt/gluu-server-{}'.format(gluu_version)
        
        if ('Ubuntu' in self.server_os) or ('Debian' in self.server_os):
            self.run_command = 'chroot {} /bin/bash -c "{}"'.format(self.container,'{}')
        elif 'CentOS' in self.server_os:
            self.run_command = ('ssh -o IdentityFile=/etc/gluu/keys/gluu-console '
                                '-o Port=60022 -o LogLevel=QUIET -o '
                                'StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
                                '-o PubkeyAuthentication=yes root@localhost \'{}\''
                                )

    def run(self, cmd):
        run_cmd = self.run_command.format(cmd)
        return c.run(run_cmd)
        


gluu_server = '/opt/gluu-server-3.1.2'


c = RemoteClient(server.hostname, ip=server.ip)
c.startup()

def change_httpd_conf():
    if 'CentOS' in server.os:
        httpd_conf = os.path.join(gluu_server, 'etc/httpd/conf/httpd.conf')
        https_gluu = os.path.join(gluu_server, 'etc/httpd/conf.d/https_gluu.conf')

    for conf_file in (httpd_conf, https_gluu):
        result, fileObj = c.get_file(conf_file)
        if result:
            config_text = fileObj.read()
            config_text = config_text.replace(old_host, new_host)
            c.put_file(conf_file, config_text)



installer = Installer(c, '3.1.2', server.os)


def create_httpd_cert():
    cert_city = 'Austin'
    cert_mail = 'mustafa@gluu.org'
    
    cmd_list = [
        '/usr/bin/openssl genrsa -des3 -out /etc/certs/httpd.key.orig -passout pass:secret 2048',
        '/usr/bin/openssl rsa -in /etc/certs/httpd.key.orig -passin pass:secret -out /etc/certs/httpd.key',
        '/usr/bin/openssl req -new -key /etc/certs/httpd.key -out /etc/certs/httpd.csr -subj '
        '"/C=US/ST=TX/L={}/O=Gluu/CN={}/emailAddress={}"'.format(cert_city, server.hostname, cert_mail),
        '/usr/bin/openssl x509 -req -days 365 -in /etc/certs/httpd.csr -signkey /etc/certs/httpd.key -out /etc/certs/httpd.crt',
        'chown root:root /etc/certs/httpd.key.orig',
        'chmod 700 /etc/certs/httpd.key.orig',
        'chown root:root /etc/certs/httpd.key',
        'chmod 700 /etc/certs/httpd.key',
        ]


    for cmd in cmd_list:
        print "Executing", cmd
        print installer.run(cmd)

create_httpd_cert()
