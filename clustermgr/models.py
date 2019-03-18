from datetime import datetime
from datetime import timedelta
from sqlalchemy.schema import Sequence
from clustermgr.extensions import db


class Server(db.Model):
    __tablename__ = "server"

    id = db.Column(db.Integer, primary_key=True)

    # Hostname of the server
    hostname = db.Column(db.String(250), unique=True)

    # IP address of the server
    ip = db.Column(db.String(45))

    # rootDN password for the LDAP server
    ldap_password = db.Column(db.String(150))

    # Operating system running in the server
    os = db.Column(db.String(150))

    # Cache method used by the server if it has oxAuth
    cache_method = db.Column(db.String(50))

    # Installed components as comma seperated values
    components = db.Column(db.Text)

    # Flag to indicate whether LDAP MMR has been set up
    mmr = db.Column(db.Boolean)

    # Is the LDAP server inside the gluu server chroot container
    gluu_server = db.Column(db.Boolean)

    # Is this the primary server
    primary_server = db.Column(db.Boolean)

    # Is redis installed
    redis = db.Column(db.Boolean)

    # Is stunnel installed
    stunnel = db.Column(db.Boolean)

    # Is filebeat installed
    filebeat = db.Column(db.Boolean)

    # Is monitoring installed
    monitoring = db.Column(db.Boolean)
    
    def __repr__(self):
        return '<Server {} {}>'.format(self.id, self.hostname)


class AppConfiguration(db.Model):
    __tablename__ = 'appconfig'

    id = db.Column(db.Integer, primary_key=True)

    # the DN of the replication user
    replication_dn = db.Column(db.String(200))

    # the password for replication user
    replication_pw = db.Column(db.String(200))

    # the result of the last replication test
    last_test = db.Column(db.Boolean)

    # gluu server version
    gluu_version = db.Column(db.String(10))

    # use ip for replication
    use_ip = db.Column(db.Boolean())

    nginx_host = db.Column(db.String(250))

    log_purge = db.Column(db.String(50))

    admin_email = db.Column(db.String())

    # flag if monitoring installed
    monitoring = db.Column(db.Boolean())

    # if ip-host pairs will be written to /etc/hosts
    modify_hosts = db.Column(db.Boolean())

    nginx_ip = db.Column(db.String(50))

    ldap_update_period = db.Column(db.Integer)

    object_class_base = db.Column(db.String(50))
    attribute_oid = db.Column(db.Integer, default=100)
    
    external_load_balancer = db.Column(db.Boolean())
    
    use_ldap_cache = db.Column(db.Boolean())
    nginx_os_type = db.Column(db.String(10))
    ldap_update_period_unit = db.Column(db.String(1), default='s')
    
    latest_version = db.Column(db.String(10))

    offline = db.Column(db.Boolean())
    gluu_archive = db.Column(db.String(50))


class KeyRotation(db.Model):
    __tablename__ = "keyrotation"

    id = db.Column(db.Integer, primary_key=True)

    # key rotation interval (in hours)
    interval = db.Column(db.Integer)

    # timestamp when last rotation occured
    rotated_at = db.Column(db.DateTime(True))

    # rotation type based on available backends (oxeleven or jks)
    type = db.Column(db.String(16))

    # inum appliance, useful for searching oxAuth config in LDAP
    inum_appliance = db.Column(db.String(255))

    # whether rotation is enabled or not
    enabled = db.Column(db.Boolean, default=False)

    def should_rotate(self):
        # determine whether we need to rotate the key
        if not self.rotated_at:
            return True
        return datetime.utcnow() > self.next_rotation_at

    @property
    def next_rotation_at(self):
        # when will the keys supposed to be rotated
        return self.rotated_at + timedelta(hours=self.interval)


class OxelevenKeyID(db.Model):
    __tablename__ = "oxeleven_key_id"

    id = db.Column(db.Integer, primary_key=True)
    kid = db.Column(db.String(255))


class LoggingServer(db.Model):
    __tablename__ = "logging_server"

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(255))

    # # RDBMS backend, must be ``mysql`` or ``postgres``
    # db_backend = db.Column(db.String(16))

    # # RDBMS hostname or IP address
    # db_host = db.Column(db.String(128))

    # # RDBMS port
    # db_port = db.Column(db.Integer)

    # db_user = db.Column(db.String(128))

    # # encrypted password; need to decrypt it before using the value
    # db_password = db.Column(db.String(255))

    # # ActiveMQ hostname or IP address
    # mq_host = db.Column(db.String(128))

    # # ActiveMQ port
    # mq_port = db.Column(db.Integer)

    # mq_user = db.Column(db.String(128))

    # # encrypted password; need to decrypt it before using the value
    # mq_password = db.Column(db.String(255))


class CacheServer(db.Model):
    __tablename__ = "cache_server"
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(250))
    ip = db.Column(db.String(45))
    install_redis = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return '<Cache Server {} {}>'.format(self.id, self.hostname)


@db.event.listens_for(CacheServer, 'before_insert')
def do_stuff(mapper, connect, target):
    last_entry = CacheServer.query.order_by(CacheServer.id.desc()).first()
    if last_entry:
        target.id = last_entry.id + 1
    else:
        target.id = 1000
