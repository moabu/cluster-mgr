from datetime import datetime
from datetime import timedelta

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

    def __repr__(self):
        return '<Server %d %s>' % (self.id, self.hostname)


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

class KeyRotation(db.Model):
    __tablename__ = "keyrotation"

    id = db.Column(db.Integer, primary_key=True)

    # key rotation interval (in days)
    interval = db.Column(db.Integer)

    # timestamp when last rotation occured
    rotated_at = db.Column(db.DateTime(True))

    # rotation type based on available backends (oxeleven or jks)
    type = db.Column(db.String(16))

    oxeleven_url = db.Column(db.String(255))

    # token used for accessing oxEleven
    # note, token is encrypted when we save into database;
    # to get the actual token, we need to decrypt it
    oxeleven_token = db.Column(db.LargeBinary)

    # random key for token encryption
    oxeleven_token_key = db.Column(db.LargeBinary)

    # random iv for token encryption
    oxeleven_token_iv = db.Column(db.LargeBinary)

    # inum appliance, useful for searching oxAuth config in LDAP
    inum_appliance = db.Column(db.String(255))

    def should_rotate(self):
        # determine whether we need to rotate the key
        if not self.rotated_at:
            return True
        return datetime.utcnow() > self.next_rotation_at

    @property
    def next_rotation_at(self):
        # when will the keys supposed to be rotated
        return self.rotated_at + timedelta(days=self.interval)


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
