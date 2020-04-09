#!/usr/bin/python

import os
import sys
import requests
import time
import datetime
import ldap
import logging

from logging.handlers import RotatingFileHandler

ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_ALLOW)

formatter = logging.Formatter('%(levelname)s %(asctime)s - %(message)s')
log_handler = RotatingFileHandler('/var/log/ldap_cache_cleaner/cache_cleaner.log', maxBytes= 5*1024*1024, backupCount=3)
log_handler.setFormatter(formatter)
log_handler.setLevel(logging.DEBUG)
logger = logging.getLogger('ldap_cache_cleaner')
logger.addHandler(log_handler)
logger.setLevel(logging.DEBUG)


prop_file = '/etc/gluu/conf/gluu-ldap.properties'

if not os.path.exists(prop_file):
    logger.error("LDAP properties file %s not found", prop_file)
    sys.exit()

props = {}

for l in open(prop_file):
    ls = l.strip()
    n = ls.find(':')
    if n > -1:
        k = ls[:n].strip()
        v = ls[n+1:].strip()
        props[k] = v


props['bindPassword'] = os.popen('/opt/gluu/bin/encode.py -e ' + props['bindPassword']).read().strip()

ldap_uri = 'ldaps://'+props['servers'].split(',')[0]

try:
    ldap_conn = ldap.initialize(ldap_uri)
    ldap_conn.simple_bind_s(props['bindDN'], props['bindPassword'])
except Exception as e:
    logger.error("Can't connect to LDAP server: %s", str(e))
    sys.exit()

offset = 0

base_dn = [
        'ou=uma,o=gluu', 'ou=clients,o=gluu', 'ou=authorizations,o=gluu',
        'ou=scopes,o=gluu', 'ou=tokens,o=gluu',
        #'ou=sessions,o=gluu', 'ou=metrics,o=gluu',
        ]


for base in base_dn:

    t_s = time.time()
    dt = datetime.datetime.now() + datetime.timedelta(seconds=offset)
    cur_time = '{}{:02d}{:02d}{:02d}{:02d}{:02d}.{}Z'.format(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, str(dt.microsecond)[:3])

    search_filter = '(&(|(oxAuthExpiration<={0})(exp<={0}))(del=true))'.format(cur_time)

    logger.info("Searching expired cache entries for %s", base)
    try:
        response = ldap_conn.search_s(
                        base, 
                        ldap.SCOPE_SUBTREE,
                        search_filter,
                        attrlist=['dn']
                        )
    except Exception as e:
        logger.error(str(e))
        response = None

    if response:

        logger.info("Deleting %d entries from %s", len(response), base)

        for e in response:
            try:
                ldap_conn.delete(e[0])
            except Exception as e:
                logger.error(str(e))
        
        t_e = time.time()

        logger.info("Cleanup %s took %0.2f", base, t_e - t_s)
