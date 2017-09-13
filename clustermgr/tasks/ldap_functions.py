from ldap3 import Server, Connection, MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE, SUBTREE, ALL, BASE
import re

class ldapOLC(object):
    
    def __init__(self, addr, binddn, passwd):
        self.addr = addr
        self.binddn = binddn
        self.passwd = passwd
        self.server = None
        self.conn = None
        
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
                                                           'olcSuffix': 'cn=accesslog',
                                                           'olcRootDN': 'cn=admin, cn=accesslog',
                                                           'olcRootPW': 'TopSecret',
                                                           'olcDbIndex': ['default eq', 'entryCSN,objectClass,reqEnd,reqResult,reqStart'],
                                                       })

    def syncprovOverlaysDB1(self):
        self.conn.search(search_base = 'olcDatabase={1}mdb,cn=config', search_filter = '(olcOverlay=syncprov)', search_scope = SUBTREE, attributes = ["*"])
        if not self.conn.response:
            return self.conn.add('olcOverlay=syncprov,olcDatabase={1}mdb,cn=config', attributes={'objectClass':  ['olcOverlayConfig', 'olcSyncProvConfig'],
                                                           'olcOverlay': 'syncprov',
                                                           'olcSpNoPresent': 'TRUE',
                                                           })


    def syncprovOverlaysDB2(self):

        self.conn.search(search_base = 'olcDatabase={2}mdb,cn=config', search_filter = '(olcOverlay=syncprov)', search_scope = SUBTREE, attributes = ["*"])
        if not self.conn.response:
            return self.conn.add('olcOverlay=syncprov,olcDatabase={2}mdb,cn=config', attributes={'objectClass':  ['olcOverlayConfig', 'olcSyncProvConfig'],
                                                           'olcOverlay': 'syncprov',
                                                           'olcSpNoPresent': 'TRUE',
                                                           'olcSpReloadHint': 'TRUE',
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
