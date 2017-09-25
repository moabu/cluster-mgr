from ldap3 import Server, Connection, SUBTREE, BASE, LEVEL, \
        MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE
import re
import time
import hashlib
import os


def makeLdapPassword(passwd):
    salt = os.urandom(4)
    sha = hashlib.sha1(passwd)
    sha.update(salt)
    digest = (sha.digest() + salt).encode('base64').strip()
    ssha_passwd = '{SSHA}' + digest

    return ssha_passwd


def getHostPort(addr):
    m = re.search('(?:ldap.*://)?(?P<host>[^:/ ]+).?(?P<port>[0-9]*).*',  addr)
    return m.group('host'), m.group('port')


class ldapOLC(object):

    def __init__(self, addr, binddn, passwd):
        self.addr = addr
        self.binddn = binddn
        self.passwd = passwd
        self.server = None
        self.conn = None
        self.hostname = getHostPort(addr)[0]

    def connect(self):
        print ("Making Ldap Connection")
        self.server = Server(self.addr, use_ssl=True)
        self.conn = Connection(
            self.server, user=self.binddn, password=self.passwd)
        return self.conn.bind()

    def loadModules(self, *modules):
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

        return self.conn.modify('cn=module{0},cn=config',
                                {'olcModuleLoad': [MODIFY_ADD, addList]})

    def checkAccesslogDBEntry(self):
        return self.conn.search(search_base='cn=config',
                                search_filter='(olcSuffix=cn=accesslog)',
                                search_scope=SUBTREE, attributes=["*"])

    def accesslogDBEntry(self, replicator_dn, log_dir="/opt/gluu/data/accesslog"):
        
        attributes={'objectClass':  ['olcDatabaseConfig', 'olcMdbConfig'],
                                                           'olcDatabase': '{2}mdb',
                                                           'olcDbDirectory': log_dir,
                                                           'OlcDbMaxSize': 1073741824,
                                                           'olcSuffix': 'cn=accesslog',
                                                           'olcRootDN': 'cn=admin, cn=accesslog',
                                                           'olcRootPW': makeLdapPassword(self.passwd),
                                                           'olcDbIndex': ['default eq', 'objectClass,entryCSN,entryUUID,reqEnd,reqResult,reqStart'],
                                                           'olcLimits': 'dn.exact="{0}" time.soft=unlimited time.hard=unlimited size.soft=unlimited size.hard=unlimited'.format(replicator_dn),
                                                           
                                                       }
        
        if not self.checkAccesslogDBEntry():
            return self.conn.add('olcDatabase={2}mdb,cn=config', attributes=attributes)

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
            return self.conn.add(
                'olcOverlay=syncprov,olcDatabase={1}mdb,cn=config', attributes=attributes)

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
            return self.conn.add(
                'olcOverlay=syncprov,olcDatabase={2}mdb,cn=config', attributes=attributes)

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

    def accesslogPurge(self):
        attributes = {
            'objectClass':  ['olcOverlayConfig', 'olcAccessLogConfig'],
            'olcOverlay': 'accesslog',
            'olcAccessLogDB': 'cn=accesslog',
            'olcAccessLogOps': 'writes',
            'olcAccessLogSuccess': 'TRUE',
            'olcAccessLogPurge': '07+00:00 01+00:00',
        }
        if not self.checkAccesslogPurge():
            return self.conn.add(
                'olcOverlay=accesslog,olcDatabase={1}mdb,cn=config', attributes=attributes
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
        if not self.checkMirroMode():
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

    def addProvider(self, rid, raddr, rbinddn, rcredentials):
        host = getHostPort(raddr)[0]
        if host not in self.getProviders():
            ridText = """rid={0} provider={1} bindmethod=simple binddn="{2}" tls_reqcert=never credentials={3} searchbase="o=gluu" logbase="cn=accesslog" logfilter="(&(objectClass=auditWriteObject)(reqResult=0))" schemachecking=on type=refreshAndPersist retry="60 +" syncdata=accesslog sizeLimit=unlimited timelimit=unlimited""".format(
                rid, raddr, rbinddn, rcredentials)

            return self.conn.modify('olcDatabase={1}mdb,cn=config',
                                    {"olcSyncRepl": [MODIFY_ADD, [ridText]]})

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
                    print e, es
                    if re.search('(\{\d*\})*rid',  es[0]):
                        pid = es[1]
                    elif es[0] == 'provider':
                        host, port = getHostPort(es[1])
                pDict[host] = (pid, port)

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
        enc_passwd = makeLdapPassword(passwd)
        m=re.search('cn=(?P<cn>\w+),o=gluu', 'cn=replicator,o=gluu')
        cn=m.group('cn')
        if not self.conn.search(replicator_dn, search_filter='(objectClass=*)', search_scope=BASE):
            self.conn.add(replicator_dn,
                          attributes={'objectClass': ['top', 'inetOrgPerson'],
                                      'cn': cn,
                                      'sn': 'replicator',
                                      'uid': 'replicator',
                                      'userpassword': enc_passwd,
                                      }
                          )
        if self.conn.result['description'] == 'success':
            return True

    def changeReplicationUserPassword(self, replicator_dn, passwd):
        enc_passwd = makeLdapPassword(passwd)
        return self.conn.modify(replicator_dn, {"userPassword": [MODIFY_REPLACE, enc_passwd]})

    def checkBaseDN(self):
        if not self.conn.search(search_base="o=gluu", search_filter='(objectClass=top)', search_scope=BASE):
            print "Adding base DN"
            self.conn.add('o=gluu', attributes={
                                        'objectClass': ['top', 'organization'],
                                        'o': 'gluu',
                                  }
                        )
