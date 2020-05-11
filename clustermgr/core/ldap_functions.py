import re
import time
import logging
import json
from flask import flash, has_request_context

from ldap3 import Server, Connection, SUBTREE, BASE, LEVEL, \
    MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE

from clustermgr.models import Server as ServerModel
from clustermgr.core.utils import ldap_encode, get_setup_properties

from clustermgr.core.clustermgr_logging import sys_logger as logger

def get_host_port(addr):
    m = re.search('(?:ldap.*://)?(?P<host>[^:/ ]+).?(?P<port>[0-9]*).*',  addr)
    return m.group('host'), m.group('port')


def get_hostname_by_ip(ipaddr):
    ldp = ServerModel.query.filter_by(ip=ipaddr).first()
    if ldp:
        return ldp.hostname


def get_ip_by_hostname(hostname):
    ldp = ServerModel.query.filter_by(hostname=hostname).first()
    if ldp:
        return ldp.ip


class LdapOLC(object):
    """A wrapper class to operate on the o=gluu DIT of the LDAP.

    Args:
        hostname (string): hostname of the server running the LDAP server
        addr (string): uri of ldap server, such as ldaps://ldp.foo.org:1636
        binddn (string): bind dn for ldap server
        password (string): the password of binddn
    """
    def __init__(self, addr, binddn, passwd):
        self.addr = addr
        self.binddn = binddn
        self.passwd = passwd
        self.server = None
        self.conn = None
        self.hostname = get_host_port(addr)[0]

    def connect(self):
        """Makes connection to ldap server and returns result
        
        Returns:
            the ldap connection result
        """
        logger.debug("Making Ldap Connection to " + self.addr)
        self.server = Server(self.addr, use_ssl=True)
        self.conn = Connection(
            self.server, user=self.binddn, password=self.passwd)
        return self.conn.bind()

    def close(self):
        """Closes ldap connection"""
        self.conn.unbind()

    def delDn(self, dn):
        """Deltes given dn
        
        Args:
            dn (string): dn to be deleted
            
        Returns:
            ldap delete result
        """

        return self.conn.delete(dn)


    def checkBaseDN(self, dn='o=gluu', attributes={'objectClass': ['top', 'organization'],'o': 'gluu'}):
        """Checks if base dn exists. If not creates

        Returns:
            ldap add result
        """
        if not self.conn.search(search_base=dn, search_filter='(objectClass=top)', search_scope=BASE):
            logger.info("Adding base DN: " + dn)
            self.conn.add(dn, attributes=attributes)
            return True

    def configureOxIDPAuthentication(self, servers):
        """Makes gluu server aware of all ldap servers in the cluster

        Args:
            servers (list): list of server to add oxIDPAuthentication

        Returns:
            ldap modify result
        """

        if self.conn.search(
                        search_base="ou=configuration,o=gluu", 
                        search_scope=BASE,
                        search_filter='(objectclass=*)',
                        attributes=["oxIDPAuthentication"]):

            r = self.conn.response
            if r:
                oxidp_s = r[0]["attributes"]["oxIDPAuthentication"][0]
                oxidp = json.loads(oxidp_s)
                oxidp["config"]["servers"] = servers
                oxidp_s = json.dumps(oxidp)

                return self.conn.modify(
                            r[0]['dn'], 
                            {"oxIDPAuthentication": [MODIFY_REPLACE, oxidp_s]}
                            )

    def changeOxCacheConfiguration(self, method, server_string=None, redis_password=None):
        result=self.conn.search(
                        search_base="ou=configuration,o=gluu",
                        search_scope=BASE,
                        search_filter='(objectclass=*)',
                        attributes=["oxCacheConfiguration"]
                        )
        if result:
            oxCacheConfiguration = json.loads(self.conn.response[0]['attributes']['oxCacheConfiguration'][0])
            oxCacheConfiguration['cacheProviderType'] = method
            if server_string:
                oxCacheConfiguration['redisConfiguration']['servers'] = server_string

            oxCacheConfiguration['redisConfiguration']['decryptedPassword'] = redis_password

            oxCacheConfiguration_js = json.dumps(oxCacheConfiguration, indent=2)
            dn = self.conn.response[0]['dn']
            
            return self.conn.modify(dn, {'oxCacheConfiguration': [MODIFY_REPLACE, oxCacheConfiguration_js]})



    def get_appliance_attributes(self, *args):
        """Returns the value of the attribute under the gluuAppliance entry

        Args:
            *args: the names of attributes whose value is required as string

        Returns:
            the ldap entry
        """
        self.conn.search(search_base="o=gluu",
                         search_filter='(objectclass=gluuAppliance)',
                         search_scope=SUBTREE, attributes=list(args))
        return self.conn.entries[0]

    def set_applicance_attribute(self, attribute, value):
        """Sets value to an attribute in the gluuApplicane entry

        Args:
            attribute (string): the name of the attribute
            value (list): the values of the attribute in list form
        """
        entry = self.get_appliance_attributes(attribute)
        dn = entry.entry_dn
        mod = {attribute: [(MODIFY_REPLACE, value)]}

        return self.conn.modify(dn, mod)

    def set_ldap_cache_cleanup_interval(self, interval=-1):

        result=self.conn.search(
                        search_base="ou=oxauth,ou=configuration,o=gluu",
                        search_scope=BASE,
                        search_filter='(objectclass=*)',
                        attributes=["oxAuthConfDynamic"]
                        )
        
        
        oxAuthConfDynamic = json.loads(self.conn.response[0]['attributes']['oxAuthConfDynamic'][0])

        oxAuthConfDynamic['cleanServiceInterval'] = interval
        oxAuthConfDynamic_json = json.dumps(oxAuthConfDynamic, indent=2)

        return self.conn.modify(
                            self.conn.response[0]['dn'], 
                            {"oxAuthConfDynamic": [MODIFY_REPLACE, oxAuthConfDynamic_json]}
                            )
    
    def __del__(self):
        self.close()


def getLdapConn(addr, dn, passwd):
    """this function gets address, dn and password for ldap server, makes
    connection and return LdapOLC object."""

    ldp = LdapOLC('ldaps://{}:1636'.format(addr), dn, passwd)
    r = None
    try:
        r = ldp.connect()
    except Exception as e:
        logger.error("Unable to connect LDAP server %s:", str(e))
        if has_request_context():
            flash("Connection to LDAPserver {0} at port 1636 failed: {1}".format(
                addr, e), "danger")
        return

    return ldp

class DBManager:
    "dummy class, remove after refactoring"


