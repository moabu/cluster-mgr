from clustermgr.model import LdapServer
from clustermgr.extensions import celery, wlogger
from clustermgr.core.remote import RemoteClient


@celery.task(bind=True)
def configure_redis(self, server_id):
    tid = self.request.id
    wlogger.log(tid, "Configuring Redis as Cache", "info")
    server = LdapServer.query.get(server_id)

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
