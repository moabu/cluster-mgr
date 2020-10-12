import json
import time
import os
from datetime import datetime

from flask import current_app as app

from celery.utils.log import get_task_logger
from ldap3 import Connection
from ldap3 import BASE
from ldap3 import MODIFY_REPLACE
from ldap3 import Server as Ldap3Server
from ldap3.core.exceptions import LDAPSocketOpenError

from ..core.clustermgr_installer import Installer
from ..core.utils import random_chars
from ..core.utils import exec_cmd
from ..core.utils import parse_setup_properties
from ..extensions import celery
from ..extensions import db
from ..models import KeyRotation
from ..models import Server
from ..models import AppConfiguration

task_logger = get_task_logger(__name__)


def generate_jks(passwd, javalibs_dir, jks_path, exp=365,
    sig_keys='RS256 RS384 RS512 ES256 ES384 ES512 PS256 PS384 PS512',
    enc_keys='RSA1_5 RSA'):
    
    if os.path.exists(jks_path):
        os.unlink(jks_path)

    dn = "CN=oxAuth CA Certificates"

    cmd = " ".join([
        "java",
        "-jar", os.path.join(javalibs_dir, "keygen.jar"),
        "-enc_keys", enc_keys,
        "-sig_keys", sig_keys,
        "-dnname", "{!r}".format(dn),
        "-expiration", "{}".format(exp),
        "-keystore", jks_path,
        "-keypasswd", passwd,
    ])
    return exec_cmd(cmd)



def modify_oxauth_config(kr, pub_keys=None, openid_jks_pass="", task_id=None):
    pub_keys = pub_keys or []
    if not pub_keys:
        task_logger.warn("Public keys are not available.")
        return False

    appconf = AppConfiguration.query.first()

    kr = KeyRotation.query.first()
    backup = False
    if kr.inum_appliance:
        try:
            jdata = json.loads(kr.inum_appliance)
            backup = jdata.get('backup')
        except:
            pass

    server = Server.query.filter_by(primary_server=True).first()
    binddn = "cn=Directory Manager"

    s = Ldap3Server(host=server.ip, port=1636, use_ssl=True)
    try:
        conn = Connection(s, user=binddn, password=server.ldap_password, auto_bind=True)
    except LDAPSocketOpenError:
        task_logger.warn("Unable to connecto to LDAP at {}; trying other server (if possible).".format(server.hostname))
        return False

    # base DN for oxAuth config
    oxauth_base = ",".join([
        "ou=oxauth",
        "ou=configuration",
        "o=gluu",
    ])

    conn.search(search_base=oxauth_base, search_filter="(objectClass=*)",
                search_scope=BASE, attributes=['*'])

    if not conn.entries:
        # search failed due to missing entry
        task_logger.warn("Unable to find oxAuth config.")
        return False

    entry = conn.entries[0]

    if backup:
        backup_dir = os.path.join(app.config["DATA_DIR"], 'backup_oxAuthConfWebKeys')
        if not os.path.exists(backup_dir):
            os.mkdir(backup_dir)
        backup_fn = os.path.join(backup_dir, '{}_{}'.format(server.id, datetime.now().strftime('%Y-%m-%d_%H.%M.%S')))
        with open(backup_fn, 'w') as w:
            w.write(entry['oxAuthConfWebKeys'].values[0])

    # oxRevision is increased to make update
    ox_rev = str(int(entry['oxRevision'].values[0]) + 1)

    # update public keys if necessary
    keys_conf = json.loads(entry['oxAuthConfWebKeys'].values[0])
    keys_conf["keys"] = pub_keys
    serialized_keys_conf = json.dumps(keys_conf, indent=2)

    dyn_conf = json.loads(entry["oxAuthConfDynamic"].values[0])
    dyn_conf.update({
        "keyRegenerationEnabled": False,  # always set to False
        "keyRegenerationInterval": kr.interval,
        "defaultSignatureAlgorithm": "RS256",
    })

    dyn_conf.update({
        "webKeysStorage": "keystore",
        "keyStoreSecret": openid_jks_pass,
    })
    serialized_dyn_conf = json.dumps(dyn_conf, indent=2)

    # update the attributes
    task_logger.info("Modifying oxAuth configuration.")
    conn.modify(entry.entry_dn, {
        'oxAuthConfWebKeys': [(MODIFY_REPLACE, [serialized_keys_conf])],
        'oxAuthConfDynamic': [(MODIFY_REPLACE, [serialized_dyn_conf])],
        #'oxRevision': [(MODIFY_REPLACE, [ox_rev])],
    })


    time.sleep(1)

    conn.modify(entry.entry_dn, {
        #'oxAuthConfWebKeys': [(MODIFY_REPLACE, [serialized_keys_conf])],
        #'oxAuthConfDynamic': [(MODIFY_REPLACE, [serialized_dyn_conf])],
        'oxRevision': [(MODIFY_REPLACE, [ox_rev])],
    })


    result = conn.result["description"]
    conn.unbind()
    return result == "success"


@celery.task(bind=True)
def rotate_keys(self):
    task_id = self.request.id
    javalibs_dir = celery.conf["JAVALIBS_DIR"]
    jks_path = celery.conf["JKS_PATH"]
    kr = KeyRotation.query.first()

    if not kr:
        task_logger.warn("Unable to find key rotation data from database; skipping task.")
        return

    # do the key rotation background task
    _rotate_keys(kr, javalibs_dir, jks_path, task_id)


def _rotate_keys(kr, javalibs_dir, jks_path, task_id):
    pub_keys = []
    openid_jks_pass = random_chars()

    task_logger.info("Generating keys.")
    out, err, retcode = generate_jks(
        openid_jks_pass, javalibs_dir, jks_path,
    )
    if retcode == 0:
        json_out = json.loads(out)
        pub_keys = json_out["keys"]
    else:
        task_logger.warn("Unable to generate keys; reason={}".format(err))

    # update LDAP entry
    if pub_keys:
        task_logger.info("Keys have been updated.")

        app_conf = AppConfiguration.query.first()

        for server in Server.query:

            installer = Installer(server, 
                                  app_conf.gluu_version,
                                  ssh_port=server.ssh_port, 
                                  logger_task_id=task_id)

            remote_jks_path = os.path.join(installer.container, 
                                                'etc/certs/oxauth-keys.jks')
            installer.upload_file(jks_path, remote_jks_path)

        mod_oxauth = modify_oxauth_config(kr, pub_keys, openid_jks_pass)
        if mod_oxauth:
            kr.rotated_at = datetime.utcnow()
            db.session.add(kr)
            db.session.commit()
    


@celery.task
def schedule_key_rotation():
    kr = KeyRotation.query.first()

    if not kr:
        task_logger.warn("Unable to find key rotation data from database; skipping task.")
        return

    if not kr.enabled:
        task_logger.warn("Key rotation is disabled.")
        return

    if not kr.should_rotate():
        task_logger.warn(
            "key rotation task will be executed "
            "approximately at {} UTC".format(kr.next_rotation_at)
        )
        return

    # do the key rotation background task
    javalibs_dir = celery.conf["JAVALIBS_DIR"]
    jks_path = celery.conf["JKS_PATH"]
    _rotate_keys(kr, javalibs_dir, jks_path, None)
