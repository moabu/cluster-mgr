from ldap3 import Server, Connection, MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE, SUBTREE, ALL, BASE, LEVEL
import re
import time
import hashlib
import os

def makeLdapPassword(passwd):
    salt=os.urandom(4)
    sha=hashlib.sha1(passwd)
    sha.update(salt)    
    digest= (sha.digest()+ salt).encode('base64').strip()
    ssha_passwd = '{SSHA}'+ digest

    return ssha_passwd


class ldapOLC(object):
    
    def __init__(self, addr, binddn, passwd):
        self.addr = addr
        self.binddn = binddn
        self.passwd = passwd
        self.server = None
        self.conn = None
        p = '(?:ldap.*://)?(?P<host>[^:/ ]+).?(?P<port>[0-9]*).*'
        m = re.search(p, self.addr)
        self.hostname = m.group('host')

        
    def connect(self):
        print ("Making Ldap Connection")
        self.server = Server(self.addr, use_ssl=True)
        self.conn = Connection(self.server, user=self.binddn, password=self.passwd)
        return self.conn.bind()


    def loadModules(self, *modules):
        mod_type  = MODIFY_ADD
        self.conn.search(search_base = 'cn=module{0},cn=config', search_filter = '(objectClass=*)', search_scope = BASE, attributes = ["olcModuleLoad"])
        addList=list(modules)

        if self.conn.response:
            for a in self.conn.response[0]['attributes']['olcModuleLoad']:
                r=re.split("{\d+}", a)
                if len(r)==1:
                    m = r[0]
                else:
                    m = r[1]
                mn = m.split('.')
                if mn[0] in addList:
                    addList.remove(mn[0])

        return self.conn.modify('cn=module{0},cn=config', {'olcModuleLoad': [MODIFY_ADD, addList]})


    def accesslogDBEntry(self, log_dir = "/opt/gluu/data/accesslog"):
        self.conn.search(search_base = 'cn=config', search_filter = '(olcSuffix=cn=accesslog)', search_scope = SUBTREE, attributes = ["*"])
        if not self.conn.response:
            

            return self.conn.add('olcDatabase={2}mdb,cn=config', attributes={'objectClass':  ['olcDatabaseConfig', 'olcMdbConfig'],
                                                           'olcDatabase': '{2}mdb',
                                                           'olcDbDirectory': log_dir,
                                                           'OlcDbMaxSize': 1073741824,
                                                           'olcSuffix': 'cn=accesslog',
                                                           'olcRootDN': 'cn=admin, cn=accesslog',
                                                           'olcRootPW': makeLdapPassword(self.passwd),
                                                           'olcDbIndex': ['default eq', 'entryCSN,objectClass,reqEnd,reqResult,reqStart'],
                                                           'olcLimits': 'dn.exact="cn=directory manager,o=gluu" time.soft=unlimited time.hard=unlimited size.soft=unlimited size.hard=unlimited',
                                                           
                                                       })

    def syncprovOverlaysDB1(self):
        self.conn.search(search_base = 'olcDatabase={1}mdb,cn=config', search_filter = '(olcOverlay=syncprov)', search_scope = SUBTREE, attributes = ["*"])
        if not self.conn.response:
            return self.conn.add('olcOverlay=syncprov,olcDatabase={1}mdb,cn=config', attributes={'objectClass':  ['olcOverlayConfig', 'olcSyncProvConfig'],
                                                           'olcOverlay': 'syncprov',
                                                           #'olcSpNoPresent': 'TRUE', ???
                                                           'olcSpReloadHint': 'TRUE',
                                                           'olcSpCheckPoint': '100 10',
                                                           'olcSpSessionlog': '10000',
                                                           })


    def syncprovOverlaysDB2(self):

        self.conn.search(search_base = 'olcDatabase={2}mdb,cn=config', search_filter = '(olcOverlay=syncprov)', search_scope = SUBTREE, attributes = ["*"])
        if not self.conn.response:
            return self.conn.add('olcOverlay=syncprov,olcDatabase={2}mdb,cn=config', attributes={
                                                           'objectClass':  ['olcOverlayConfig', 'olcSyncProvConfig'],
                                                           #'structuralObjectClass': ['olcSyncProvConfig'],
                                                           'olcOverlay': 'syncprov',
                                                           'olcSpNoPresent': 'TRUE',
                                                           'olcSpReloadHint': 'TRUE',
                                                           #'olcSpCheckPoint': '100 10',
                                                           #'olcSpSessionlog': '10000',
                                                           #'olcLimits': 'dn.exact="cn=directory manager,o=gluu" time.soft=unlimited time.hard=unlimited size.soft=unlimited size.hard=unlimited',
                                                         })    


    
    def setServerID(self, sid):

        mod_type  = MODIFY_ADD
        self.conn.search(search_base='cn=config', search_filter='(objectClass=*)', search_scope=BASE, attributes = ["olcServerID"])

        if self.conn.response:
            if self.conn.response[0]['attributes']['olcServerID']:
                mod_type = MODIFY_REPLACE

        return self.conn.modify('cn=config', {'olcServerID': [mod_type, str(sid)]})
        

    def setDBIndexes(self):
        self.conn.search(search_base = 'olcDatabase={1}mdb,cn=config', search_filter = '(objectClass=*)', search_scope = BASE, attributes = ["olcDbIndex"])
        addList=["entryCSN eq", "entryUUID eq"]

        if self.conn.response:
            for idx in self.conn.response[0]['attributes']['olcDbIndex']:
                if idx in addList:
                    addList.remove(idx)
        
        return self.conn.modify('olcDatabase={1}mdb,cn=config', {'olcDbIndex': [MODIFY_ADD, addList]})
        

    def accesslogPurge(self):
        print ("accessslog purge")
        self.conn.search(search_base = 'cn=config', search_filter = '(objectClass=olcAccessLogConfig)', search_scope = SUBTREE, attributes = ["olcAccessLogPurge"])

        if not self.conn.response:
            return self.conn.add('olcOverlay=accesslog,olcDatabase={1}mdb,cn=config', attributes={'objectClass':  ['olcOverlayConfig', 'olcAccessLogConfig'],
                                                           'olcOverlay': 'accesslog',
                                                           'olcAccessLogDB': 'cn=accesslog',
                                                           'olcAccessLogOps': 'writes',
                                                           'olcAccessLogSuccess': 'TRUE',
                                                           'olcAccessLogPurge': '07+00:00 01+00:00',

                                                           })

    def removeMirrorMode(self):
        self.conn.search(search_base = 'olcDatabase={1}mdb,cn=config', search_filter = '(objectClass=*)', search_scope = BASE, attributes = ["olcMirrorMode"])
        if self.conn.response:
            if  self.conn.response[0]['attributes']['olcMirrorMode']:
                return self.conn.modify('olcDatabase={1}mdb,cn=config', {"olcMirrorMode": [MODIFY_REPLACE, []]})

    def makeMirroMode(self):
        
        self.conn.search(search_base = 'olcDatabase={1}mdb,cn=config', search_filter = '(objectClass=*)', search_scope = BASE, attributes = ["olcMirrorMode"])
        if self.conn.response:
            if not self.conn.response[0]['attributes']['olcMirrorMode']:
                return self.conn.modify('olcDatabase={1}mdb,cn=config', {"olcMirrorMode": [MODIFY_ADD, ["TRUE"]]})

    def removeProvider(self, raddr):
        self.conn.search(search_base = 'olcDatabase={1}mdb,cn=config', search_filter = '(objectClass=*)', search_scope = BASE, attributes = ["olcSyncRepl"])

        rmMirrorMode = False

        if len(self.conn.response[0]["attributes"]["olcSyncrepl"])==1:
            rmMirrorMode = True

        if self.conn.response:
            for pr in self.conn.response:
                prdict={}
                if pr["attributes"]["olcSyncrepl"]:
                    for pri in pr["attributes"]["olcSyncrepl"]:
                        for l in pri.split():
                            ls=l.split('=')
                            if ls[0]=='provider':
                                if ls[1]==raddr:
                                    baseDn=pr['dn']
                                    r=self.conn.modify(baseDn, {'olcSyncrepl': [MODIFY_DELETE, [pri]]})
                                    if r:
                                        if rmMirrorMode:
                                            self.removeMirrorMode()
                                    return r
        return -1
    def addProvider(self, rid, raddr, rbinddn, rcredentials):
        self.removeProvider(raddr)
        ridText='rid={} provider={} bindmethod=simple binddn="{}" tls_reqcert=never credentials={} searchbase="o=gluu" logbase="cn=accesslog" logfilter="(&(objectClass=auditWriteObject)(reqResult=0))" schemachecking=on type=refreshAndPersist retry="60 +" syncdata=accesslog'.format(rid, raddr, rbinddn, rcredentials)
        return self.conn.modify('olcDatabase={1}mdb,cn=config', {"olcSyncRepl": [MODIFY_ADD, [ridText]]})
        #if r: self.makeMirroMode()
        #return r
        


    def checkAccesslogDB(self):
        return self.conn.search(search_base = 'cn=config', search_filter = '(olcSuffix=cn=accesslog)', search_scope = SUBTREE, attributes = ["*"])



    def addTestUser(self,  cn, sn, mail):
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


    def checkTestUserBase():
        if not self.conn.search(search_base = 'ou=testusers,o=gluu',
                search_filter = '(objectClass=inetOrgPerson)',
                search_scope = BASE,
                attributes='*'
                ):
            conn.add('ou=testusers,o=gluu',   
                 attributes={ 
                     'objectClass': ['top', 'organizationalUnit'],
                     'ou': 'testusers',
                     }
                 )


    def searchTestUsers(self):
        return self.conn.search(search_base = 'ou=testusers,o=gluu',
            search_filter = '(title=gluuClusterMgrTestUser)',
            search_scope = LEVEL,
            attributes='*'
            )
            
    def delDn(self,dn):
        return self.conn.delete(dn)
