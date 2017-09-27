import json
import requests

from datetime import datetime
from ldap3 import Connection, BASE, MODIFY_REPLACE
from ldap3 import Server as Ldap3Server

from clustermgr.extensions import celery, db
from clustermgr.models import Server, KeyRotation, OxelevenKeyID
from clustermgr.core.utils import decrypt_text, random_chars
from clustermgr.core.ox11 import generate_key, delete_key
from clustermgr.core.keygen import generate_jks


def starttls(server):
    return server.protocol == 'starttls'


def modify_oxauth_config(kr, pub_keys=None, openid_jks_pass=""):
    server = Server.query.first()

    pub_keys = pub_keys or []
    if not pub_keys:
        return

    s = Ldap3Server(host=server.ip, port=1636, use_ssl=True)
    conn = Connection(s, user="cn=directory manager,o=gluu",
                      password=server.ldap_password, auto_bind=True)

    # base DN for oxAuth config
    oxauth_base = ",".join([
        "ou=oxauth",
        "ou=configuration",
        "inum={}".format(kr.inum_appliance),
        "ou=appliances",
        "o=gluu",
    ])

    conn.search(search_base=oxauth_base, search_filter="(objectClass=*)",
                search_scope=BASE, attributes=['*'])
    if not conn.entries:
        # search failed due to missing entry
        return
    entry = conn.entries[0]

    # oxRevision is increased to make update
    ox_rev = str(int(entry['oxRevision'].values[0]) + 1)

    # update public keys if necessary
    keys_conf = json.lods(entry['oxAuthConfWebKeys'].values[0])
    keys_conf["keys"] = pub_keys
    serialized_keys_conf = json.dumps(keys_conf)

    dyn_conf = json.loads(entry["oxAuthConfDynamic"].values[0])
    dyn_conf.update({
        "keyRegenerationEnabled": False,  # always set to False
        "keyRegenerationInterval": kr.interval * 24,
        "defaultSignatureAlgorithm": "RS512",
    })

    if kr.type == 'oxeleven':
        dyn_conf.update({
            "oxElevenGenerateKeyEndpoint": "{}/oxeleven/rest/oxeleven/generateKey".format(kr.oxeleven_url),  # noqa
            "oxElevenSignEndpoint": "{}/oxeleven/rest/oxeleven/sign".format(kr.oxeleven_url),  # noqa
            "oxElevenVerifySignatureEndpoint": "{}/oxeleven/rest/oxeleven/verifySignature".format(kr.oxeleven_url),  # noqa
            "oxElevenDeleteKeyEndpoint": "{}/oxeleven/rest/oxeleven/deleteKey".format(kr.oxeleven_url),  # noqa
            "oxElevenJwksEndpoint": "{}/oxeleven/rest/oxeleven/jwks".format(kr.oxeleven_url),  # noqa
            "oxElevenTestModeToken": decrypt_text(kr.oxeleven_token, kr.oxeleven_token_key, kr.oxeleven_token_iv),  # noqa
            "webKeysStorage": "pkcs11",
        })
    else:
        dyn_conf.update({
            "webKeysStorage": "keystore",
            "keyStoreSecret": openid_jks_pass,
        })
    serialized_dyn_conf = json.dumps(dyn_conf)

    # update the attributes
    conn.modify(entry.entry_dn, {
        'oxRevision': [(MODIFY_REPLACE, [ox_rev])],
        'oxAuthConfWebKeys': [(MODIFY_REPLACE, [serialized_keys_conf])],
        'oxAuthConfDynamic': [(MODIFY_REPLACE, [serialized_dyn_conf])],
    })

    print conn.result
    conn.unbind()
    return True


@celery.task(bind=True)
def rotate_pub_keys(t):
    javalibs_dir = celery.conf["JAVALIBS_DIR"]
    jks_path = celery.conf["JKS_PATH"]
    kr = KeyRotation.query.first()

    if not kr:
        print "unable to find key rotation data from database; skipping task"
        return

    # do the key rotation background task
    _rotate_keys(kr, javalibs_dir, jks_path)


def _rotate_keys(kr, javalibs_dir, jks_path):
    pub_keys = []
    openid_jks_pass = random_chars()

    if kr.type == "oxeleven":
        token = decrypt_text(kr.oxeleven_token, kr.oxeleven_token_key,
                             kr.oxeleven_token_iv)

        try:
            # delete old keys first
            print "deleting old keys"
            for key_id in OxelevenKeyID.query:
                status_code, out = delete_key(kr.oxeleven_url, key_id.kid, token)
                if status_code == 200 and out["deleted"]:
                    db.session.delete(key_id)
                    db.session.commit()
                elif status_code == 401:
                    print "insufficient access to call oxEleven API"

            # obtain new keys
            print "obtaining new keys"
            for algo in ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]:
                status_code, out = generate_key(kr.oxeleven_url, algo, token=token)
                if status_code == 200:
                    key_id = OxelevenKeyID()
                    key_id.kid = out["kid"]
                    db.session.add(key_id)
                    db.session.commit()
                    pub_keys.append(out)
                elif status_code == 401:
                    print "insufficient access to call oxEleven API"
                else:
                    print "unable to obtain the keys from oxEleven; " \
                        "status code={}".format(status_code)
        except requests.exceptions.ConnectionError:
            print "unable to establish connection to oxEleven; skipping task"
    else:
        out, err, retcode = generate_jks(
            openid_jks_pass, javalibs_dir, jks_path,
        )
        if retcode == 0:
            json_out = json.loads(out)
            pub_keys = json_out["keys"]
        else:
            print err

    # update LDAP entry
    if pub_keys and modify_oxauth_config(kr, pub_keys, openid_jks_pass):
        print "pub keys has been updated"
        kr.rotated_at = datetime.utcnow()
        db.session.add(kr)
        db.session.commit()

        if kr.type == "jks":
            from clustermgr.core.remote import RemoteClient
            for server in Server.query:
                c = RemoteClient(server.hostname)
                try:
                    c.startup()
                except Exception:
                    print "Couldn't connect to server %s. Can't copy JKS" % server.hostname
                    continue
                c.upload(jks_path, server.jks_path)
                c.close()


@celery.task
def schedule_key_rotation():
    kr = KeyRotation.query.first()

    if not kr:
        print "unable to find key rotation data from database; skipping task"
        return

    if not kr.should_rotate():
        print "key rotation task will be executed " \
              "approximately at {} UTC".format(kr.next_rotation_at)
        return

    # do the key rotation background task
    javalibs_dir = celery.conf["JAVALIBS_DIR"]
    jks_path = celery.conf["JKS_PATH"]
    _rotate_keys(kr, javalibs_dir, jks_path)


# disabled for backward-compatibility with celery 3.x
#@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        celery.conf['SCHEDULE_REFRESH'],
        schedule_key_rotation.s(),
        name='add every 30',
    )
