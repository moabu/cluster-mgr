#!/usr/bin/env python
# ------------------------------------
"""
updating cache refresh in gluu server
Author : Mohammad Abudayyeh
support@gluu.org
"""
import base64
import logging
import os
import string
import time
import pwd
import shutil
from ldap3 import Server, Connection, MODIFY_REPLACE


logger = logging.getLogger("cr_rotate")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
fmt = logging.Formatter('%(levelname)s - %(asctime)s - %(message)s')
ch.setFormatter(fmt)
logger.addHandler(ch)


def get_credentials():
    bindDN = None
    bindPassword = None
    inumAppliance = None
    ldapHost = None
    with open('/etc/gluu/conf/ox-ldap.properties', 'r+') as f:
        for line in f:
            ls = line.strip()
            if ls.startswith('servers:'):
                lsl = ls.split('servers:')
                ldap_host_port = lsl[1].strip().split(',')[0].strip()
                ldapHost, ldapPort = ldap_host_port.split(':')
                
            elif ls.startswith('bindDN:'):
                bindDN = ls.split('bindDN:')[1].strip()

            elif ls.startswith('bindPassword:'):
        
                lsl = ls.split('bindPassword:')
                bindPassword_encoded = lsl[1].strip()
                bindPassword = os.popen('/opt/gluu/bin/encode.py -D {}'.format(bindPassword_encoded)).read().strip()
                
            elif ls.startswith('oxauth_ConfigurationEntryDN='):
                lsl = ls.split('oxauth_ConfigurationEntryDN=')
                lsll = lsl[1].split(',')
                inumAppliance = lsll[2].replace('inum=','')
                
    return bindDN, bindPassword, inumAppliance, ldapHost


def clean_snapshot(ip):
    logger.info("Cleaning cache folders for node with IP {}".format(ip))
    if os.path.isdir('/var/ox/identity/cr-snapshots/'):
        shutil.rmtree('/var/ox/identity/cr-snapshots/')
    if not os.path.isdir('/var/ox/identity/cr-snapshots/'):
        os.makedirs('/var/ox/identity/cr-snapshots/')
        # jetty:jetty /var/ox/identity/cr-snapshots/
        uid, gid = pwd.getpwnam('jetty').pw_uid, pwd.getpwnam('jetty').pw_uid
        os.chown('/var/ox/identity/cr-snapshots/', uid, gid)


def get_appliance(conn_ldap, inum):
    if not inum:
        conn_ldap.search('ou=appliances,o=gluu', '(objectclass=gluuAppliance)', attributes=['gluuIpAddress'])
    else:
        conn_ldap.search(
            'inum={},ou=appliances,o=gluu'.format(inum),
            '(objectclass=gluuAppliance)',
            attributes=['oxTrustCacheRefreshServerIpAddress',
                        'gluuVdsCacheRefreshEnabled']
        )
    return conn_ldap.entries[0]


def update_appliance(conn_ldap, appliance, ip):
    try:
        dn = str(appliance)
        dn = dn[dn.find("inum"):dn.find("ou=appliances,o=gluu") + 20]
        logger.info("Updating oxTrustCacheRefreshServerIpAddress with IP {}".format(ip))
        conn_ldap.modify(dn,
                         {'oxTrustCacheRefreshServerIpAddress': [(MODIFY_REPLACE, [ip])]})
        result = conn_ldap.result
        if result["description"] == "success":
            logger.info("CacheRefresh config has been updated")
        else:
            logger.warn("Unable to update CacheRefresh config; reason={}".format(result["message"]))
    except Exception as e:
        logger.warn("Unable to update CacheRefresh config; reason={}".format(e))


def main():
    
    
    bindDN, bindPassword, inumAppliance, ldapHost = get_credentials()
    
    credentials = get_credentials()
    # Get creds for LDAP access
    ldap_server = Server(ldapHost, port=1636, use_ssl=True)

    try:
        with Connection(ldap_server, bindDN, bindPassword) as conn_ldap:
            ip_appliance = get_appliance(conn_ldap, inum='')
            ip = str(ip_appliance["gluuIpAddress"])
            appliance = get_appliance(conn_ldap, inumAppliance)
            current_ip_in_ldap = appliance["oxTrustCacheRefreshServerIpAddress"]
            is_cr_enabled = bool(str(appliance["gluuVdsCacheRefreshEnabled"]).strip() == "enabled")
            # The user has disabled the CR or CR is not active
            if not is_cr_enabled:
                # TODO: should we bail since CR is disabled?
                logger.warn('Cache refresh is found to be disabled.')

            if ip.strip() != str(current_ip_in_ldap).strip() and is_cr_enabled:
                logger.info("Current oxTrustCacheRefreshServerIpAddress: {}".format(current_ip_in_ldap))
                # Clean cache folder
                clean_snapshot(ip)
                update_appliance(conn_ldap, appliance, ip)

    except KeyboardInterrupt:
        logger.warn("Canceled by user; exiting ...")


if __name__ == "__main__":
    main()
