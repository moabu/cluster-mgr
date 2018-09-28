import re
import time
import logging
import json

from ldap3 import Server, Connection, SUBTREE, BASE, LEVEL, \
    MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE

from clustermgr.models import Server as ServerModel
from clustermgr.core.utils import ldap_encode, get_setup_properties
from ldap.schema import AttributeType, ObjectClass, LDAPSyntax


logger = logging.getLogger(__name__)


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
        logger.debug("Making Ldap Connection")
        self.server = Server(self.addr, use_ssl=True)
        self.conn = Connection(
            self.server, user=self.binddn, password=self.passwd)
        return self.conn.bind()

    def close(self):
        """Closes ldap connection"""
        self.conn.unbind()

    def loadModules(self, *modules):
        """This function creates ldap entry on server for loading nodules.
        
        Args:
            modules (list): list of modules to be loaded 
        
        Returns:
            -1 if modulas were already loaded, else returns modify result
        """
        
        #Get loaded modules
        self.conn.search(search_base='cn=module{0},cn=config',
                         search_filter='(objectClass=*)', search_scope=BASE,
                         attributes=["olcModuleLoad"])

        #addList are modules that will be loaded
        addList = list(modules)

        if self.conn.response:
            
            #if a module is allread loaded, remove it from addList
            for a in self.conn.response[0]['attributes']['olcModuleLoad']:
                r = re.split("{\d+}", a)
                if len(r) == 1:
                    m = r[0]
                else:
                    m = r[1]
                mn = m.split('.')
                if mn[0] in addList:
                    addList.remove(mn[0])

        #If there is still modules to be loaded, add them and return
        #modify results
        if addList:

            return self.conn.modify('cn=module{0},cn=config',
                                    {'olcModuleLoad': [MODIFY_ADD, addList]})

        #If all modules were loaded previously, return -1
        return -1

    def checkAccesslogDBEntry(self):
        """Checks if access logdb (cn=accesslog) entry exists
        
        Returns:
            search results of cn=accesslog
        """
        
        return self.conn.search(search_base='cn=config',
                                search_filter='(olcSuffix=cn=accesslog)',
                                search_scope=SUBTREE, attributes=["*"])

    def accesslogDBEntry(self, replicator_dn, 
                            log_dir="/opt/gluu/data/accesslog"):
        """This function creates ldap entry on server for accesslog database.
        
        Args:
            replicator_dn (string): replicator dn for replication
            log_dir (string, optional): accesslog database directorsy,
                    default to /opt/gluu/data/accesslog
        
        Returns:
            None if accesslogdb entry is already exists else ldap modifcation 
            result for adding accsesslogdb entry.
        """

        attributes = {'objectClass':  ['olcDatabaseConfig', 'olcMdbConfig'],
                      'olcDatabase': '{2}mdb',
                      'olcDbDirectory': log_dir,
                      'OlcDbMaxSize': 1073741824,
                      'olcSuffix': 'cn=accesslog',
                      'olcRootDN': 'cn=admin, cn=accesslog',
                      'olcRootPW': ldap_encode(self.passwd),
                      'olcDbIndex': ['default eq', 'objectClass,entryCSN,entryUUID,reqEnd,reqResult,reqStart,reqDN'],
                      'olcLimits': 'dn.exact="{0}" time.soft=unlimited time.hard=unlimited size.soft=unlimited size.hard=unlimited'.format(replicator_dn),

                      }
        #check if accesslogdb entry is allread exists. If not exists, create it.
        if not self.checkAccesslogDBEntry():
            return self.conn.add('olcDatabase={2}mdb,cn=config',
                                 attributes=attributes)

    def checkSyncprovOverlaysDB1(self):
        """Checks if overlay configuration entry exists on first database
        
        Returns:
            search results of olcOverlay=syncprov
        """
        return self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                                search_filter='(olcOverlay=syncprov)',
                                search_scope=SUBTREE, attributes=["*"])

    def syncprovOverlaysDB1(self):
        """This function creates overlay configuration on first database

        Returns:
            None if overlay configuration entry is already exists 
            else ldap modifcation result for adding overlay configuration entry.
        """
        attributes = {'objectClass':  ['olcOverlayConfig',
                                       'olcSyncProvConfig'],
                      'olcOverlay': 'syncprov',
                      'olcSpReloadHint': 'TRUE',
                      'olcSpCheckPoint': '100 10',
                      'olcSpSessionlog': '10000',
                      }
        #If not overlay configuration on first database is not exists, crtate it
        if not self.checkSyncprovOverlaysDB1():
            self.conn.add(
                'olcOverlay=syncprov,olcDatabase={1}mdb,cn=config',
                attributes=attributes)
            if self.conn.result['description'] == 'success':
                return True

    def checkSyncprovOverlaysDB2(self):
        """Checks if overlay configuration entry exists on second database
        
        Returns:
            search results of olcOverlay=syncprov
        """
        return self.conn.search(search_base='olcDatabase={2}mdb,cn=config',
                                search_filter='(olcOverlay=syncprov)',
                                search_scope=SUBTREE, attributes=["*"])

    def syncprovOverlaysDB2(self):
        """This function creates overlay configuration on second database

        Returns:
            None if overlay configuration entry is already exists 
            else ldap modifcation result for adding overlay configuration entry.
        """
        attributes = {
            'objectClass':  ['olcOverlayConfig', 'olcSyncProvConfig'],
            'olcOverlay': 'syncprov',
            'olcSpNoPresent': 'TRUE',
            'olcSpReloadHint': 'TRUE',
            }
        #If not overlay configuration on second database 
        #is not exists, crtate it
        if not self.checkSyncprovOverlaysDB2():
            self.conn.add(
                'olcOverlay=syncprov,olcDatabase={2}mdb,cn=config',
                attributes=attributes)

            if self.conn.result['description'] == 'success':
                return True

    def checkServerID(self):
        """Checks if Server ID entry exists
        
        Returns:
            search results of olcServerID
        """
        return self.conn.search(search_base='cn=config',
                                search_filter='(objectClass=*)',
                                search_scope=BASE, attributes=["olcServerID"])

    def setServerID(self, sid):
        """This function sets Server ID for replication
        
        Args:
            sid (int): Server ID for this server

        Returns:
            ldap modifcation result for setting server id entry.
        """
        
        #modification type is add
        mod_type = MODIFY_ADD
        
        #check if server id exists.
        self.conn.search(search_base='cn=config',
                         search_filter='(objectClass=*)',
                         search_scope=BASE, attributes=["olcServerID"])

        #If server id exists, modfication type id replace
        if self.checkServerID():
            if self.conn.response[0]['attributes']['olcServerID']:
                mod_type = MODIFY_REPLACE

        return self.conn.modify('cn=config',
                                {'olcServerID': [mod_type, str(sid)]})

    def setDBIndexes(self):
        """This function sets indexes for accesslog database
        
        Returns:
            ldap modifcation result for setting indexes for accesslog.
        """
        
        #check if indexes exist
        self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                         search_filter='(objectClass=*)', search_scope=BASE,
                         attributes=["olcDbIndex"])
        addList = ["entryCSN eq", "entryUUID eq"]

        #remove index that is already exist
        if self.conn.response:
            for idx in self.conn.response[0]['attributes']['olcDbIndex']:
                if idx in addList:
                    addList.remove(idx)

        return self.conn.modify('olcDatabase={1}mdb,cn=config',
                                {'olcDbIndex': [MODIFY_ADD, addList]})

    def checkAccesslogPurge(self):
        """This function checks if accesslog purge entry exists
        
        Returns:
            search result of objectClass=olcAccessLogConfig
        """
        return self.conn.search(
            search_base='cn=config',
            search_filter='(objectClass=olcAccessLogConfig)',
            search_scope=SUBTREE, attributes=["olcAccessLogPurge"])

    def accesslogPurge(self, purge='0:24:0 1:0:0'):
        """This function creates purge interval and age for accessogdb entries
        
        Args:
            purge (string, optional): interval and age representation separeted
                by a space in the form: "D+H:M:S" 
                where D: day, H: hour, M: min, S:sec

        Returns:
            ldap modifcation result for setting accesslog purge entry.
        """
        
        #split data to interval and age.
        p,a = purge.split()
        pl = p.split(':')
        al = a.split(':')

        olcAccessLogPurge = ''

        #all entries except day, should be double in length
        if not pl[0]=='0':
            olcAccessLogPurge += pl[0].zfill(2)+'+'
        olcAccessLogPurge += "{}:{}".format(pl[1].zfill(2),pl[2].zfill(2)) + ' '
        
        if not al[0]=='0':
            olcAccessLogPurge += al[0].zfill(2)+'+'
        olcAccessLogPurge += "{}:{}".format(al[1].zfill(2),al[2].zfill(2))

        attributes = {
                'objectClass':  ['olcOverlayConfig', 'olcAccessLogConfig'],
                'olcOverlay': 'accesslog',
                'olcAccessLogDB': 'cn=accesslog',
                'olcAccessLogOps': 'writes',
                'olcAccessLogSuccess': 'TRUE',
                'olcAccessLogPurge': olcAccessLogPurge,
            }
            
        if not self.checkAccesslogPurge():
            return self.conn.add(
                'olcOverlay=accesslog,olcDatabase={1}mdb,cn=config',
                attributes=attributes
            )

    def removeMirrorMode(self):
        """This function removes mirror mode entry

        Returns:
            None if server is not in mirror mode else ldap modification result
        """
        self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                         search_filter='(objectClass=*)', search_scope=BASE,
                         attributes=["olcMirrorMode"])

        if not self.conn.response:
            return

        if self.conn.response[0]['attributes']['olcMirrorMode']:
            return self.conn.modify('olcDatabase={1}mdb,cn=config',
                                    {"olcMirrorMode": [MODIFY_REPLACE, []]})

    def checkMirroMode(self):
        """This function checks if server is in mirror mode

        Returns:
            False if server is not in mirror mode else search result of 
            olcMirrorMode
            
        """
        r = self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                             search_filter='(objectClass=*)',
                             search_scope=BASE, attributes=["olcMirrorMode"])
        if r:
            if self.conn.response[0]['attributes']:
                if self.conn.response[0]['attributes']['olcMirrorMode']:
                    return self.conn.response[0]['attributes']['olcMirrorMode']

        return False

    def makeMirroMode(self):
        """This function makse server in mirror mode

        Returns:
            ldap modification result
        """
        return self.conn.modify('olcDatabase={1}mdb,cn=config',
                                {"olcMirrorMode": [MODIFY_ADD, ["TRUE"]]})

    def removeProvider(self, raddr):
        """This function removes provider form server
        
        Args:
            raddr (string): provider uri, for example: ldaps://ldp.foo.org:1636

        Returns:
            -1 if this server has no such provider else 
            ldap modifcation result for removing provider
        """
        
        rmMirrorMode = False

        if len(self.getProviders()) <= 1:
            rmMirrorMode = True

        #if there is no such privder return -1
        if not self.conn.response:
            return -1

        #iterate all attributes to find basedn of olcSyncrepl
        for pr in self.conn.response:
            if pr["attributes"]["olcSyncrepl"]:
                for pri in pr["attributes"]["olcSyncrepl"]:
                    for l in pri.split():
                        ls = l.split('=')
                        if ls[0] == 'provider':
                            if ls[1] == raddr:
                                baseDn = pr['dn']
                                r = self.conn.modify(
                                    baseDn,
                                    {'olcSyncrepl': [MODIFY_DELETE, [pri]]})
                                if r:
                                    if rmMirrorMode:
                                        self.removeMirrorMode()
                                return r

    def add_provider(self, rid, raddr, rbinddn, rcredentials):
        """Adds provider to server for replication.

        Args:
            rid (int): provider server id
            raddr (string): provider uri, for example: ldaps://ldp.foo.org:1636
            rbindn (string): bind dn of replicator user
            rcredentials (string): password for replicator user (rbinddn)

        Returns:
            modification result of adding provider
        """

        #this is rpvider information
        ridText = ('rid={0} provider={1} bindmethod=simple binddn="{2}" '
                   'tls_reqcert=never credentials={3} searchbase="o=gluu" '
                   'logbase="cn=accesslog" '
                   #'filter=(&(objectClass=*)(!(ou:dn:=appliances))) '
                   'logfilter="(&(objectClass=auditWriteObject)(reqResult=0))" '
                   'schemachecking=on type=refreshAndPersist retry="60 +" '
                   'syncdata=accesslog sizeLimit=unlimited '
                   'timelimit=unlimited'.format(
                        rid, raddr, rbinddn, rcredentials)
                    )

        #we should delete if such an entry exists, so search it
        self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                         search_filter='(objectClass=*)',
                         search_scope=BASE, attributes=["olcSyncRepl"])

        # delete the entry if a syncrepl config exists for the same rid
        entry = self.conn.entries[0]
        for rep in entry["olcSyncRepl"]:
            if 'rid={0}'.format(rid) in rep:
                lmod = {"olcSyncRepl": [(MODIFY_DELETE, [rep])]}
                self.conn.modify('olcDatabase={1}mdb,cn=config', lmod)
                break

        mod = {"olcSyncRepl": [(MODIFY_ADD, [ridText])]}
        
        return self.conn.modify('olcDatabase={1}mdb,cn=config', mod)

    def checkAccesslogDB(self):
        """Checks if access logdb (cn=accesslog) entry exists
        
        Returns:
            search results of cn=accesslog
        """
        
        return self.conn.search(search_base='cn=config',
                                search_filter='(olcSuffix=cn=accesslog)',
                                search_scope=SUBTREE, attributes=["*"])

    def addTestUser(self,  cn, sn, mail):
        """Adds test user
        
        Args:
            cn (string): common name for test user
            sn (string): last name for test user
            mail (string): mail address for test user
            
        Returns:
            ldap add result
        """


        #get base dn
        self.checkBaseDN()
        
        #check if base for tests user exists 'ou=testusers,o=gluu'
        self.checkTestUserBase()
        
        #create a uid
        uid = '{0}@{1}'.format(time.time(), self.hostname)
        
        #make dn for test user
        dn = "uid={0},ou=testusers,o=gluu".format(uid)
        
        return self.conn.add(dn,
                             attributes={
                                 'objectClass': ['top', 'inetOrgPerson'],
                                 "cn": cn,
                                 'mail': mail,
                                 'sn': sn,
                                 'title': 'gluuClusterMgrTestUser',
                                 'uid': uid
                             }
                             )

    def checkTestUserBase(self):
        """Checks if test user base (ou=testusers,o=gluu) exists. If not exists
            creates it
            
        Returns:
            None if not base dn exists else returns ldap add result
            ldap add result
        """
        
        if not self.conn.search(search_base='ou=testusers,o=gluu',
                                search_filter='(objectClass=inetOrgPerson)',
                                search_scope=BASE,
                                attributes='*'
                                ):
            self.conn.add('ou=testusers,o=gluu',
                          attributes={
                              'objectClass': ['top', 'organizationalUnit'],
                              'ou': 'testusers',
                          }
                          )


    def searchTestUsers(self):
        """Searches test user
            
        Returns:
            ldap search result for test users
        """
        return self.conn.search(search_base='ou=testusers,o=gluu',
                                search_filter='(title=gluuClusterMgrTestUser)',
                                search_scope=LEVEL,
                                attributes='*'
                                )

    def delDn(self, dn):
        """Deltes given dn
        
        Args:
            dn (string): dn to be deleted
            
        Returns:
            ldap delete result
        """

        return self.conn.delete(dn)

    def getProviders(self):
        """Collects providers for this server

        Returns:
            provider dictionary.
        """

        pDict = {}
        
        #Search provider entries
        if self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                            search_filter='(objectClass=*)',
                            search_scope=BASE, attributes=["olcSyncRepl"]):
            
            #Iterate all providers and parse it
            for pe in self.conn.response[0]['attributes']['olcSyncrepl']:
                for e in pe.split():
                    es = e.split("=")
                    if re.search('(\{\d*\})*rid',  es[0]):
                        pid = es[1]
                    elif es[0] == 'provider':
                        host, port = get_host_port(es[1])
                        dkey = host
                        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", host):
                            dkey = get_hostname_by_ip(host)

                pDict[dkey] = (pid, port, host)

        return pDict

    def getMMRStatus(self):
        """Returns multi master replication status for this server

        Returns:
            dictionary includes replicator results
        """
        
        retDict = {}
        retDict["server_id"] = None
        if self.checkServerID():
            if self.conn.response[0]['attributes']['olcServerID']:
                retDict["server_id"] = self.conn.response[0]['attributes']['olcServerID'][0]

        retDict["overlaysDB1"] = self.checkSyncprovOverlaysDB1()
        retDict["overlaysDB2"] = self.checkSyncprovOverlaysDB2()
        retDict["mirrorMode"] = self.checkMirroMode()
        retDict["accesslogDB"] = self.checkAccesslogDBEntry()
        retDict["accesslogPurge"] = self.checkAccesslogPurge()
        retDict["providers"] = self.getProviders()

        return retDict

    def getMainDbDN(self):
        """Returns dn of main db 

        Returns:
            dn of main db
        """
        
        
        if self.conn.search(search_base="cn=config", search_scope=LEVEL,
                            search_filter="(olcDbDirectory=/opt/gluu/data/main_db)",
                            attributes='*'):
            if self.conn.response:
                return self.conn.response[0]['dn']

    def setLimitOnMainDb(self, replicator_dn):
        """Sets limit for replicator dn
        
        Args:
            replicator_dn (string): dn for replicator user

        Returns:
            ldap modification result
        """

        main_db_dn = self.getMainDbDN()
        return self.conn.modify(main_db_dn, {'olcLimits': [MODIFY_ADD, 'dn.exact="{0}" time.soft=unlimited time.hard=unlimited size.soft=unlimited size.hard=unlimited'.format(replicator_dn)]})

    def addReplicatorUser(self, replicator_dn, passwd):
        """Adds replicator user (dn)
        
        Args:
            replicator_dn (string): dn for replicator user
            passwd (string): password of replicator user

        Returns:
            ldap add/modification result
        """


        #Ckech if base dn exists
        self.checkBaseDN()

        #get encoded password
        enc_passwd = ldap_encode(passwd)
        
        #check if replicator user exists
        self.conn.search(replicator_dn, search_filter='(objectClass=*)',
                         search_scope=BASE)

        if len(self.conn.response):  # user dn already exists
            return self.conn.modify(
                replicator_dn, {"userPassword": [MODIFY_REPLACE, enc_passwd]})
        else:
            m = re.search('cn=(?P<cn>[a-zA-Z][a-zA-Z ]*[a-zA-Z]),o=gluu',
                          replicator_dn)
            cn = m.group('cn')
            attributes = {'objectClass': ['top', 'inetOrgPerson'],
                          'cn': cn,
                          'sn': 'replicator',
                          'uid': 'replicator',
                          'userpassword': enc_passwd,
                          }
            return self.conn.add(replicator_dn, attributes=attributes)

    def checkBaseDN(self):
        """Checks id base dn exists. If not creates

        Returns:
            ldap add result
        """
        r = self.conn.search(search_base="o=gluu", search_filter='(objectClass=top)', search_scope=BASE)
        if not self.conn.search(search_base="o=gluu", search_filter='(objectClass=top)', search_scope=BASE):
            logger.info("Adding base DN")
            self.conn.add('o=gluu', attributes={
                'objectClass': ['organization'],
                'o': 'gluu',
            }
            )

    def configureOxIDPAuthentication(self, servers):
        """Makes gluu server aware of all ldap servers in the cluster

        Args:
            servers (list): list of server to add oxIDPAuthentication

        Returns:
            ldap modify result
        """
        
        if self.conn.search("ou=appliances,o=gluu", 
                        search_filter='(objectClass=gluuAppliance)',
                        search_scope=LEVEL, 
                        attributes=["oxIDPAuthentication"]):
            r = self.conn.response
            if r:
                oxidp_s = r[0]["attributes"]["oxIDPAuthentication"][0]
                oxidp = json.loads(oxidp_s)
                config=json.loads(oxidp["config"])
                config["servers"] = servers
                oxidp["config"] = json.dumps(config)
                oxidp_s = json.dumps(oxidp)
                return self.conn.modify(
                                r[0]['dn'], {"oxIDPAuthentication": [MODIFY_REPLACE, oxidp_s]})
                                
    def changeOxCacheConfiguration(self, method):

        result=self.conn.search(search_base='o=gluu',
                         search_filter='(oxCacheConfiguration=*)', search_scope=SUBTREE,
                         attributes=["oxCacheConfiguration"])
        if result:
            oxCacheConfiguration = json.loads(self.conn.response[0]['attributes']['oxCacheConfiguration'][0])
            oxCacheConfiguration['cacheProviderType'] = method
            oxCacheConfiguration_js = json.dumps(oxCacheConfiguration)

            dn = self.conn.response[0]['dn']
            
            self.conn.modify(dn, {'oxCacheConfiguration': [MODIFY_REPLACE, oxCacheConfiguration_js]})        
    
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
            

def getLdapConn(addr, dn, passwd):
    """this function gets address, dn and password for ldap server, makes
    connection and return LdapOLC object."""

    ldp = LdapOLC('ldaps://{}:1636'.format(addr), dn, passwd)
    r = None
    try:
        r = ldp.connect()
    except Exception as e:
        flash("Connection to LDAPserver {0} at port 1636 failed: {1}".format(
            addr, e), "danger")
        return
    if not r:
        flash("Connection to LDAPserver {0} at port 1636 failed: {1}".format(
            addr, ldp.conn.result['description']), "danger")
        return
    return ldp


class DBManager(object):
    """A wrapper class to operate on the o=gluu DIT of the LDAP.

    Args:
        hostname (string): hostname of the server running the LDAP server
        port (int): port in which the LDAP server is listening
        password (string): the password of admin `cn=directoy manager,o=gluu`
        ssl (boolean): if connection should be made over ssl or not
        ip (string, optional): ip address of the server for connection fallback
    """
    def __init__(self, hostname, port, password, ssl=True, ip=None):
        self.server = Server(hostname, port=port, use_ssl=ssl)
        
        setup_prop = get_setup_properties()
        
        ldap_user = "cn=directory manager"
        if setup_prop['ldap_type'] == "openldap":
            ldap_user += ",o=gluu"

        self.conn = Connection(self.server, 
                                ldap_user,
                                password=password)
        result = self.conn.bind()

        if not result:
            self.server = Server(ip, port=port, use_ssl=ssl)
            self.conn = Connection(
                self.server, ldap_user,
                password=password)

        self.conn.bind()


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



