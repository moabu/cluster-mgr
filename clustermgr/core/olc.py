"""A LDAP3 based module that provides classes to handle manipulation of the
On-Line Configuration (OLC) of OpenLDAP server.
"""
from ldap3 import Server, Connection, BASE, SUBTREE, MODIFY_ADD, \
        MODIFY_DELETE, MODIFY_REPLACE


class CnManager(object):
    def __init__(self, addr, port, ssl, username, password):
        self.server = Server(addr, port=port, use_ssl=ssl)
        self.conn = Connection(self.server, user=username, password=password,
                               auto_bind=True)
        self.gluu_db_dn = None

    def __get_gluu_db_dn(self):
        """Function that gets the full DN of the cn=config module containing
        the configuration of o=gluu data.

        Returns:
            either the dn as string or None
        """
        self.conn.search("cn=config", "(objectclass=olcMdbConfig)",
                         search_scope=SUBTREE, attributes=['*'])
        for entry in self.conn.entries:
            if 'o=gluu' in entry.olcSuffix:
                self.gluu_db_dn = entry.entry_dn
        return None  # TODO: probably raise an exception and destroy conn

    def add_olcsyncrepl(self, repl):
        """Function adds a olcSyncRepl attribute value to the cn=config
        concerning the o=gluu database.

        Args:
            repl (string, list): the string which has the syncrepl config
                to be added to the server, or a list of syncrepl strings

        Returns:
            success or failure of the add operation as True or False
        """
        if not self.gluu_db_dn:
            self.__get_gluu_db_dn()

        if type(repl) is str:
            repl = [repl]  # put it in a list to satisfy mod command

        mod = {'olcSyncRepl': [(MODIFY_ADD, repl)]}
        return self.conn.modify(self.gluu_db_dn, mod)

    def remove_olcsyncrepl(self, server_id):
        """Function removes the syncrepl config of a particular server from
        the o=gluu olcDatabase config.

        Args:
            server_id (int): the id of the server whose config has to be
                removed

        """
        if not self.gluu_db_dn:
            self.__get_gluu_db_dn()

        self.conn.search(self.gluu_db_dn, "(objectclass=*)",
                         search_scope=BASE, attributes=['olcSyncRepl'])
        entry = self.conn.entries[0]
        for item in entry.olcSyncRepl:
            if 'rid={0} provider'.format(server_id) not in item:
                continue
            # delete the entry if server id matches
            mod = {'olcSyncRepl': [(MODIFY_DELETE, [item])]}
            return self.conn.modify(self.gluu_db_dn, mod)

    def close(self):
        """Unbinds from the connection and closes it down"""
        self.conn.unbind()

    def recent_result(self):
        """This function returns the connection.result value at the requested
        instant. Would be helpful for debugging errors in case operations fail
        """
        return self.conn.result

    def enable_mirrormode(self):
        """This function sets the MirrorMode value to TRUE
        """
        if not self.gluu_db_dn:
            self.__get_gluu_db_dn()

        self.conn.search(self.gluu_db_dn, "(objectclass=*)", search_scope=BASE,
                         attributes=['olcMirrorMode'])
        entry = self.conn.entries[0]

        if len(entry.olcMirrorMode) == 0:
            mod = {'olcMirrorMode': [(MODIFY_ADD, [True])]}
        else:
            mod = {'olcMirrorMode': [(MODIFY_REPLACE, [True])]}

        return self.conn.modify(self.gluu_db_dn, mod)

    def disable_mirrormode(self):
        """This function removed the MirrorMode attribute from the entry.
        """
        if not self.gluu_db_dn:
            self.__get_gluu_db_dn()

        self.conn.search(self.gluu_db_dn, "(objectclass=*)", search_scope=BASE,
                         attributes=['olcMirrorMode'])
        entry = self.conn.entries[0]

        if len(entry.olcMirrorMode) == 0:
            return True

        mod = {'olcMirrorMode': [(MODIFY_DELETE, [])]}
        return self.conn.modify(self.gluu_db_dn, mod)
