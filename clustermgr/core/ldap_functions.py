import re
import time
import logging
import json

from ldap3 import Server, Connection, SUBTREE, BASE, LEVEL, \
    MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE

from clustermgr.models import Server as ServerModel
from clustermgr.core.utils import ldap_encode

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

    def __init__(self, addr, binddn, passwd):
        self.addr = addr
        self.binddn = binddn
        self.passwd = passwd
        self.server = None
        self.conn = None
        self.hostname = get_host_port(addr)[0]

    def connect(self):
        logger.debug("Making Ldap Connection")
        self.server = Server(self.addr, use_ssl=True)
        self.conn = Connection(
            self.server, user=self.binddn, password=self.passwd)
        return self.conn.bind()

    def loadModules(self, *modules):
        """If modules are loaded, returns status, If modules are already loaded returns -1"""
        self.conn.search(search_base='cn=module{0},cn=config',
                         search_filter='(objectClass=*)', search_scope=BASE,
                         attributes=["olcModuleLoad"])

        addList = list(modules)

        if self.conn.response:
            for a in self.conn.response[0]['attributes']['olcModuleLoad']:
                r = re.split("{\d+}", a)
                if len(r) == 1:
                    m = r[0]
                else:
                    m = r[1]
                mn = m.split('.')
                if mn[0] in addList:
                    addList.remove(mn[0])

        if addList:

            return self.conn.modify('cn=module{0},cn=config',
                                    {'olcModuleLoad': [MODIFY_ADD, addList]})

        return -1

    def checkAccesslogDBEntry(self):
        return self.conn.search(search_base='cn=config',
                                search_filter='(olcSuffix=cn=accesslog)',
                                search_scope=SUBTREE, attributes=["*"])

    def accesslogDBEntry(self, replicator_dn, log_dir="/opt/gluu/data/accesslog"):

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

        if not self.checkAccesslogDBEntry():
            return self.conn.add('olcDatabase={2}mdb,cn=config',
                                 attributes=attributes)

    def checkSyncprovOverlaysDB1(self):
        return self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                                search_filter='(olcOverlay=syncprov)',
                                search_scope=SUBTREE, attributes=["*"])

    def syncprovOverlaysDB1(self):
        attributes = {'objectClass':  ['olcOverlayConfig',
                                       'olcSyncProvConfig'],
                      'olcOverlay': 'syncprov',
                      # 'olcSpNoPresent': 'TRUE', ???
                      'olcSpReloadHint': 'TRUE',
                      'olcSpCheckPoint': '100 10',
                      'olcSpSessionlog': '10000',
                      }
        if not self.checkSyncprovOverlaysDB1():
            self.conn.add(
                'olcOverlay=syncprov,olcDatabase={1}mdb,cn=config',
                attributes=attributes)
            if self.conn.result['description'] == 'success':
                return True

    def checkSyncprovOverlaysDB2(self):
        return self.conn.search(search_base='olcDatabase={2}mdb,cn=config',
                                search_filter='(olcOverlay=syncprov)',
                                search_scope=SUBTREE, attributes=["*"])

    def syncprovOverlaysDB2(self):
        attributes = {
            'objectClass':  ['olcOverlayConfig', 'olcSyncProvConfig'],
            # 'structuralObjectClass': ['olcSyncProvConfig'],
            'olcOverlay': 'syncprov',
            'olcSpNoPresent': 'TRUE',
            'olcSpReloadHint': 'TRUE',
            # 'olcSpCheckPoint': '100 10',
            # 'olcSpSessionlog': '10000',
            # 'olcLimits': 'dn.exact="cn=directory manager,o=gluu" time.soft=unlimited time.hard=unlimited size.soft=unlimited size.hard=unlimited',
        }
        if not self.checkSyncprovOverlaysDB2():
            self.conn.add(
                'olcOverlay=syncprov,olcDatabase={2}mdb,cn=config',
                attributes=attributes)

            if self.conn.result['description'] == 'success':
                return True

    def checkServerID(self):
        return self.conn.search(search_base='cn=config',
                                search_filter='(objectClass=*)',
                                search_scope=BASE, attributes=["olcServerID"])

    def setServerID(self, sid):

        mod_type = MODIFY_ADD
        self.conn.search(search_base='cn=config',
                         search_filter='(objectClass=*)',
                         search_scope=BASE, attributes=["olcServerID"])

        if self.checkServerID():
            if self.conn.response[0]['attributes']['olcServerID']:
                mod_type = MODIFY_REPLACE

        return self.conn.modify('cn=config',
                                {'olcServerID': [mod_type, str(sid)]})

    def setDBIndexes(self):
        self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                         search_filter='(objectClass=*)', search_scope=BASE,
                         attributes=["olcDbIndex"])
        addList = ["entryCSN eq", "entryUUID eq"]

        if self.conn.response:
            for idx in self.conn.response[0]['attributes']['olcDbIndex']:
                if idx in addList:
                    addList.remove(idx)

        return self.conn.modify('olcDatabase={1}mdb,cn=config',
                                {'olcDbIndex': [MODIFY_ADD, addList]})

    def checkAccesslogPurge(self):
        return self.conn.search(
            search_base='cn=config',
            search_filter='(objectClass=olcAccessLogConfig)',
            search_scope=SUBTREE, attributes=["olcAccessLogPurge"])

    def accesslogPurge(self, purge='0:24:0 1:0:0'):
        p,a = purge.split()
        pl = p.split(':')
        al = a.split(':')

        olcAccessLogPurge = ''

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
        self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                         search_filter='(objectClass=*)', search_scope=BASE,
                         attributes=["olcMirrorMode"])

        if not self.conn.response:
            return

        if self.conn.response[0]['attributes']['olcMirrorMode']:
            return self.conn.modify('olcDatabase={1}mdb,cn=config',
                                    {"olcMirrorMode": [MODIFY_REPLACE, []]})

    def checkMirroMode(self):
        r = self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                             search_filter='(objectClass=*)',
                             search_scope=BASE, attributes=["olcMirrorMode"])
        if r:
            if self.conn.response[0]['attributes']:
                if self.conn.response[0]['attributes']['olcMirrorMode']:
                    return self.conn.response[0]['attributes']['olcMirrorMode']

        return False

    def makeMirroMode(self):
        return self.conn.modify('olcDatabase={1}mdb,cn=config',
                                {"olcMirrorMode": [MODIFY_ADD, ["TRUE"]]})

    def removeProvider(self, raddr):
        rmMirrorMode = False

        if len(self.getProviders()) <= 1:
            rmMirrorMode = True

        if not self.conn.response:
            return -1

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
        return self.conn.search(search_base='cn=config',
                                search_filter='(olcSuffix=cn=accesslog)',
                                search_scope=SUBTREE, attributes=["*"])

    def addTestUser(self,  cn, sn, mail):
        self.checkBaseDN()
        self.checkTestUserBase()
        uid = '{0}@{1}'.format(time.time(), self.hostname)
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
        return self.conn.search(search_base='ou=testusers,o=gluu',
                                search_filter='(title=gluuClusterMgrTestUser)',
                                search_scope=LEVEL,
                                attributes='*'
                                )

    def delDn(self, dn):
        return self.conn.delete(dn)

    def getProviders(self):
        pDict = {}
        if self.conn.search(search_base='olcDatabase={1}mdb,cn=config',
                            search_filter='(objectClass=*)',
                            search_scope=BASE, attributes=["olcSyncRepl"]):

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
        if self.conn.search(search_base="cn=config", search_scope=LEVEL,
                            search_filter="(olcDbDirectory=/opt/gluu/data/main_db)",
                            attributes='*'):
            if self.conn.response:
                return self.conn.response[0]['dn']

    def setLimitOnMainDb(self, replicator_dn):
        main_db_dn = self.getMainDbDN()
        return self.conn.modify(main_db_dn, {'olcLimits': [MODIFY_ADD, 'dn.exact="{0}" time.soft=unlimited time.hard=unlimited size.soft=unlimited size.hard=unlimited'.format(replicator_dn)]})

    def addReplicatorUser(self, replicator_dn, passwd):
        self.checkBaseDN()
        enc_passwd = ldap_encode(passwd)
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
        r = self.conn.search(search_base="o=gluu", search_filter='(objectClass=top)', search_scope=BASE)
        if not self.conn.search(search_base="o=gluu", search_filter='(objectClass=top)', search_scope=BASE):
            logger.info("Adding base DN")
            self.conn.add('o=gluu', attributes={
                'objectClass': ['organization'],
                'o': 'gluu',
            }
            )

    def configureOxIDPAuthentication(self, servers):
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
        self.conn = Connection(self.server, user="cn=directory manager,o=gluu",
                               password=password, auto_bind=True)

        if not self.conn.bound and ip:
            self.server = Server(ip, port=port, use_ssl=ssl)
            self.conn = Connection(
                self.server, user="cn=directory manager,o=gluu",
                password=password, auto_bind=True)

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



