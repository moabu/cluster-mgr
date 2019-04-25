import json
import os
import time
from datetime import datetime

from celery.utils.log import get_task_logger
from ldap3 import Connection
from ldap3 import MODIFY_REPLACE
from ldap3 import Server as Ldap3Server
from ldap3.core.exceptions import LDAPSocketOpenError

from ..core.remote import RemoteClient
from ..core.utils import random_chars
from ..core.utils import exec_cmd
from ..extensions import celery
from ..extensions import db
from ..models import KeyRotation
from ..models import Server
from ..models import AppConfiguration

task_logger = get_task_logger(__name__)

SIG_KEYS = "RS256 RS384 RS512 ES256 ES384 ES512"
ENC_KEYS = "RSA_OAEP RSA1_5"


def generate_jks(passwd, javalibs_dir, jks_path, exp=48):
    if os.path.exists(jks_path):
        os.unlink(jks_path)

    dn = "CN=oxAuth CA Certificates"

    cmd = " ".join([
        "java",
        "-jar", os.path.join(javalibs_dir, "keygen.jar"),
        "-enc_keys", ENC_KEYS,
        "-sig_keys", SIG_KEYS,
        "-dnname", "{!r}".format(dn),
        "-expiration_hours", "{}".format(exp),
        "-keystore", jks_path,
        "-keypasswd", passwd,
    ])
    return exec_cmd(cmd)


def get_remote_jks_path(server, gluu_version):
    return "/opt/gluu-server-{}/etc/certs/oxauth-keys.jks".format(gluu_version)


def get_inum(conn):
    conn.search(
        "ou=appliances,o=gluu",
        "(objectClass=gluuAppliance)",
        attributes=["inum"],
    )
    try:
        return conn.entries[0]["inum"]
    except (IndexError, KeyError):
        return


def get_oxauth_config(conn, inum):
    conn.search(
        "ou=oxauth,ou=configuration,inum={},ou=appliances,o=gluu".format(inum),
        "(objectClass=*)",
        attributes=[
            "oxRevision",
            "oxAuthConfWebKeys",
            "oxAuthConfDynamic",
        ],
    )
    try:
        return conn.entries[0]
    except IndexError:
        return


def merge_keys(new_keys, old_keys):
    now = int(time.time() * 1000)
    for key in old_keys["keys"]:
        if key.get("exp") > now:
            new_keys["keys"].append(key)
    return new_keys


def modify_oxauth_config(conn, entry_dn, ox_rev, conf_dynamic, conf_webkeys):
    serialized_keys_conf = json.dumps(conf_webkeys)
    serialized_dyn_conf = json.dumps(conf_dynamic)
    ox_rev = str(ox_rev + 1)

    conn.modify(entry_dn, {
        "oxRevision": [(MODIFY_REPLACE, [ox_rev])],
        "oxAuthConfWebKeys": [(MODIFY_REPLACE, [serialized_keys_conf])],
        "oxAuthConfDynamic": [(MODIFY_REPLACE, [serialized_dyn_conf])],
    })
    return conn.result


def distribute_jks(jks_path):
    appconf = AppConfiguration.query.first()

    for server in Server.query:
        c = RemoteClient(server.hostname, ip=server.ip)
        try:
            c.startup()
        except Exception:
            task_logger.warn("Couldn't connect to server %s. Can't copy JKS." % server.hostname)
            continue

        remote_jks_path = get_remote_jks_path(server, appconf.gluu_version)
        task_logger.info("Copying JKS to server {}".format(server.hostname))
        task_logger.info(c.upload(jks_path, remote_jks_path))
        c.close()


def _rotate_keys(kr, javalibs_dir, jks_path):
    binddn = "cn=Directory Manager"

    for server in Server.query:
        srv = Ldap3Server(host=server.ip, port=1636, use_ssl=True)

        try:
            task_logger.info("Connecting to LDAP at {}".format(server.hostname))

            with Connection(srv, user=binddn, password=server.ldap_password) as conn:
                # get inum appliance
                inum = get_inum(conn)
                if not inum:
                    task_logger.warn("Unable to find inum appliance; trying from other server (if possible)")
                    continue

                # get oxauth config
                ox_config = get_oxauth_config(conn, inum)
                if not ox_config:
                    task_logger.warn("Unable to find oxAuth config; trying from other server (if possible)")
                    continue

                jks_pass = random_chars()

                ox_rev = int(ox_config["oxRevision"][0])

                conf_dynamic = json.loads(ox_config["oxAuthConfDynamic"][0])
                conf_dynamic.update({
                    "keyRegenerationEnabled": False,
                    "keyRegenerationInterval": kr.interval,
                    "webKeysStorage": "keystore",
                    "keyStoreSecret": jks_pass,
                })

                try:
                    conf_webkeys = json.loads(ox_config["oxAuthConfWebKeys"][0])
                except IndexError:
                    conf_webkeys = {"keys": []}

                # generate public and private keys
                task_logger.info("Generating keys.")
                exp = kr.interval + (conf_dynamic["idTokenLifetime"] / 3600)
                out, err, retcode = generate_jks(
                    jks_pass, javalibs_dir, jks_path, exp=exp,
                )

                if retcode != 0:
                    task_logger.warn("Unable to generate keys; reason={}".format(err))
                    continue

                new_keys = json.loads(out)
                merged_keys = merge_keys(new_keys, conf_webkeys)
                ox_modified = modify_oxauth_config(conn, ox_config.entry_dn, ox_rev, conf_dynamic, merged_keys)

                if ox_modified["description"] != "success":
                    task_logger.warn("Unable to update oxAuth config; reason={}".format(ox_modified["message"]))
                else:
                    task_logger.info("Keys have been updated")
                    kr.rotated_at = datetime.utcnow()
                    db.session.add(kr)
                    db.session.commit()
                    # copy JKS to all servers
                    distribute_jks(jks_path)
                    break
        except LDAPSocketOpenError:
            task_logger.warn("Unable to connect to LDAP at {}; trying other server (if possible).".format(server.hostname))
            continue


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
        task_logger.info("No need to rotate oxAuth keys at the moment")
        return

    # do the key rotation background task
    javalibs_dir = celery.conf["JAVALIBS_DIR"]
    jks_path = celery.conf["JKS_PATH"]
    _rotate_keys(kr, javalibs_dir, jks_path)
