import json
import os
from datetime import datetime

from celery.utils.log import get_task_logger
from ldap3 import Connection
from ldap3 import BASE
from ldap3 import MODIFY_REPLACE
from ldap3 import Server as Ldap3Server
from ldap3.core.exceptions import LDAPSocketOpenError

from ..core.remote import RemoteClient
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
                 alg="RS256 RS384 RS512 ES256 ES384 ES512"):
    if os.path.exists(jks_path):
        os.unlink(jks_path)

    dn = "CN=oxAuth CA Certificates"

    cmd = " ".join([
        "java",
        "-jar", os.path.join(javalibs_dir, "keygen.jar"),
        "-enc_keys", alg,
        "-sig_keys", alg,
        "-dnname", "{!r}".format(dn),
        "-expiration", "{}".format(exp),
        "-keystore", jks_path,
        "-keypasswd", passwd,
    ])
    return exec_cmd(cmd)


def get_props(server, gluu_version):
    props = {}
    props_fn = "/opt/gluu-server-{}/install/community-edition-setup/setup.properties.last".format(gluu_version)

    rc = RemoteClient(server.hostname, ip=server.ip)
    try:
        rc.startup()
    except Exception as exc:
        task_logger.warn(exc)
        task_logger.warn("Couldn't connect to server %s." % server.hostname)
    else:
        _, stdout, stderr = rc.run("cat {}".format(props_fn))
        if not stderr:
            props = parse_setup_properties(stdout.splitlines())
    rc.close()
    return props


def get_remote_jks_path(server, gluu_version):
    return "/opt/gluu-server-{}/etc/certs/oxauth-keys.jks".format(gluu_version)


def modify_oxauth_config(kr, pub_keys=None, openid_jks_pass=""):
    pub_keys = pub_keys or []
    if not pub_keys:
        task_logger.warn("Public keys are not available.")
        return False

    appconf = AppConfiguration.query.first()

    for server in Server.query:
        props = get_props(server, appconf.gluu_version)
        binddn = "cn=Directory Manager"

        s = Ldap3Server(host=server.ip, port=1636, use_ssl=True)
        try:
            conn = Connection(s, user=binddn, password=server.ldap_password, auto_bind=True)
        except LDAPSocketOpenError:
            task_logger.warn("Unable to connecto to LDAP at {}; trying other server (if possible).".format(server.hostname))
            continue

        # base DN for oxAuth config
        oxauth_base = ",".join([
            "ou=oxauth",
            "ou=configuration",
            "inum={}".format(props.get("inumAppliance")),
            "ou=appliances",
            "o=gluu",
        ])

        conn.search(search_base=oxauth_base, search_filter="(objectClass=*)",
                    search_scope=BASE, attributes=['*'])

        if not conn.entries:
            # search failed due to missing entry
            task_logger.warn("Unable to find oxAuth config.")
            continue

        entry = conn.entries[0]

        # oxRevision is increased to make update
        ox_rev = str(int(entry['oxRevision'].values[0]) + 1)

        # update public keys if necessary
        keys_conf = json.loads(entry['oxAuthConfWebKeys'].values[0])
        keys_conf["keys"] = pub_keys
        serialized_keys_conf = json.dumps(keys_conf)

        dyn_conf = json.loads(entry["oxAuthConfDynamic"].values[0])
        dyn_conf.update({
            "keyRegenerationEnabled": False,  # always set to False
            "keyRegenerationInterval": kr.interval,
            "defaultSignatureAlgorithm": "RS512",
        })

        dyn_conf.update({
            "webKeysStorage": "keystore",
            "keyStoreSecret": openid_jks_pass,
        })
        serialized_dyn_conf = json.dumps(dyn_conf)

        # update the attributes
        task_logger.info("Modifying oxAuth configuration.")
        conn.modify(entry.entry_dn, {
            'oxRevision': [(MODIFY_REPLACE, [ox_rev])],
            'oxAuthConfWebKeys': [(MODIFY_REPLACE, [serialized_keys_conf])],
            'oxAuthConfDynamic': [(MODIFY_REPLACE, [serialized_dyn_conf])],
        })

        result = conn.result["description"]
        conn.unbind()
        return result == "success"

    # default return value
    return False


@celery.task(bind=True)
def rotate_keys(t):
    javalibs_dir = celery.conf["JAVALIBS_DIR"]
    jks_path = celery.conf["JKS_PATH"]
    kr = KeyRotation.query.first()

    if not kr:
        task_logger.warn("Unable to find key rotation data from database; skipping task.")
        return

    # do the key rotation background task
    _rotate_keys(kr, javalibs_dir, jks_path)


def _rotate_keys(kr, javalibs_dir, jks_path):
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
    if pub_keys and modify_oxauth_config(kr, pub_keys, openid_jks_pass):
        task_logger.info("Keys have been updated.")
        kr.rotated_at = datetime.utcnow()
        db.session.add(kr)
        db.session.commit()

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
    _rotate_keys(kr, javalibs_dir, jks_path)
