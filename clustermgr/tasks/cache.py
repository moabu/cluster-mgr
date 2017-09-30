import json

from clustermgr.models import Server
from clustermgr.extensions import db, celery, wlogger
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import DBManager


@celery.task(bind=True)
def configure_redis(self, server_id):
    tid = self.request.id
    wlogger.log(tid, "Configuring Redis as Cache", "info")
    server = Server.query.get(server_id)

    c = RemoteClient(server.fqn_hostname)
    try:
        c.startup()
    except Exception as e:
        wlogger.log(tid, "Could not connect using hostname. {0}".format(e),
                    "error")
        wlogger.log(tid, "Retrying with the IP address.", "info")
        c = RemoteClient(server.ip_address)
        try:
            c.startup()
        except Exception as e:
            wlogger.log(tid, "Could not connect to the server. {0}".format(e),
                        "error")
    # TODO
    # 0. Install stunnel and redis - Should this be done by cluster-mgr? Or
    #               Should we ask the admin to do it manually? Most probably
    #               the cluster-mgr
    # 1. Get the oxAuth config from LDAP and change the config values
    # 2. update the stunnel configuration and restart stunnel


@celery.task(bind=True)
def get_cache_methods(self):
    tid = self.request.id
    servers = Server.query.all()
    methods = []
    for server in servers:
        dbm = DBManager(server.hostname, 1636,  server.ldap_password, ssl=True,
                        ip=server.ip,)
        entry = dbm.get_appliance_attributes('oxCacheConfiguration')
        cache_conf = json.loads(entry.oxCacheConfiguration.value)
        server.cache_method = cache_conf['cacheProviderType']
        db.session.commit()
        methods.append({"id": server.id, "method": server.cache_method})
    wlogger.log(tid, str(methods))
    return methods


