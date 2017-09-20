# -*- coding: utf-8 -*-

import re
import os

from flask import current_app as app
from flask import session
from clustermgr.models import LDAPServer, LdapServer, MultiMaster
from clustermgr.extensions import celery, wlogger, db
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import ldapOLC, makeLdapPassword

def run_command(tid, c, command, container=None):
    if container=='/': container=None
    """Shorthand for RemoteClient.run(). This function automatically logs
    the commands output at appropriate levels to the WebLogger to be shared
    in the web frontend.

    Args:
        tid (string): task id of the task to store the log
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        command (string): the command to be run on the remote server
        container (string, optional): location where the Gluu Server container
            is installed. For standalone LDAP servers this is not necessary.

    Returns:
        the output of the command or the err thrown by the command as a string
    """
    if container:
        command = 'chroot {0} /bin/bash -c "{1}"'.format(container,
                                                         command)

    wlogger.log(tid, command, "debug")
    cin, cout, cerr = c.run(command)
    output = ''
    if cout:
        wlogger.log(tid, cout, "debug")
        output += "\n"+ cout
    if cerr:
        # For some reason slaptest decides to send success message as err, so
        if 'config file testing succeeded' in cerr:
            wlogger.log(tid, cerr, "success")
        else:
            wlogger.log(tid, cerr, "error")
        output += "\n" + cerr
        
    return output


def upload_file(tid, c, local, remote):
    """Shorthand for RemoteClient.upload(). This function automatically handles
    the logging of events to the WebLogger

    Args:
        tid (string): id of the task running the command
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        local (string): local location of the file to upload
        remote (string): location of the file in remote server
    """
    out = c.upload(local, remote)
    wlogger.log(tid, out, 'error' if 'Error' in out else 'success')


def download_file(tid, c, remote, local):
    """Shorthand for RemoteClient.download(). This function automatically handles
    the logging of events to the WebLogger

    Args:
        tid (string): id of the task running the command
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        remote (string): location of the file in remote server
        local (string): local location of the file to upload
    """
    out = c.download(remote, local)
    wlogger.log(tid, out, 'error' if 'Error' in out else 'success')


@celery.task(bind=True)
def setup_server(self, server_id, conffile):
    server = LDAPServer.query.get(server_id)
    tid = self.request.id
    if server.gluu_server:
        chdir = '/opt/gluu-server-'+server.gluu_version
    else:
        chdir = None

    wlogger.log(tid, "Connecting to the server %s" % server.hostname)
    c = RemoteClient(server.hostname)
    try:
        c.startup()
    except Exception as e:
        wlogger.log(tid, "Cannot establish SSH connection {0}".format(e),
                    "error")

    wlogger.log(tid, "Retrying with the IP address")
    c = RemoteClient(server.ip)
    try:
        c.startup()
    except Exception as e:
        wlogger.log(tid, "Cannot establish SSH connection {0}".format(e),
                    "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False

    # Premilinary checks for standalone servers with openldap installed
    if not server.gluu_server:
        # 1. Check OpenLDAP is installed
        if c.exists('/opt/symas/bin/slaptest'):
            wlogger.log(tid, 'Checking if OpenLDAP is installed', 'success')
        else:
            wlogger.log(tid, 'Cheking if OpenLDAP is installed', 'fail')
            wlogger.log(tid, 'Kindly install OpenLDAP on the server and '
                        ' refresh this page to try setup again.')
            return
        # 2. symas-openldap.conf file exists
        if c.exists('/opt/symas/etc/openldap/symas-openldap.conf'):
            wlogger.log(tid, 'Checking symas-openldap.conf exists', 'success')
        else:
            wlogger.log(tid, 'Checking if symas-openldap.conf exists', 'fail')
            wlogger.log(tid, 'Configure OpenLDAP with /opt/gluu/etc/openldap'
                        '/symas-openldap.conf', 'warning')
            return

        # 3. Certificates
        if server.tls_cacert:
            if c.exists(server.tls_cacert):
                wlogger.log(tid, 'Checking TLS CA Certificate', 'success')
            else:
                wlogger.log(tid, 'Checking TLS CA Certificate', 'fail')
        if server.tls_servercert:
            if c.exists(server.tls_servercert):
                wlogger.log(tid, 'Checking TLS Server Certificate', 'success')
            else:
                wlogger.log(tid, 'Checking TLS Server Certificate', 'fail')
        if server.tls_serverkey:
            if c.exists(server.tls_serverkey):
                wlogger.log(tid, 'Checking TLS Server Key', 'success')
            else:
                wlogger.log(tid, 'Checking TLS Server Key', 'fail')

    # 4. Check for existance of all the directories, create them if they don't
    wlogger.log(tid, "Checking existing data and schema folders for LDAP")
    conf = open(conffile, 'r')
    for line in conf:
        if re.match('^directory', line):
            folder = line.split()[1]
            if server.gluu_server:
                folder = os.path.join(chdir, folder)
            if not c.exists(folder):
                run_command(tid, c, 'mkdir -p '+folder, chdir)
            else:
                wlogger.log(tid, folder, 'success')

    # 5. Gluu Schema file will be present - Only for Standalone
    if not server.gluu_server:
        wlogger.log(tid, "Copying Gluu Schema files to the server")
        if not c.exists('/opt/gluu/schema/openldap'):
            run_command(tid, c, 'mkdir -p /opt/gluu/schema/openldap')
        gluu_schemas = os.listdir(os.path.join(app.static_folder, 'schema'))
        for schema in gluu_schemas:
            upload_file(tid, c,
                        os.path.join(app.static_folder, 'schema', schema),
                        "/opt/gluu/schema/openldap/"+schema)

    # 6. Copy User's custom schema files if any
    schemas = os.listdir(app.config['SCHEMA_DIR'])
    if len(schemas):
        wlogger.log(tid, "Copying custom schema files to the server")
        for schema in schemas:
            local = os.path.join(app.config['SCHEMA_DIR'], schema)
            remote = "/opt/gluu/schema/openldap/"+schema
            if chdir:
                remote = chdir+"/opt/gluu/schema/openldap/"+schema
            upload_file(tid, c, local, remote)

    # 7. Copy the slapd.conf
    wlogger.log(tid, "Copying slapd.conf file to the server")
    remote = "/opt/symas/etc/openldap/slapd.conf"
    if chdir:
        remote = chdir + "/opt/symas/etc/openldap/slapd.conf"
    upload_file(tid, c, conffile, remote)

    wlogger.log(tid, "Restarting LDAP server to validate slapd.conf")
    # IMPORTANT:
    # Restart allows the server to create the mdb files for accesslog so
    # slaptest doesn't throw errors during OLC generation
    run_command(tid, c, 'service solserver restart', chdir)

    # 8. Download openldap.crt to be used in other servers for ldaps
    if server.gluu_server or server.protocol == 'ldaps':
        wlogger.log(tid, "Downloading SSL Certificate to use in other servers")
        if server.gluu_server:
            remote = chdir + '/etc/certs/openldap.crt'
        else:
            remote = server.tls_servercert
        local = os.path.join(app.config["CERTS_DIR"],
                             "{0}.crt".format(server.hostname))
        download_file(tid, c, remote, local)

    # 9. Generate OLC slapd.d
    wlogger.log(tid, "Convert slapd.conf to slapd.d OLC")
    run_command(tid, c, 'service solserver stop', chdir)
    run_command(tid, c, "rm -rf /opt/symas/etc/openldap/slapd.d", chdir)
    run_command(tid, c, "mkdir /opt/symas/etc/openldap/slapd.d", chdir)
    run_command(tid, c, "/opt/symas/bin/slaptest -f /opt/symas/etc/openldap/"
                "slapd.conf -F /opt/symas/etc/openldap/slapd.d", chdir)

    # 10. Reset ownerships
    run_command(tid, c, "chown -R ldap:ldap /opt/gluu/data", chdir)
    run_command(tid, c, "chown -R ldap:ldap /opt/gluu/schema/openldap", chdir)
    run_command(tid, c, "chown -R ldap:ldap /opt/symas/etc/openldap/slapd.d",
                chdir)

    # 11. Restart the solserver with the new OLC configuration
    wlogger.log(tid, "Restarting LDAP server with OLC configuration")
    log = run_command(tid, c, "service solserver start", chdir)
    if 'failed' in log:
        wlogger.log(tid, "There seems to be some issue in starting the server."
                    "Running LDAP server in debug mode for troubleshooting")
        run_command(tid, c, "service solserver start -d 1", chdir)

    # Everything is done. Set the flag to based on the messages
    msgs = wlogger.get_messages(tid)
    setup_success = True
    for msg in msgs:
        setup_success = setup_success and msg['level'] != 'error'
    server.setup = setup_success
    db.session.commit()

######### MB

import time

@celery.task(bind=True)
def setupMmrServer(self, server_id):
    
    tid = self.request.id
    gluu = False
    server = LdapServer.query.get(server_id)
    
    if not server:
        wlogger.log(tid, "Server is not on database", "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False
    
    tid = self.request.id
    if server.gluu_version == "-1":
        chroot='/'
    else:
        chroot = '/opt/gluu-server-'+server.gluu_version
        gluu = True
   
    wlogger.log(tid, "Making SSH connection to the server %s" % server.fqn_hostname)
    c = RemoteClient(server.fqn_hostname)
    
    conn_addr = server.fqn_hostname
    
    try:
        c.startup()
    except Exception as e:
        wlogger.log(tid, "Cannot establish SSH connection {0}".format(e), "warning")
        
        wlogger.log(tid, "Retrying with the IP address")
        c = RemoteClient(server.ip_address)
        conn_addr = server.ip_address
        try:
            c.startup()
        except Exception as e:
            wlogger.log(tid, "Cannot establish SSH connection {0}".format(e), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
    if gluu:
        # check if remote is gluu server
        if c.exists(chroot):
            wlogger.log(tid, 'Checking if remote is gluu server', 'success')
        else:
            wlogger.log(tid, "Remote is not a gluu server.", "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
    

    # symas-openldap.conf file exists
    if c.exists(os.path.join(chroot, 'opt/symas/etc/openldap/symas-openldap.conf')):
        wlogger.log(tid, 'Checking symas-openldap.conf exists', 'success')
    else:
        wlogger.log(tid, 'Checking if symas-openldap.conf exists', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    # uplodading symas-openldap.conf file to remote server: enable openldap remote
    # access and make openldap sldapd.d
    confile = os.path.join(app.root_path, "templates", "slapd", "symas-openldap.conf")
    confile_content = open(confile).read()
    
    
    HOST_LIST='HOST_LIST="ldaps://127.0.0.1:1636/ ldaps://{0}:1636/"'.format(conn_addr)
    EXTRA_SLAPD_ARGS='EXTRA_SLAPD_ARGS="-F /opt/symas/etc/openldap/slapd.d"'
    SLAPD_GROUP=server.ldap_user
    SLAPD_USER=server.ldap_group
    
    confile_content = confile_content.format(**{'HOST_LIST': HOST_LIST, 
                                                'EXTRA_SLAPD_ARGS': EXTRA_SLAPD_ARGS,
                                                'SLAPD_GROUP':SLAPD_GROUP,
                                                'SLAPD_USER': SLAPD_USER,
                                                })
    
    r=c.putFile(os.path.join(chroot, 'opt/symas/etc/openldap/symas-openldap.conf'), confile_content)
    
    if r[0]:
        wlogger.log(tid, 'symas-openldap.conf file uploaded', 'success')
    else:
        wlogger.log(tid, 'An error occured while uploading symas-openldap.conf: {0}'.format(r[1], 'fail'))
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    accesslog_dir = '/opt/gluu/data/accesslog'

    # Generate OLC slapd.d
    wlogger.log(tid, "Convert slapd.conf to slapd.d OLC")
    run_command(tid, c, 'service solserver stop', chroot)
    run_command(tid, c, "rm -rf /opt/symas/etc/openldap/slapd.d", chroot)
    run_command(tid, c, "mkdir /opt/symas/etc/openldap/slapd.d", chroot)
    run_command(tid, c, "/opt/symas/bin/slaptest -f /opt/symas/etc/openldap/"
                "slapd.conf -F /opt/symas/etc/openldap/slapd.d", chroot)
    run_command(tid, c, "chown -R {0}.{1} /opt/symas/etc/openldap/slapd.d".format(server.ldap_user, server.ldap_group), chroot)

    if not c.exists(chroot+accesslog_dir):
        run_command(tid, c, "mkdir {0}".format(accesslog_dir), chroot)
        
    run_command(tid, c, "chown -R {0}.{1} {2}".format(server.ldap_user, server.ldap_group, accesslog_dir), chroot)


    # Restart the solserver with the new OLC configuration
    wlogger.log(tid, "Restarting LDAP server with OLC configuration")
    log = run_command(tid, c, "service solserver start", chroot)
    if 'failed' in log:
        wlogger.log(tid, "There seems to be some issue in restarting the server.", "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return
        
        # fix later !!!
        #            "Running LDAP server in debug mode for troubleshooting")
        #run_command(tid, c, "service solserver start -d 1", chdir)

    ldp = ldapOLC('ldaps://{}:1636'.format(conn_addr), 'cn=config', server.ldap_password)
    r=None
    try:
        r = ldp.connect()
    except Exception as e:
        wlogger.log(tid, "Connection to LDAPserver at port 1636 was failed: {0}".format(e), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    if not r:
        try:
            wlogger.log(tid, "Connection to LDAPserver at port 1636 was failed: {0}".format(ldp.conn.result['description']), "error")
        except:
            pass
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    wlogger.log(tid, 'Successfully connected to LDAPServer ', 'success')

    if ldp.setServerID(server.id):
        wlogger.log(tid, 'Setting Server ID {0}'.format(server.id), 'success')
    else:
        wlogger.log(tid, "Stting Server ID failed: {0}".format(ldp.conn.result['description']), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    if ldp.loadModules("syncprov", "accesslog"):
        wlogger.log(tid, 'Loading syncprov and accesslog', 'success')
    else:
        wlogger.log(tid, "Loading syncprov and accesslog failed: {0}".format(ldp.conn.result['description']), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    if ldp.accesslogDBEntry(accesslog_dir):
        wlogger.log(tid, 'Creating accesslog database entry', 'success')
    else:
        wlogger.log(tid, "Creating accesslog database entry failed: {0}".format(ldp.conn.result['description']), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    
    # !WARNING UNBIND NECASSARY - I DON'T KNOW WHY.*****
    ldp.conn.unbind()
    ldp.conn.bind()
    
    r=''
    r1=ldp.syncprovOverlaysDB2()
    
    if not r1: r += ldp.conn.result['description']
    
    r2=ldp.syncprovOverlaysDB1()
    if not r2: r += ' ' + ldp.conn.result['description']
    
    if not (r):
        wlogger.log(tid, 'Creating syncprovOverlays entries', 'success')
    else:
        wlogger.log(tid, "Creating syncprovOverlays entries failed: {0}".format(r), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    
    if ldp.accesslogPurge():
        wlogger.log(tid, 'Creating accesslog purge entry', 'success')
    else:
        wlogger.log(tid, "Creating accesslog purge entry failed: {0}".format(ldp.conn.result['description']), "warning")
    
    if ldp.setLimitOnMainDb():
        wlogger.log(tid, 'Setting size limit on main database for replicator user', 'success')
    else:
        wlogger.log(tid, "Setting size limit on main database for replicator user failed: {0}".format(ldp.conn.result['description']), "warning")


    #Fix Me: For non-gluu symas ldapserveri there is no o=gluu base, can't add replicator user.
    # create replicator user
    adminOlc = ldapOLC('ldaps://{}:1636'.format(conn_addr), 'cn=directory manager,o=gluu', server.ldap_password)
    r=None
    try:
        r = adminOlc.connect()
    except Exception as e:
        wlogger.log(tid, "Connection to LDAPserver as direcory manager at port 1636 was failed: {0}".format(e), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    
    wlogger.log(tid, 'Creating replicator user: cn=replicator@{0},o=gluu'.format(server.fqn_hostname))
    
    if not adminOlc.addReplicatorUser(server.replicator_password):
        if adminOlc.conn.result['description']=='entryAlreadyExists':
            
            wlogger.log(tid, 'Replicator user already exists', 'success')
            
            if adminOlc.changeReplicationUserPassword(server.replicator_password):
                wlogger.log(tid, 'Replicator password changed', 'success')
            else:
                wlogger.log(tid, 'Chaning replicator password failed', 'warning')  
        else:
            
            wlogger.log(tid, "Creating replicator user failed: {0}".format(adminOlc.conn.result['description']), "warning")
            wlogger.log(tid, "Ending server setup process.", "error")
            return
    else:
        wlogger.log(tid, 'Replicator user cn=replicator@{0},o=gluu created'.format(server.fqn_hostname), 'success')
       
            
            
            #Fix Me: if replicator user exists, paswword need to be changed.
    

    #Adding providers
    providers = MultiMaster.query.filter(MultiMaster.mmr_id != server.id).filter(MultiMaster.replicator==True).all()
    
    for p in providers:

        serverp = LdapServer.query.get( p.mmr_id )
        ldpp = ldapOLC('ldaps://{}:1636'.format(serverp.fqn_hostname), "cn=config", serverp.ldap_password)
        r=None
        try:
            wlogger.log(tid, "Connecting to LDAP Server {0}".format(serverp.fqn_hostname))
            r = ldpp.connect()
        except Exception as e:
             #wlogger.log(tid, "Connection to LDAPserver {0} at port 1636 was failed: {1}".format(serverp.fqn_hostname, e), "warning")
            wlogger.log(tid, "Conection failed", "warning")
        if not r:
            wlogger.log(tid, "LDAPserver {0} was not added as provider".format(serverp.fqn_hostname), "warning")

        else:
            serverStatus = ldpp.getMMRStatus()
        
            #checking only server_id and access log db, further checks may be required
            if serverStatus["server_id"] and serverStatus["accesslogDB"]:
        
                if ldp.addProvider(serverp.id, "ldaps://{0}:1636".format(serverp.fqn_hostname), "cn=replicator@{0},o=gluu".format(serverp.fqn_hostname), serverp.replicator_password):
                    wlogger.log(tid, 'Adding provider {0}'.format(serverp.fqn_hostname), 'success')
                else:
                    wlogger.log(tid, 'Adding provider {0} failed: {1}'.format(serverp.fqn_hostname, ldp.conn.result['description']), "warning")
            else:
                wlogger.log(tid, "LDAPserver {0} does not seem to be a valid provider, not added.".format(serverp.fqn_hostname), "warning")
    
    if providers:
        if ldp.makeMirroMode():
            wlogger.log(tid, 'Enabling mirror mode', 'success')
        else:
            wlogger.log(tid, "Enabling mirror mode failed: {0}".format(ldp.conn.result['description']), "warning")
   
    wlogger.log(tid, "Deployment is successful")
   
    #FIX ME: Add current ldap server as a provider to previously deployed servers.



@celery.task(bind=True)
def removeMultiMasterReplicator(self, server_id):
    tid = self.request.id
    server = LdapServer.query.get(server_id)

    wlogger.log(tid, "Removing Master")

    ldapc=Provider.query.filter_by(consumer_id=server_id).all()
    for c in ldapc:
        db.session.delete(c)

    mmrs=MultiMaster.query.filter_by(mmr_id=server_id).first()
    db.session.delete(mmrs)
    db.session.commit()

@celery.task(bind=True)
def removeMultiMasterDeployement(self, server_id):

    server = LdapServer.query.get(server_id)
    tid = self.request.id
    if server.gluu_version == "-1":
        chroot = '/'
    else:
        chroot = '/opt/gluu-server-'+server.gluu_version
   
    wlogger.log(tid, "Making SSH connection to the server %s" % server.fqn_hostname)
    c = RemoteClient(server.fqn_hostname)
    
    conn_addr = server.fqn_hostname
    
    try:
        c.startup()
    except Exception as e:
        wlogger.log(tid, "Cannot establish SSH connection {0}".format(e), "warning")
        
        wlogger.log(tid, "Retrying with the IP address")
        c = RemoteClient(server.ip_address)
        conn_addr = server.ip_address
        try:
            c.startup()
        except Exception as e:
            wlogger.log(tid, "Cannot establish SSH connection {0}".format(e), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
    if server.gluu_version != "-1":
        # check if remote is gluu server
        if c.exists(chroot):
            wlogger.log(tid, 'Checking if remote is gluu server', 'success')
        else:
            wlogger.log(tid, "Remote is not a gluu server.", "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
    

    # symas-openldap.conf file exists
    if c.exists(os.path.join(chroot, 'opt/symas/etc/openldap/symas-openldap.conf')):
        wlogger.log(tid, 'Checking symas-openldap.conf exists', 'success')
    else:
        wlogger.log(tid, 'Checking if symas-openldap.conf exists', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    # sldapd.conf file exists
    if c.exists(os.path.join(chroot, 'opt/symas/etc/openldap/slapd.conf')):
        wlogger.log(tid, 'Checking slapd.conf exists', 'success')
    else:
        wlogger.log(tid, 'Checking if slapd.conf exists', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return


    # uplodading symas-openldap.conf file
    confile = os.path.join(app.root_path, "templates", "slapd", "symas-openldap.conf")
    confile_content = open(confile).read()
    
    
    HOST_LIST='HOST_LIST="ldaps://127.0.0.1:1636/"'
    EXTRA_SLAPD_ARGS='EXTRA_SLAPD_ARGS=""'
    
    SLAPD_GROUP=server.ldap_user
    SLAPD_USER=server.ldap_group
    
    confile_content = confile_content.format(**{'HOST_LIST': HOST_LIST, 
                                                'EXTRA_SLAPD_ARGS': EXTRA_SLAPD_ARGS,
                                                'SLAPD_GROUP':SLAPD_GROUP,
                                                'SLAPD_USER': SLAPD_USER,
                                                })

    r=c.putFile(os.path.join(chroot, 'opt/symas/etc/openldap/symas-openldap.conf'), confile_content)
    
    if r[0]:
        wlogger.log(tid, 'symas-openldap.conf file uploaded', 'success')
    else:
        wlogger.log(tid, 'An error occured while uploading symas-openldap.conf: {0}'.format(r[1], 'fail'))
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    run_command(tid, c, "chown -R {0}.{1} /opt/symas/etc/openldap".format(server.ldap_user, server.ldap_group), chroot)

    # Restart the solserver with slapd.conf configuration
    wlogger.log(tid, "Restarting LDAP server with slapd.conf configuration")
    log = run_command(tid, c, "service solserver restart", chroot)
    if 'failed' in log:
        wlogger.log(tid, "There seems to be some issue in restarting the server.", "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    wlogger.log(tid, 'Deployment of Ldap Server was successfully removed')
    return True

@celery.task(bind=True)
def InstallLdapServer(self, ldap_info):
    tid = self.request.id
   
    wlogger.log(tid, "Making SSH connection to the server %s" % ldap_info['fqn_hostname'])
    c = RemoteClient(ldap_info['fqn_hostname'])
    
    conn_addr = ldap_info['fqn_hostname']
    
    try:
        c.startup()
    except Exception as e:
        wlogger.log(tid, "Cannot establish SSH connection {0}".format(e), "warning")
        
        wlogger.log(tid, "Retrying with the IP address")
        c = RemoteClient(ldap_info['ip_address'])
        conn_addr = ldap_info['ip_address']
        try:
            c.startup()
        except Exception as e:
            wlogger.log(tid, "Cannot establish SSH connection {0}".format(e), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False

    # check if debian clone
    if c.exists('/usr/bin/dpkg'):
        wlogger.log(tid, 'Checking if /usr/bin/dpkg exists', 'success')
    else:
        wlogger.log(tid, '/usr/bin/dpkg nout found on this server', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    
    wlogger.log(tid, "Downloading and installing Symas Open-Ldap Server")
    cmd = "wget http://104.237.133.194/pkg/GLUU/UB14/symas-openldap-gluu.amd64_2.4.45-2_amd64.deb -O /tmp/symas-openldap-gluu.amd64_2.4.45-2_amd64.deb"
    cin, cout, cerr = c.run(cmd)

    if "‘/tmp/symas-openldap-gluu.amd64_2.4.45-2_amd64.deb’ saved" in cerr:
        wlogger.log(tid, 'Symas open-ldap package downloaded.', 'success')
    else:
        wlogger.log(tid, 'Downloading Symas open-ldap package failed', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    
    cmd = "dpkg -i /tmp/symas-openldap-gluu.amd64_2.4.45-2_amd64.deb"
    cin, cout, cerr = c.run(cmd)

    if "Setting up symas-openldap-gluu" in cout:
        wlogger.log(tid, 'Symas open-ldap package installed.', 'success')
    else:
        wlogger.log(tid, 'Installing Symas open-ldap package failed', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    
    
    wlogger.log(tid, "Creating ldap user and group")
        
    
    cmd = "adduser --system --no-create-home --group ldap"
    cin, cout, cerr = c.run(cmd)
    if not "Adding system user" in cout:
        wlogger.log(tid, "Can not add ldap user: {0}".format(cout.strip()), "warning")
        if not "already exists. Exiting" in cout:
            wlogger.log(tid, 'Creating ldap user failed', 'fail')
            wlogger.log(tid, "Ending server setup process.", "error")
            return
    
    wlogger.log(tid, "Uploading config file and gluu schemas")
    
    cmd="mkdir -p /opt/gluu/schema/openldap/"
    c.run(cmd)
    if not c.exists('/opt/gluu/schema/openldap/'):
        wlogger.log(tid, 'Creating "/opt/gluu/schema/openldap/" failed', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    
    wlogger.log(tid, 'Directory "/opt/gluu/schema/openldap/" created', 'success')

    custom_schema_file = os.path.join(app.root_path, "templates", "slapd", "schema", "custom.schema")
    gluu_schema_file = os.path.join(app.root_path, "templates", "slapd", "schema", "gluu.schema") 
    r1=c.upload(custom_schema_file, "/opt/gluu/schema/openldap/custom.schema")
    r2=c.upload(gluu_schema_file, "/opt/gluu/schema/openldap/gluu.schema")
    err=''
    if not 'Upload successful.' in r1: err +=r1
    if not 'Upload successful.' in r2: err +=r2
    if err:
        wlogger.log(tid, 'Uploading Gluu schema files failed: {0}'.format(err), 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    wlogger.log(tid, 'Gluu schema files uploaded', 'success')
    
    gluu_slapd_conf_file = os.path.join(app.root_path, "templates", "slapd", "slapd.conf.gluu")
    gluu_slapd_conf_file_content = open(gluu_slapd_conf_file).read()
    
    hashpw = makeLdapPassword(ldap_info["ldap_password"])
    
    gluu_slapd_conf_file_content = gluu_slapd_conf_file_content.replace("{#ROOTPW#}", hashpw)
    
        
    r=c.putFile("/opt/symas/etc/openldap/slapd.conf", gluu_slapd_conf_file_content)
    
    if r[0]:
        wlogger.log(tid, 'slapd.conf file uploaded', 'success')
    else:
        wlogger.log(tid, 'An error occured while uploading slapd.conf.conf: {0}'.format(r[1], 'fail'))
        wlogger.log(tid, "Ending server setup process.", "error")
        return
        

    wlogger.log(tid, 'Gluu slapd.conf file uploaded', 'success')
    

    cmd="mkdir -p /opt/gluu/data/main_db"
    c.run(cmd)
    if not c.exists('/opt/gluu/data/main_db'):
        wlogger.log(tid, 'Creating "/opt/gluu/data/main_db" failed', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    cmd="mkdir -p /opt/gluu/data/site_db"
    c.run(cmd)
    if not c.exists('/opt/gluu/data/site_db'):
        wlogger.log(tid, 'Creating "/opt/gluu/data/site_db" failed', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return

        
    wlogger.log(tid, 'Directories "/opt/gluu/data/main_db" and "/opt/gluu/data/site_db" were created', 'success')
    
    run_command(tid, c, "chown -R {0}.{1} /opt/gluu/data/".format(ldap_info["ldap_user"], ldap_info["ldap_group"]))
    
    run_command(tid, c, "mkdir -p /var/symas/run/")
    
    run_command(tid, c, "chown -R {0}.{1} /var/symas".format(ldap_info["ldap_user"], ldap_info["ldap_group"]))
    
    run_command(tid, c, "mkdir -p /etc/certs/")
    
    
    wlogger.log(tid, "Generating Certificate")
    cmd="/usr/bin/openssl genrsa -des3 -out /etc/certs/openldap.key.orig -passout pass:{0} 2048".format(ldap_info["ldap_password"])
    
    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    wlogger.log(tid, cin+cout+cerr, "debug")
    

    cmd="/usr/bin/openssl rsa -in /etc/certs/openldap.key.orig -passin pass:{0} -out /etc/certs/openldap.key".format(ldap_info["ldap_password"])
    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    wlogger.log(tid, cin+cout+cerr, "debug")


    subj = '/C={0}/ST={1}/L={2}/O={3}/CN={4}/emailAddress={5}'.format(ldap_info['countryCode'], 
                                                                      ldap_info['state'],
                                                                      ldap_info['city'],
                                                                      ldap_info['orgName'] ,
                                                                      ldap_info['fqn_hostname'],
                                                                      ldap_info['admin_email'])
    
    cmd = '/usr/bin/openssl req -new -key /etc/certs/openldap.key -out /etc/certs/openldap.csr -subj {0}'.format(subj)

    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    if cout.strip()+cerr.strip():
        wlogger.log(tid, cin+cout+cerr, "debug")
    
    cmd="/usr/bin/openssl x509 -req -days 365 -in /etc/certs/openldap.csr -signkey /etc/certs/openldap.key -out /etc/certs/openldap.crt"
    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    wlogger.log(tid, cin+cout+cerr, "debug")
    
    cmd="cat /etc/certs/openldap.crt >> /etc/certs/openldap.pem && cat /etc/certs/openldap.key >> /etc/certs/openldap.pem"
    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    if cout.strip()+cerr.strip():
        wlogger.log(tid, cin+cout+cerr, "debug")

    run_command(tid, c, "chown -R {0}.{1} /etc/certs".format(ldap_info["ldap_user"], ldap_info["ldap_group"]))
    
    # uplodading symas-openldap.conf file
    confile = os.path.join(app.root_path, "templates", "slapd", "symas-openldap.conf")
    confile_content = open(confile).read()
    
    
    HOST_LIST='HOST_LIST="ldaps://127.0.0.1:1636/"'
    EXTRA_SLAPD_ARGS='EXTRA_SLAPD_ARGS=""'
    
    SLAPD_GROUP=ldap_info["ldap_user"]
    SLAPD_USER=ldap_info["ldap_group"]
    
    confile_content = confile_content.format(**{'HOST_LIST': HOST_LIST, 
                                                'EXTRA_SLAPD_ARGS': EXTRA_SLAPD_ARGS,
                                                'SLAPD_GROUP':SLAPD_GROUP,
                                                'SLAPD_USER': SLAPD_USER,
                                                })

    r=c.putFile('/opt/symas/etc/openldap/symas-openldap.conf', confile_content)
    
    if r[0]:
        wlogger.log(tid, 'symas-openldap.conf file uploaded', 'success')
    else:
        wlogger.log(tid, 'An error occured while uploading symas-openldap.conf: {0}'.format(r[1], 'fail'))
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    
    wlogger.log(tid, "Satring Symas Open-Ldap Server")
    log = run_command(tid, c, "service solserver restart")
    if 'failed' in log:
        wlogger.log(tid, "There seems to be some issue in restarting the server.", "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return
  
    ldps=LdapServer()
    ldps.gluu_version = "-1"
    ldps.fqn_hostname=ldap_info["fqn_hostname"]
    ldps.ip_address=ldap_info["ip_address"]
    ldps.ldap_password=ldap_info["ldap_password"]
    ldps.replicator_password = ldap_info["replicator_password"]
    ldps.ldap_user="ldap"
    ldps.ldap_group="ldap"
    db.session.add(ldps)
    db.session.commit()
    
