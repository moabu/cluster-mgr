import re
import time
import logging
import json
from flask import flash, has_request_context

from ldap3 import Server, Connection, SUBTREE, BASE, LEVEL, \
    MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE

from clustermgr.models import Server as ServerModel
from clustermgr.core.utils import ldap_encode, get_setup_properties
from ldap.schema import AttributeType, ObjectClass, LDAPSyntax

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


    def getSyntaxes(self):
        self.conn.search(search_base='cn=schema',
                                search_filter='(objectclass=*)',
                                search_scope=BASE, attributes=["ldapSyntaxes"])

        return self.conn.response
    
    def getAttributes(self):
        self.conn.search(search_base='cn=schema',
                                search_filter='(objectclass=*)',
                                search_scope=BASE, attributes=["attributeTypes"])

        return self.conn.response


    def getCustomAttributes(self):
        setup_prop = get_setup_properties()
        inumOrg = setup_prop['inumOrg']
        inumOrgFN = inumOrg.replace('@','').replace('!','').replace('.','')
        x_origin = "X-ORIGIN '{}'".format(inumOrgFN)
        
        atrributes = self.getAttributes()
        ret_list = []
        for ats in atrributes[0]['attributes']['attributeTypes']:
            if x_origin in ats:
                ret_list.append(ats)
        return ret_list

    def getObjectClasses(self):
        self.conn.search(search_base='cn=schema',
                                search_filter='(objectclass=*)',
                                search_scope=BASE, attributes=["objectClasses"])

        return self.conn.response
    
    def getObjectClass(self, object_class_name):
        object_classes = self.getObjectClasses()
        name = "'{}'".format(object_class_name)
        for objcl in object_classes[0]['attributes']['objectClasses']:
            if name in objcl:
                return objcl
    
    def addAtributeToObjectClass(self, object_class_name, attribute_name):
        
        if not type(attribute_name) == type([]):
            attribute_name = [attribute_name]
        
        objcl_s = self.getObjectClass(object_class_name)
        if objcl_s:
            self.conn.modify("cn=schema", {'objectClasses': [MODIFY_DELETE, objcl_s]})
            if not self.conn.result['description']== 'success':
                return False, self.conn.result['description']+'({})'.format(self.conn.result['message'])
        else:
            objcl_s = "( 1.3.6.1.4.1.48710.1.4.200 NAME '{}' SUP top AUXILIARY )".format(object_class_name)
        
        obcl_obj = ObjectClass(objcl_s)
        
        may_list = list(obcl_obj.may)
        
        
        for attribute in attribute_name:
            if not attribute in may_list:
                may_list.append(attribute)
        
        obcl_obj.may = tuple(may_list)
        self.conn.modify("cn=schema", {'objectClasses': [MODIFY_ADD, str(obcl_obj)]})
        if not self.conn.result['description']== 'success':
            return False, self.conn.result['description']

        return True, 'success'
    
    def removeAtributeFromObjectClass(self, object_class_name, attribute_name):
        objcl_s = self.getObjectClass(object_class_name)
        if objcl_s:
            obcl_obj = ObjectClass(objcl_s)
            may_list = list(obcl_obj.may)
            if attribute_name in may_list:
                self.conn.modify("cn=schema", {'objectClasses': [MODIFY_DELETE, objcl_s]})
                if not self.conn.result['description']== 'success':
                    return False, self.conn.result['description']
                may_list.remove(attribute_name)
                obcl_obj.may = tuple(may_list)
                self.conn.modify("cn=schema", {'objectClasses': [MODIFY_ADD, str(obcl_obj)]})
                if not self.conn.result['description']== 'success':
                    return False, self.conn.result['description']
                    
        return True, 'success'
        
    def addAttribute(self, attribute, editing=None, objcls=None):
        
        print "EDITING", editing
        
        name = "'{}'".format(attribute.names[0])
        
        atrributes = self.getAttributes()
        
        for ats in atrributes[0]['attributes']['attributeTypes']:
            if editing:
                if editing in ats:
                    a = AttributeType(str(ats))
                    r = self.removeAtributeFromObjectClass(objcls, a.names[0])
                    if not r:
                        return False, self.conn.result['description']
                    r = self.removeAttribute(editing)
                    if not r[0]:
                        return r
            else:
                if name in ats:
                    return False, 'This attribute name exists'

        r = self.conn.modify("cn=schema", {'attributeTypes': [MODIFY_ADD, attribute]})

        if r:
            return True, ''
        else:
            return False, self.conn.result['description']

    def getAttributebyOID(self, oid):
        atrributes = self.getCustomAttributes()
        for ats in atrributes:
            if oid in ats:
                return ats

    def removeAttribute(self, oid):
        atrribute = self.getAttributebyOID(oid)
        if atrribute:
            r = self.conn.modify("cn=schema", {'attributeTypes': [MODIFY_DELETE, atrribute]})
            if not r:
                return False, self.conn.result['description']
        return True, ''

    def registerObjectClass(self, obcls):

        setup_prop = get_setup_properties()
        inumAppliance = setup_prop['inumAppliance']
        dn='ou=oxtrust,ou=configuration,inum={},ou=appliances,o=gluu'.format(inumAppliance)

        print dn

        r = self.conn.search(dn,
                    search_filter='(objectclass=*)',
                    search_scope=BASE, 
                    attributes=["oxTrustConfApplication"],
                    )

        print r, self.conn.result

        jstr = self.conn.response[0]['attributes']['oxTrustConfApplication'][0]
        jdata = json.loads(jstr)

        change = False

        if not obcls  in jdata["personObjectClassTypes"]:
            jdata["personObjectClassTypes"].append(obcls)
            change = True
        if not obcls in jdata["personObjectClassDisplayNames"]:
            jdata["personObjectClassDisplayNames"].append(obcls)
            change = True
            
        if change:
            print "changing"
            jstr = json.dumps(jdata)
            r = self.conn.modify(dn, {'oxTrustConfApplication': [MODIFY_REPLACE, jstr]})
            if not r:
                return False, self.conn.result['description']
        
        return True, ''

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


