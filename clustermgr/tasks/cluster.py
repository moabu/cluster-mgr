# -*- coding: utf-8 -*-

import os
import re
import StringIO
import time

from flask import current_app as app
from flask import flash

from clustermgr.models import Server, AppConfiguration
from clustermgr.extensions import celery, wlogger, db
from clustermgr.core.remote import RemoteClient
from clustermgr.core.ldap_functions import LdapOLC
from clustermgr.core.olc import CnManager
from clustermgr.core.utils import ldap_encode
from clustermgr.config import Config
import uuid

def run_command(tid, c, command, container=None, no_error='error'):
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
    if container == '/':
        container = None
    if container:
        command = 'chroot {0} /bin/bash -c "{1}"'.format(container,
                                                         command)

    wlogger.log(tid, command, "debug")
    cin, cout, cerr = c.run(command)
    output = ''
    if cout:
        wlogger.log(tid, cout, "debug")
        output += "\n" + cout
    if cerr:
        # For some reason slaptest decides to send success message as err, so
        if 'config file testing succeeded' in cerr:
            wlogger.log(tid, cerr, "success")
        else:
            wlogger.log(tid, cerr, no_error)
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
    """Shorthand for RemoteClient.download(). This function automatically
     handles the logging of events to the WebLogger

    Args:
        tid (string): id of the task running the command
        c (:object:`clustermgr.core.remote.RemoteClient`): client to be used
            for the SSH communication
        remote (string): location of the file in remote server
        local (string): local location of the file to upload
    """
    out = c.download(remote, local)
    wlogger.log(tid, out, 'error' if 'Error' in out else 'success')



def modifyOxLdapProperties(server, c, tid, pDict, chroot):
    
    remote_file = os.path.join(chroot, 'etc/gluu/conf/ox-ldap.properties')

    ox_ldap=c.get_file(remote_file)
    
    temp = None
    
    if ox_ldap[0]:
        fc = ''
        for l in ox_ldap[1]:
            if l.startswith('servers:'):
                l='servers: {0}\n'.format( pDict[server.hostname] )
            fc += l

        r = c.put_file(remote_file,fc)

        if r[0]:
            wlogger.log(tid, 
                'ox-ldap.properties file on {0} modified to include all providers'.format(server.hostname), 
                'success')
        else:
            temp = r[1]
    else:
        temp = ox_ldap[1]
        
    if temp:
        wlogger.log(tid, 
                'ox-ldap.properties file on {0} was not modified to '
                'include all providers: {1}'.format(server.hostname, temp), 
                'warning')
        
@celery.task(bind=True)
def setup_ldap_replication(self, server_id):
    tid = self.request.id
    server = Server.query.get(server_id)
    conn_addr = server.hostname
    app_config = AppConfiguration.query.first()

    
    # 1. Ensure that the server id is valid
    if not server:
        wlogger.log(tid, "Server is not on database", "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False

    if not server.gluu_server:
        chroot = '/'
    else:
        chroot = '/opt/gluu-server-' + app_config.gluu_version
    
    # 2. Make SSH Connection to the remote server
    wlogger.log(tid, "Making SSH connection to the server %s" %
                server.hostname)
    c = RemoteClient(server.hostname, ip=server.ip)
    try:
        c.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection {0}".format(e), "warning")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False


    # 3. For Gluu server, ensure that chroot directory is available
    if server.gluu_server:
        if c.exists(chroot):
            wlogger.log(tid, 'Checking if remote is gluu server', 'success')
        else:
            wlogger.log(tid, "Remote is not a gluu server.", "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False

    # 3.1 Ensure the data directories are available
    accesslog_dir = '/opt/gluu/data/accesslog'
    if not c.exists(chroot + accesslog_dir):
        run_command(tid, c, "mkdir -p {0}".format(accesslog_dir), chroot)
        run_command(tid, c, "chown -R ldap:ldap {0}".format(accesslog_dir),
                    chroot)

    # 4. Ensure Openldap is installed on the server
    if c.exists(os.path.join(chroot, 'opt/symas/bin/slaptest')):
        wlogger.log(tid, "Checking OpenLDAP is installed", "success")
    else:
        wlogger.log(tid, "Cannot find directory /opt/symas/bin. OpenLDAP is "
                         "not installed. Cannot setup replication.", "error")
        return False

    # 5. Upload symas-openldap.conf with remote access and slapd.d enabled
    syconf = os.path.join(chroot, 'opt/symas/etc/openldap/symas-openldap.conf')
    confile = os.path.join(app.root_path, "templates", "slapd",
                           "symas-openldap.conf")
                           
    ldap_bind_addr = server.hostname
    if app_config.use_ip:
        ldap_bind_addr = server.ip
    

    values = dict(
        hosts="ldaps://127.0.0.1:1636/ ldaps://{0}:1636/".format(ldap_bind_addr),
        extra_args="-F /opt/symas/etc/openldap/slapd.d"
    )

    confile_content = open(confile).read()
    confile_content = confile_content.format(**values)

    r = c.put_file(syconf, confile_content)

    if r[0]:
        wlogger.log(tid, 'symas-openldap.conf file uploaded', 'success')
    else:
        wlogger.log(tid, 'An error occured while uploading symas-openldap.conf'
                    ': {0}'.format(r[1]), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    # 6. Generate OLC slapd.d
    wlogger.log(tid, "Convert slapd.conf to slapd.d OLC")
    
    if server.os == 'CentOS 7' or server.os == 'RHEL 7':
        run_command(tid, c, "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost 'service solserver stop'")
    else:
        run_command(tid, c, 'service solserver stop', chroot)
    run_command(tid, c, "rm -rf /opt/symas/etc/openldap/slapd.d", chroot)
    run_command(tid, c, "mkdir -p /opt/symas/etc/openldap/slapd.d", chroot)
    run_command(tid, c, "/opt/symas/bin/slaptest -f /opt/symas/etc/openldap/"
                "slapd.conf -F /opt/symas/etc/openldap/slapd.d", chroot)
    run_command(tid, c,
                "chown -R ldap:ldap /opt/symas/etc/openldap/slapd.d", chroot)

    # 7. Restart the solserver with the new OLC configuration
    wlogger.log(tid, "Restarting LDAP server with OLC configuration")

    if server.os == 'CentOS 7' or server.os == 'RHEL 7':
        log= run_command(tid, c, "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost 'service solserver start'")
    else:
        log = run_command(tid, c, "service solserver start", chroot)
    if 'failed' in log:
        wlogger.log(tid, "Couldn't restart solserver.", "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        
        if 'CentOS' in server.os or 'RHEL' in server.os:
            run_command(tid, c, "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost 'service solserver start -d 1'")
        else:
            run_command(tid, c, "service solserver start -d 1", chroot)
        return

    # 8. Connect to the OLC config
    ldp = LdapOLC('ldaps://{}:1636'.format(conn_addr), 'cn=config',
                  server.ldap_password)
    try:
        ldp.connect()
        wlogger.log(tid, 'Successfully connected to LDAPServer ', 'success')
    except Exception as e:
        wlogger.log(tid, "Connection to LDAPserver {0} at port 1636 was failed:"
                    " {1}".format(conn_addr, e), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    # 9. Set the server ID
    if ldp.setServerID(server.id):
        wlogger.log(tid, 'Setting Server ID: {0}'.format(server.id), 'success')
    else:
        wlogger.log(tid, "Stting Server ID failed: {0}".format(
            ldp.conn.result['description']), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    # 10. Enable the syncprov and accesslog modules
    r = ldp.loadModules("syncprov", "accesslog")
    if r == -1:
        wlogger.log(
            tid, 'Syncprov and accesslog modlues already exist', 'debug')
    else:
        if r:
            wlogger.log(
                tid, 'Syncprov and accesslog modlues were loaded', 'success')
        else:
            wlogger.log(tid, "Loading syncprov & accesslog failed: {0}".format(
                ldp.conn.result['description']), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return

    if not ldp.checkAccesslogDBEntry():
        if ldp.accesslogDBEntry(app_config.replication_dn, accesslog_dir):
            wlogger.log(tid, 'Creating accesslog entry', 'success')
        else:
            wlogger.log(tid, "Creating accesslog entry failed: {0}".format(
                ldp.conn.result['description']), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return
    else:
        wlogger.log(tid, 'Accesslog entry already exists.', 'debug')

    # !WARNING UNBIND NECASSARY - I DON'T KNOW WHY.*****
    ldp.conn.unbind()
    ldp.conn.bind()

    if not ldp.checkSyncprovOverlaysDB1():
        if ldp.syncprovOverlaysDB1():
            wlogger.log(
                tid, 'SyncprovOverlays entry on main database was created',
                'success')
        else:
            wlogger.log(
                tid, "Creating SyncprovOverlays entry on main database failed:"
                " {0}".format(ldp.conn.result['description']), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return
    else:
        wlogger.log(
            tid, 'SyncprovOverlays entry on main database already exists.',
            'debug')

    if not ldp.checkSyncprovOverlaysDB2():
        if ldp.syncprovOverlaysDB2():
            wlogger.log(
                tid, 'SyncprovOverlay entry on accasslog database was created',
                'success')
        else:
            wlogger.log(
                tid, "Creating SyncprovOverlays entry on accasslog database"
                " failed: {0}".format(ldp.conn.result['description']), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return
    else:
        wlogger.log(
            tid, 'SyncprovOverlay entry on accasslog database already exists.',
            'debug')

    if not ldp.checkAccesslogPurge():
        if ldp.accesslogPurge(app_config.log_purge):
            wlogger.log(tid, 'Creating accesslog purge entry', 'success')
        else:
            wlogger.log(tid, "Creating accesslog purge entry failed: {0}".format(
                ldp.conn.result['description']), "warning")

    else:
        wlogger.log(tid, 'Accesslog purge entry already exists.', 'debug')

    if ldp.setLimitOnMainDb(app_config.replication_dn):
        wlogger.log(
            tid, 'Setting size limit on main database for replicator user',
            'success')
    else:
        wlogger.log(tid, "Setting size limit on main database for replicator"
                    " user failed: {0}".format(ldp.conn.result['description']),
                    "warning")


    if server.primary_server:
        # 11. Add replication user to the o=gluu
        wlogger.log(tid, 'Creating replicator user: {0}'.format(
            app_config.replication_dn))

        adminOlc = LdapOLC('ldaps://{}:1636'.format(conn_addr),
                           'cn=directory manager,o=gluu', server.ldap_password)
        try:
            adminOlc.connect()
        except Exception as e:
            wlogger.log(
                tid, "Connection to LDAPserver as direcory manager at port 1636"
                " has failed: {0}".format(e), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return

        if adminOlc.addReplicatorUser(app_config.replication_dn,
                                      app_config.replication_pw):
            wlogger.log(tid, 'Replicator user created.', 'success')
        else:
            wlogger.log(tid, "Creating replicator user failed: {0}".format(
                adminOlc.conn.result), "warning")
            wlogger.log(tid, "Ending server setup process.", "error")
            return

    saddr = server.ip if app_config.use_ip else server.hostname


    # Prepare pDict for modifying ox-ldap.properties file.
    allproviders = Server.query.all()
    pDict = {}
    oxIDP=['localhost:1636']
    
    for ri in allproviders:
        
        laddr = ri.ip if app_config.use_ip else ri.hostname
        oxIDP.append(laddr+':1636')
        
        ox_auth = [ laddr+':1636' ]

        for rj in  allproviders:
            if not ri == rj:
                laddr = rj.ip if app_config.use_ip else rj.hostname
                ox_auth.append(laddr+':1636')

        pDict[ri.hostname]= ','.join(ox_auth)


    if server.primary_server:
        if adminOlc.configureOxIDPAuthentication(oxIDP):
            wlogger.log(tid, 'oxIDPAuthentication entry is modified to include all privders','success')
        else:
            wlogger.log(tid, 'Modifying oxIDPAuthentication entry is failed: {}'.format(
                    adminOlc.conn.result['description']), 'success')


    modifyOxLdapProperties(server, c, tid, pDict, chroot)
    

    # 12. Make this server to listen to all other providers
    
    if server.os == 'CentOS 7' or server.os == 'RHEL 7':
        restart_gluu_cmd = '/sbin/gluu-serverd-{0} restart'.format(app_config.gluu_version)
    else:
        restart_gluu_cmd = 'service gluu-server-{0} restart'.format(app_config.gluu_version)
    
    providers = Server.query.filter(Server.id.isnot(server.id)).filter().all()
    
    if providers:
        wlogger.log(tid, "Adding Syncrepl to integrate the server in cluster")
    for p in providers:

        paddr = p.ip if app_config.use_ip else p.hostname
        
        if not server.primary_server:
        
            status = ldp.add_provider(
                p.id, "ldaps://{0}:1636".format(paddr), app_config.replication_dn,
                app_config.replication_pw)
            if status:
                wlogger.log(tid, '>> Making LDAP of {0} listen to {1}'.format(
                    server.hostname, p.hostname), 'success')
            else:
                wlogger.log(tid, '>> Making {0} listen to {1} failed: {2}'.format(
                    p.hostname, server.hostname, ldp.conn.result['description']),
                    "warning")

            """
            # 13. Make the other server listen to this server
            other = LdapOLC('ldaps://{}:1636'.format(paddr), "cn=config",
                            p.ldap_password)
            try:
                other.connect()
            except Exception as e:
                wlogger.log("Couldn't connect to {0}. It will not be listening"
                            " to {1} for changes.".format(
                                p.hostname, server.hostname), "warning")
                continue
            status = other.add_provider(server.id,
                                        "ldaps://{0}:1636".format(saddr),
                                        app_config.replication_dn,
                                        app_config.replication_pw)
            if status:
                wlogger.log(tid, '<< Making LDAP of {0} listen to {1}'.format(
                    p.hostname, server.hostname), 'success')
            else:
                wlogger.log(tid, '<< Making {0} listen to {1} failed: {2}'.format(
                    p.hostname, server.hostname, ldp.conn.result['description']),
                    "warning")
            """
        # Special case - if there are only two server enable mirror mode
        # in other server as well
        #if len(providers) == 1:
        #    other.makeMirroMode()
        #other.conn.unbind()


        pc = RemoteClient(p.hostname, ip=p.ip)
        try:
            pc.startup()
        except:
            pc = None
            wlogger.log(tid, "Can't establish SSH connection to provider server: ".format(p.hostname), 'fail')
            #wlogger.log(tid, "Ending server installation process.", "error")

            return
        
        modifyOxLdapProperties(p, pc, tid, pDict, chroot)
        

        wlogger.log(tid, 'Restarting Gluu Server on provider {0}'.format(p.hostname))
        wlogger.log(tid, "SSH connection to provider server: {0}".format(p.hostname), 'success')
        
        if pc:
            run_command(tid, pc, restart_gluu_cmd, no_error='debug')

    if not server.primary_server:
        # 15. Enable Mirrormode in the server
        if providers:
            if not ldp.checkMirroMode():
                if ldp.makeMirroMode():
                    wlogger.log(tid, 'Enabling mirror mode', 'success')
                else:
                    wlogger.log(tid, "Enabling mirror mode failed: {0}".format(
                        ldp.conn.result['description']), "warning")
            else:
                wlogger.log(tid, 'LDAP Server is already in mirror mode', 'debug')

    
    wlogger.log(tid, 'Restarting Gluu Server')
    run_command(tid, c, restart_gluu_cmd, no_error='debug')

    # 16. Set the mmr flag to True to indicate it has been configured
    server.mmr = True
    db.session.commit()

    wlogger.log(tid, "Deployment is successful")


@celery.task
def remove_provider(server_id):
    """Task to remove the syncrepl config of the given server from all other
    servers in the LDAP cluster.
    """
    appconfig = AppConfiguration.query.first()
    server = Server.query.get(server_id)
    receivers = Server.query.filter(Server.id.isnot(server_id)).all()
    for receiver in receivers:
        addr = receiver.ip if appconfig.use_ip else receiver.hostname
        c = CnManager(addr, 1636, True, 'cn=config', receiver.ldap_password)
        c.remove_olcsyncrepl(server_id)
        c.close()
        # TODO monitor for failures and report or log it somewhere

    # may have more than one provider - MB
    # rewrite the symas-openldap.conf to make it listen localhost only
    #c = RemoteClient(server.hostname, ip=server.ip)
    #c.startup()
    #values = dict(
    #    hosts="ldaps://127.0.0.1:1636/ ldaps://{0}:1636/".format(server.ip),
    #    extra_args="-F /opt/symas/etc/openldap/slapd.d"
    #)

    #chroot = "/opt/gluu-server-" + appconfig.gluu_version if server.gluu_server \
    #    else None
    #syconf = os.path.join(chroot,
    #                      '/opt/symas/etc/openldap/symas-openldap.conf')
    #confile = os.path.join(app.root_path, "templates", "slapd",
    #                       "symas-openldap.conf")
    #confile_content = open(confile).read()
    #confile_content = confile_content.format(**values)
    #c.put_file(syconf, confile_content)
    #c.close()




@celery.task(bind=True)
def InstallLdapServer(self, ldap_info):
    tid = self.request.id

    wlogger.log(tid, "Making SSH connection to the server %s" %
                ldap_info['fqn_hostname'])
    c = RemoteClient(ldap_info['fqn_hostname'], ip=ldap_info['ip_address'])

    try:
        c.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection {0}".format(e), "warning")
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
    if "Adding system user" not in cout:
        wlogger.log(tid, "Can not add ldap user: {0}".format(
            cout.strip()), "warning")
        if "already exists. Exiting" not in cout:
            wlogger.log(tid, 'Creating ldap user failed', 'fail')
            wlogger.log(tid, "Ending server setup process.", "error")
            return

    wlogger.log(tid, "Uploading config file and gluu schemas")

    cmd = "mkdir -p /opt/gluu/schema/openldap/"
    c.run(cmd)
    if not c.exists('/opt/gluu/schema/openldap/'):
        wlogger.log(tid, 'Creating "/opt/gluu/schema/openldap/" failed',
                    'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    custom_schema_file = os.path.join(app.root_path, "templates",
                                      "slapd", "schema", "custom.schema")
    gluu_schema_file = os.path.join(
        app.root_path, "templates", "slapd", "schema", "gluu.schema")
    r1 = c.upload(custom_schema_file,
                  "/opt/gluu/schema/openldap/custom.schema")
    r2 = c.upload(gluu_schema_file, "/opt/gluu/schema/openldap/gluu.schema")
    err = ''
    if 'Upload successful.' not in r1:
        err += r1
    if 'Upload successful.' not in r2:
        err += r2
    if err:
        wlogger.log(
            tid, 'Uploading Gluu schema files failed: {0}'.format(err), 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return
    wlogger.log(tid, 'Gluu schema files uploaded', 'success')

    gluu_slapd_conf_file = os.path.join(
        app.root_path, "templates", "slapd", "slapd.conf.gluu")
    gluu_slapd_conf_file_content = open(gluu_slapd_conf_file).read()

    hashpw = ldap_encode(ldap_info["ldap_password"])

    gluu_slapd_conf_file_content = gluu_slapd_conf_file_content.replace(
        "{#ROOTPW#}", hashpw)

    r = c.put_file("/opt/symas/etc/openldap/slapd.conf",
                   gluu_slapd_conf_file_content)

    if r[0]:
        wlogger.log(tid, 'slapd.conf file uploaded', 'success')
    else:
        wlogger.log(tid, 'An error occured while uploading slapd.conf.conf:'
                    ' {0}'.format(r[1]), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    wlogger.log(tid, 'Gluu slapd.conf file uploaded', 'success')

    cmd = "mkdir -p /opt/gluu/data/main_db"
    c.run(cmd)
    if not c.exists('/opt/gluu/data/main_db'):
        wlogger.log(tid, 'Creating "/opt/gluu/data/main_db" failed', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    cmd = "mkdir -p /opt/gluu/data/site_db"
    c.run(cmd)
    if not c.exists('/opt/gluu/data/site_db'):
        wlogger.log(tid, 'Creating "/opt/gluu/data/site_db" failed', 'fail')
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    wlogger.log(
        tid, 'Directories "/opt/gluu/data/main_db" and "/opt/gluu/data/site_db" were created', 'success')

    run_command(
        tid, c, "chown -R {0}.{1} /opt/gluu/data/".format(
            ldap_info["ldap_user"], ldap_info["ldap_group"]))

    run_command(tid, c, "mkdir -p /var/symas/run/")

    run_command(
        tid, c, "chown -R {0}.{1} /var/symas".format(
            ldap_info["ldap_user"], ldap_info["ldap_group"]))

    run_command(tid, c, "mkdir -p /etc/certs/")

    wlogger.log(tid, "Generating Certificate")
    cmd = "/usr/bin/openssl genrsa -des3 -out /etc/certs/openldap.key.orig -passout pass:{0} 2048".format(
        ldap_info["ldap_password"])

    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    wlogger.log(tid, cin + cout + cerr, "debug")

    cmd = "/usr/bin/openssl rsa -in /etc/certs/openldap.key.orig -passin pass:{0} -out /etc/certs/openldap.key".format(
        ldap_info["ldap_password"])
    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    wlogger.log(tid, cin + cout + cerr, "debug")

    subj = '/C={0}/ST={1}/L={2}/O={3}/CN={4}/emailAddress={5}'.format(
        ldap_info['countryCode'], ldap_info['state'], ldap_info['city'],
        ldap_info['orgName'], ldap_info['fqn_hostname'],
        ldap_info['admin_email'])

    cmd = '/usr/bin/openssl req -new -key /etc/certs/openldap.key -out /etc/certs/openldap.csr -subj {0}'.format(
        subj)

    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    if cout.strip() + cerr.strip():
        wlogger.log(tid, cin + cout + cerr, "debug")

    cmd = "/usr/bin/openssl x509 -req -days 365 -in /etc/certs/openldap.csr -signkey /etc/certs/openldap.key -out /etc/certs/openldap.crt"
    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    wlogger.log(tid, cin + cout + cerr, "debug")

    cmd = "cat /etc/certs/openldap.crt >> /etc/certs/openldap.pem && cat /etc/certs/openldap.key >> /etc/certs/openldap.pem"
    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(cmd)
    if cout.strip() + cerr.strip():
        wlogger.log(tid, cin + cout + cerr, "debug")

    run_command(tid, c, "chown -R {0}.{1} /etc/certs".format(
        ldap_info["ldap_user"], ldap_info["ldap_group"]))

    values = dict(
        hosts="ldaps://127.0.0.1:1636/",
        extra_args=""
    )
    # uplodading symas-openldap.conf file
    confile = os.path.join(app.root_path, "templates",
                           "slapd", "symas-openldap.conf")
    confile_content = open(confile).read()
    confile_content = confile_content.format(**values)

    r = c.put_file('/opt/symas/etc/openldap/symas-openldap.conf',
                   confile_content)

    if r[0]:
        wlogger.log(tid, 'symas-openldap.conf file uploaded', 'success')
    else:
        wlogger.log(tid, 'An error occured while uploading symas-openldap.conf'
                    ': {0}'.format(r[1], 'fail'))
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    wlogger.log(tid, "Satring Symas Open-Ldap Server")
    log = run_command(tid, c, "service solserver restart")
    if 'failed' in log:
        wlogger.log(
            tid, "There seems to be some issue in restarting the server.",
            "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    ldps = Server()
    ldps.hostname = ldap_info["fqn_hostname"]
    ldps.ip = ldap_info["ip_address"]
    ldps.ldap_password = ldap_info["ldap_password"]
    db.session.add(ldps)
    db.session.commit()

def get_os_type(c):
    
    # 2. Linux Distribution of the server
    cin, cout, cerr = c.run("ls /etc/*release")
    files = cout.split()
    cin, cout, cerr = c.run("cat "+files[0])

    if "Ubuntu" in cout and "14.04" in cout:
        return "Ubuntu 14"
    if "Ubuntu" in cout and "16.04" in cout:
        return "Ubuntu 16"
    if "CentOS" in cout and "release 6." in cout:
        return "CentOS 6"
    if "CentOS" in cout and "release 7." in cout:
        return "CentOS 7"
    if 'Red Hat Enterprise Linux' in cout and '7.':
        return 'RHEL 7'


def check_gluu_installation(c):

    appconf = AppConfiguration.query.first()
    check_file = ('/opt/gluu-server-{}/install/community-edition-setup/'
                  'setup.properties.last').format(
                                                appconf.gluu_version
                                            )
    return c.exists(check_file)
    

@celery.task
def collect_server_details(server_id):
    server = Server.query.get(server_id)
    appconf = AppConfiguration.query.first()
    c = RemoteClient(server.hostname, ip=server.ip)
    try:
        c.startup()
    except:
        return

    # 0. Make sure it is a Gluu Server
    chdir = "/opt/gluu-server-" + appconf.gluu_version
    if not c.exists(chdir):
        server.gluu_server = False
        chdir = '/'

    # 1. The components installed in the server
    components = {
        'oxAuth': 'opt/gluu/jetty/oxauth',
        'oxTrust': 'opt/gluu/jetty/identity',
        'OpenLDAP': 'opt/symas/etc/openldap',
        'Shibboleth': 'opt/shibboleth-idp',
        'oxAuthRP': 'opt/gluu/jetty/oxauth-rp',
        'Asimba': 'opt/gluu/jetty/asimba',
        'Passport': 'opt/gluu/node/passport',
    }
    installed = []
    for component, marker in components.iteritems():
        marker = os.path.join(chdir, marker)
        if c.exists(marker):
            installed.append(component)
    server.components = ",".join(installed)

    server.os = get_os_type(c)
    server.gluu_server = check_gluu_installation(c)

    db.session.commit()


def import_key(suffix, hostname, gluu_version, tid, c, sos):
    defaultTrustStorePW = 'changeit'
    defaultTrustStoreFN = '/opt/jre/jre/lib/security/cacerts'
    certFolder = '/etc/certs'
    public_certificate = '%s/%s.crt' % (certFolder, suffix)
    cmd =' '.join([ 
                    '/opt/jre/bin/keytool', "-import", "-trustcacerts", 
                    "-alias", "%s_%s" % (hostname, suffix),
                    "-file", public_certificate, "-keystore", 
                    defaultTrustStoreFN, 
                    "-storepass", defaultTrustStorePW, "-noprompt"
                    ])

    chroot = '/opt/gluu-server-{0}'.format(gluu_version)
    
    if 'CentOS' in sos:
        command = "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost '{0}'".format(cmd)
    else:
        command = 'chroot {0} /bin/bash -c "{1}"'.format(chroot,
                                                         cmd)
    
    cin, cout, cerr = c.run(command)
    wlogger.log(tid, cmd, 'debug')
    wlogger.log(tid, cout+cerr, 'debug')


def delete_key(suffix, hostname, gluu_version, tid, c, sos):
    defaultTrustStorePW = 'changeit'
    defaultTrustStoreFN = '/opt/jre/jre/lib/security/cacerts'
    chroot = '/opt/gluu-server-{0}'.format(gluu_version)
    cert = "etc/certs/%s.crt" % (suffix)
    if c.exists(os.path.join(chroot, cert)):
        cmd=' '.join([  
                        '/opt/jre/bin/keytool', "-delete", "-alias", 
                        "%s_%s" % (hostname, suffix),
                        "-keystore", defaultTrustStoreFN,
                        "-storepass", defaultTrustStorePW
                        ])

        if 'CentOS' in sos:
            command = "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost '{0}'".format(cmd)
        else:
            command = 'chroot {0} /bin/bash -c "{1}"'.format(chroot,
                                                         cmd)
        cin, cout, cerr = c.run(command)
        wlogger.log(tid, cmd, 'debug')
        wlogger.log(tid, cout+cerr, 'debug')


@celery.task(bind=True)
def installGluuServer(self, server_id):
    tid = self.request.id
    server = Server.query.get(server_id)
    pserver = Server.query.filter_by(primary_server=True).first()
    
    appconf = AppConfiguration.query.first()
    c = RemoteClient(server.hostname, ip=server.ip)

    setup_properties_file = os.path.join(Config.DATA_DIR, 'setup.properties')

    gluu_server = 'gluu-server-' + appconf.gluu_version

    if not server.os:
        wlogger.log(tid, "OS type has not been identified.", 'fail')
        wlogger.log(tid, "Ending server installation process.", "error")
        return


    if not server.primary_server:
        wlogger.log(tid, "Check if Primary Server is Installed")

        pc = RemoteClient(pserver.hostname, ip=pserver.ip)

        try:
            pc.startup()
        except:
            wlogger.log(tid, "Can't make SSH connection to primary server: ".format(pserver.hostname), 'error')
            wlogger.log(tid, "Ending server installation process.", "error")
            return
        
        if check_gluu_installation(pc):
            wlogger.log(tid, "Primary Server is Installed",'success')
        else:
            wlogger.log(tid, "Primary Server is not Installed. Please first install Primary Server",'fail')
            wlogger.log(tid, "Ending server installation process.", "error")
            return

    # FIXME: add gluu repo and GPG Key before starting to install

    try:
        c.startup()
    except:
        wlogger.log(tid, "Can't establish SSH connection",'fail')
        wlogger.log(tid, "Ending server installation process.", "error")
        return
    
    wlogger.log(tid, "Preparing for Installation")

    start_command  = 'service gluu-server-{0} start'
    stop_command   = 'service gluu-server-{0} stop'
    enable_command = None

    if 'Ubuntu' in server.os:

        if server.os == 'Ubuntu 14':
            dist = 'trusty'
        elif server.os == 'Ubuntu 16':
            dist = 'xenial'

        cmd = 'curl https://repo.gluu.org/ubuntu/gluu-apt.key | apt-key add -'
        run_command(tid, c, cmd, no_error='debug')

        cmd = ('echo "deb https://repo.gluu.org/ubuntu/ {0} main" '
               '> /etc/apt/sources.list.d/gluu-repo.list'.format(dist))

        run_command(tid, c, cmd)

        install_command = 'apt-get '
        

        
        cmd = 'apt-get update'
        wlogger.log(tid, cmd, 'debug')
        cin, cout, cerr = c.run(cmd)
        wlogger.log(tid, cout+'\n'+cerr, 'debug')
        
        if 'dpkg --configure -a' in cerr:
            cmd = 'dpkg --configure -a'
            wlogger.log(tid, cmd, 'debug')
            cin, cout, cerr = c.run(cmd)
            wlogger.log(tid, cout+'\n'+cerr, 'debug')


    elif 'CentOS' in server.os or 'RHEL' in server.os:
        install_command = 'yum '
        if server.os == 'CentOS 7' or server.os == 'RHEL 7':
            enable_command  = '/sbin/gluu-serverd-{0} enable'
            stop_command    = '/sbin/gluu-serverd-{0} stop'
            start_command   = '/sbin/gluu-serverd-{0} start'
        
        qury_package    = 'yum list installed | grep gluu-server-'

        if not c.exists('/usr/bin/wget'):
            cmd = install_command +'install -y wget'
            run_command(tid, c, cmd, no_error='debug')

        if server.os == 'CentOS 6':
            cmd = 'wget https://repo.gluu.org/centos/Gluu-centos6.repo -O /etc/yum.repos.d/Gluu.repo'
        elif server.os == 'CentOS 7':
            cmd = 'wget https://repo.gluu.org/centos/Gluu-centos7.repo -O /etc/yum.repos.d/Gluu.repo'
        elif server.os == 'RHEL 7':
            cmd = 'wget https://repo.gluu.org/rhel/Gluu-rhel7.repo -O /etc/yum.repos.d/Gluu.repo'

        run_command(tid, c, cmd, no_error='debug')

        cmd = 'wget https://repo.gluu.org/centos/RPM-GPG-KEY-GLUU -O /etc/pki/rpm-gpg/RPM-GPG-KEY-GLUU'
        run_command(tid, c, cmd, no_error='debug')
        
        cmd = 'rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-GLUU'
        run_command(tid, c, cmd, no_error='debug')
        
        cmd = 'yum clean all'
        run_command(tid, c, cmd, no_error='debug')

    wlogger.log(tid, "Check if Gluu Server was installed")

    gluu_installed = False

    r = c.listdir("/opt")
    if r[0]:
        for s in r[1]:
            m=re.search("gluu-server-(?P<gluu_version>(\d+).(\d+).(\d+))$",s)
            if m:
                gluu_version = m.group("gluu_version")
                #FIXME : Modify stop command for OS versions
                gluu_installed = True
                cmd = stop_command.format(gluu_version)
                rs = run_command(tid, c, cmd, no_error='debug')
                
                if "Can't stop gluu server" in rs:
                    cmd = 'rm -f /var/run/{0}.pid'.format(gluu_server)
                    run_command(tid, c, cmd, no_error='debug')
                    
                    cmd = "df -aP | grep %s | awk '{print $6}' | xargs -I {} umount -l {}" % (gluu_server)
                    run_command(tid, c, cmd, no_error='debug')
                 
                    cmd = stop_command.format(gluu_version)
                    rs = run_command(tid, c, cmd, no_error='debug')
                
                run_command(tid, c, install_command + "remove -y "+s)
                #wlogger.log(tid, 
                #        "Gluu version {} was previously installed. Please unintsall and then retry.".format(gluu_version),
                #       "fail")
                #wlogger.log(tid, "Ending server installation process.", "error")
                #return


    if not gluu_installed:
        wlogger.log(tid, "Gluu Server was not previously installed", "debug")



    wlogger.log(tid, "Installing Gluu Server: " + gluu_server)

    #FIXME : check cerr for possible issues on installing package
    cmd = install_command + 'install -y ' + gluu_server
    wlogger.log(tid, cmd, "debug")
    cin, cout, cerr = c.run(install_command + 'install -y ' + gluu_server)
    wlogger.log(tid, cout+cerr, "debug")

    if 'half-installed' in cout + cerr:
        if 'Ubuntu' in server.os: 
            cmd = 'apt-get install --reinstall -y '+ gluu_server
            run_command(tid, c, cmd, no_error='debug')


    if enable_command:
        run_command(tid, c, enable_command.format(appconf.gluu_version), no_error='debug')
        
    run_command(tid, c, start_command.format(appconf.gluu_version))

    if server.os == 'CentOS 7' or server.os == 'RHEL 7':
        wlogger.log(tid, "Sleeping 10 secs to wait for gluu server start properly.")
        time.sleep(10)
    
    # If this server is primary, upload local setup.properties to server
    if server.primary_server:
        wlogger.log(tid, "Uploading setup.properties")
        r = c.upload(setup_properties_file, '/opt/{}/install/community-edition-setup/setup.properties'.format(gluu_server))
    # If this server is not primary, get setup.properties.last from primary server and upload to this server
    else:
        pc = RemoteClient(pserver.hostname, ip=pserver.ip)
        try:
            pc.startup()
        except:
            wlogger.log(tid, "Can't establish SSH connection to primary server: ".format(pserver.hostname), 'error')
            wlogger.log(tid, "Ending server installation process.", "error")
            return
    
        # ldap_paswwrod of this server should be the same with primary server
        ldap_passwd = None

        remote_file = '/opt/{}/install/community-edition-setup/setup.properties.last'.format(gluu_server)
        wlogger.log(tid, 'Downloading setup.properties.last from primary server', 'debug')
        r=pc.get_file(remote_file)
        if r[0]:
            new_setup_properties=''
            setup_properties = r[1].readlines()
            for l in setup_properties:
                if l.startswith('ip='):
                    l = 'ip={0}\n'.format(server.ip)
                elif l.startswith('ldapPass='):
                    ldap_passwd = l.split('=')[1].strip()
                new_setup_properties += l

            remote_file_new = '/opt/{}/install/community-edition-setup/setup.properties'.format(gluu_server)
            wlogger.log(tid, 'Uploading setup.properties', 'debug')
            c.put_file(remote_file_new,  new_setup_properties)
            
            if ldap_passwd:
                server.ldap_password = ldap_passwd
        else:
            wlogger.log(tid, "Can't download setup.properties.last from primary server", 'fail')
            wlogger.log(tid, "Ending server installation process.", "error")
            return

    #if r.startswith('Error:'):
    #    wlogger.log(tid, r, 'fail')
    #    wlogger.log(tid, "Ending server setup process.", "error")
    

    wlogger.log(tid, "Running setup.py - Be patient this process will take a while ...")
    
    if server.os == 'CentOS 7' or server.os == 'RHEL 7':
        cmd = "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost 'cd /install/community-edition-setup/ && ./setup.py -n'"
        run_command(tid, c, cmd)
    else:
        cmd = 'cd /install/community-edition-setup/ && ./setup.py -n'
        run_command(tid, c, cmd, '/opt/'+gluu_server+'/', no_error='debug')

        

    # Get slapd.conf from primary server and upload this server
    if not server.primary_server:

        #FIXME: Check this later
        cmd = 'rm /opt/gluu/data/main_db/*.mdb'
        run_command(tid, c, cmd, '/opt/'+gluu_server)


        slapd_conf_file = '/opt/{0}/opt/symas/etc/openldap/slapd.conf'.format(gluu_server)
        r = pc.get_file(slapd_conf_file)
        if r[0]:
            fc = r[1].read()
            r2 = c.put_file(slapd_conf_file, fc)
            if not r2[0]:
                wlogger.log(tid, "Can't put slapd.conf to this server: ".format(r[1]), 'error')
            else:
                wlogger.log(tid, "slapd.conf was downloaded from primary server and uploaded to this server", 'success')
        else:
            wlogger.log(tid, "Can't get slapd.conf from primary server: ".format(r[1]), 'error')


        wlogger.log(tid, 'Downloading custom schema files from primary server and upload to this server')
        custom_schema_files = pc.listdir("/opt/{0}/opt/gluu/schema/openldap/".format(gluu_server))
        
        if custom_schema_files[0]:
            for csf in custom_schema_files[1]:
                local = '/tmp/'+csf
                remote = '/opt/{0}/opt/gluu/schema/openldap/{1}'.format(gluu_server, csf)
                
                pc.download(remote, local)
                c.upload(local, remote)
                os.remove(local)
                wlogger.log(tid, '{0} dowloaded from from primary and uploaded'.format(csf), 'debug')

            if server.os == 'CentOS 7' or server.os == 'RHEL 7':
                run_command(tid, c, "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost 'service solserver stop'")
            else:
                run_command(tid, c, 'service solserver stop', '/opt/'+gluu_server)
            
            if server.os == 'CentOS 7' or server.os == 'RHEL 7':
                run_command(tid, c, "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost 'service solserver start'")
            else:
                run_command(tid, c, 'service solserver start', '/opt/'+gluu_server)

        if appconf.gluu_version > '3.0.2':
            wlogger.log(tid, "Downloading certificates from primary server and uploading to this server")
            certs_remote_tmp = "/tmp/certs_"+str(uuid.uuid4())[:4].upper()+".tgz"
            certs_local_tmp = "/tmp/certs_"+str(uuid.uuid4())[:4].upper()+".tgz"
            
            cmd = 'tar -zcf {0} /opt/gluu-server-{1}/etc/certs/'.format(certs_remote_tmp, appconf.gluu_version)
            wlogger.log(tid,cmd,'debug')
            cin, cout, cerr = pc.run(cmd)
            wlogger.log(tid, cout+cerr, 'debug')
            wlogger.log(tid,cmd,'debug')
            

            r = pc.download(certs_remote_tmp, certs_local_tmp)
            if 'Download successful' in r :
                wlogger.log(tid, r,'success')
            else:
                wlogger.log(tid, r,'error')
                
            r = c.upload(certs_local_tmp, "/tmp/certs.tgz")
            
            if 'Upload successful' in r:
                wlogger.log(tid, r,'success')
            else:
                wlogger.log(tid, r,'error')
                
            cmd = 'tar -zxf /tmp/certs.tgz -C /'
            run_command(tid, c, cmd)
        
            wlogger.log(tid, 'Manuplating keys')
            for suffix in (
                    'httpd',
                    'shibIDP',
                    'idp-encryption',
                    'asimba',
                    'openldap',
                    ):
                delete_key(suffix, appconf.nginx_host, appconf.gluu_version, tid, c, server.os)
                import_key(suffix, appconf.nginx_host, appconf.gluu_version, tid, c, server.os)

    else:
        custom_schema_dir = os.path.join(Config.DATA_DIR, 'schema')
        custom_schemas = os.listdir(custom_schema_dir)
        
        if custom_schemas:
            for sf in custom_schemas:
                local = os.path.join(custom_schema_dir, sf)
                remote = '/opt/{0}/opt/gluu/schema/openldap/{1}'.format(gluu_server, sf)
                r = c.upload(local, remote)
                if r[0]:
                    wlogger.log(tid, 'Custom schame file {0} uploaded'.format(sf), 'success')
                else:
                    wlogger.log(tid, "Can't upload custom schame file {0}: ".format(sf, r[1]), 'error')

    wlogger.log(tid, "Checking if ntp is installed and configured.")

    if c.exists('/usr/sbin/ntpdate'):
        wlogger.log(tid, "ntp was installed", 'success')
    else:

        cmd = install_command + 'install -y ntpdate'
        run_command(tid, c, cmd)
    
    c.put_file('/etc/cron.d/setdate', '* * * * *    root    /usr/sbin/ntpdate -s time.nist.gov\n')
    wlogger.log(tid, 'Crontab entry was created to update time in every minute', 'debug')
    
    if 'CentOS' in server.os or 'RHEL' in server.os:
        cmd = 'service crond reload'
    else:
        cmd = 'service cron reload'
    
    run_command(tid, c, cmd, no_error='debug')

    server.gluu_server = True
    db.session.commit()
    wlogger.log(tid, "Gluu Server successfully installed")


@celery.task(bind=True)
def removeMultiMasterDeployement(self, server_id):
    app_config = AppConfiguration.query.first()
    server = Server.query.get(server_id)
    tid = self.request.id
    app_config = AppConfiguration.query.first()
    if not server.gluu_server:
        chroot = '/'
    else:
        chroot = '/opt/gluu-server-' + app_config.gluu_version

    wlogger.log(tid, "Making SSH connection to the server %s" %
                server.hostname)
    c = RemoteClient(server.hostname, ip=server.ip)

    try:
        c.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection {0}".format(e), "warning")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False

    if server.gluu_server:
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
    confile = os.path.join(app.root_path, "templates",
                           "slapd", "symas-openldap.conf")
    confile_content = open(confile).read()

    vals = dict(
        hosts='ldaps://127.0.0.1:1636/',
        extra_args='',
    )

    confile_content = confile_content.format(**vals)

    r = c.put_file(os.path.join(
        chroot, 'opt/symas/etc/openldap/symas-openldap.conf'), confile_content)

    if r[0]:
        wlogger.log(tid, 'symas-openldap.conf file uploaded', 'success')
    else:
        wlogger.log(tid, 'An error occured while uploading symas-openldap.conf'
                    ': {0}'.format(r[1]), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return

    run_command(tid, c, "chown -R ldap:ldap /opt/symas/etc/openldap", chroot)


    slapd_d_dir = os.path.join(chroot, 'opt/symas/etc/openldap/')
    if c.exists(slapd_d_dir):
        cmd = "rm -rf /opt/symas/etc/openldap/slapd.d"
        run_command(tid, c, cmd, chroot)


    server.mmr = False
    db.session.commit()
    
    #modifyOxLdapProperties(server, c, tid)

    # Restart the solserver with slapd.conf configuration
    wlogger.log(tid, "Restarting LDAP server with slapd.conf configuration")
    
    if 'CentOS' in server.os:
        run_command(tid, c, "ssh -o IdentityFile=/etc/gluu/keys/gluu-console -o Port=60022 -o LogLevel=QUIET -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PubkeyAuthentication=yes root@localhost 'service solserver restart'")
    else:
        log = run_command(tid, c, "service solserver restart", chroot)
                
        if 'failed' in log:
            wlogger.log(tid,
                        "There seems to be some issue in restarting the server.",
                        "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return
    
    wlogger.log(tid, 'Deployment of Ldap Server was successfully removed')

    return True

@celery.task(bind=True)
def installNGINX(self, nginx_host):
    tid = self.request.id
    app_config = AppConfiguration.query.first()
    pserver = Server.query.filter_by(primary_server=True).first()
    wlogger.log(tid, "Making SSH connection to the server {}".format(nginx_host))
    c = RemoteClient(nginx_host)

    try:
        c.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection {0}".format(e), "warning")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False
    wlogger.log(tid, "Determining OS type")
    os_type = get_os_type(c)
    wlogger.log(tid, "OS is determined as {0}".format(os_type),'debug')
    wlogger.log(tid, "Check if NGINX installed")
    
    r = c.exists("/usr/sbin/nginx")
    
    if r:
        wlogger.log(tid, "nginx allready exists")
    else:
        if 'CentOS' in os_type:
            run_command(tid, c, 'yum install -y epel-release')
            cmd = 'yum install -y nginx'
        else:
            run_command(tid, c, 'apt-get update')
            cmd = 'apt-get install -y nginx'
            
        wlogger.log(tid, cmd, 'debug')
        
        #FIXME: check cerr??
        cin, cout, cerr = c.run(cmd)
        wlogger.log(tid, cout, 'debug')


    r = c.exists("/etc/nginx/ssl/")
    if not r:
        wlogger.log(tid, "/etc/nginx/ssl/ does not exists. Creating ...", "debug")
        r2 = c.mkdir("/etc/nginx/ssl/")
        if r2[0]:
            wlogger.log(tid, "/etc/nginx/ssl/ was created", "success")
        else:
            wlogger.log(tid, "Error creating /etc/nginx/ssl/ {0}".format(r2[1]), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
    else:
        wlogger.log(tid, "Directory /etc/nginx/ssl/ exists.", "debug")


    wlogger.log(tid, "Making SSH connection to primary server {} for downloading certificates".format(pserver.hostname))
    pc = RemoteClient(pserver.hostname, pserver.ip)
    try:
        pc.startup()
    except Exception as e:
        wlogger.log(
            tid, "Cannot establish SSH connection to primary server {0}".format(e), "warning")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False
    for crt in ('httpd.crt', 'httpd.key'):
        wlogger.log(tid, "Downloading {0} from primary server".format(crt), "debug")
        remote_file = '/opt/gluu-server-{0}/etc/certs/{1}'.format(app_config.gluu_version, crt)
        r = pc.get_file(remote_file)
        if not r[0]:
            wlogger.log(tid, "Can't download {0} from primary server: {1}".format(crt,r[1]), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
        else:
            wlogger.log(tid, "File {} was downloaded.".format(remote_file), "success")
        fc = r[1].read()
        remote = os.path.join("/etc/nginx/ssl/", crt)
        r = c.put_file(remote, fc)
        
        if r[0]:
            wlogger.log(tid, "File {} uploaded".format(remote), "success")
        else:
            wlogger.log(tid, "Can't upload {0}: {1}".format(remote,r[1]), "error")
            wlogger.log(tid, "Ending server setup process.", "error")
            return False
    
    servers = Server.query.all()
    nginx_backends = []
    
    
    nginx_tmp_file = os.path.join(app.root_path, "templates", "nginx",
                           "nginx.temp")
    nginx_tmp = open(nginx_tmp_file).read()
    
    for s in servers:
        nginx_backends.append('  server {0}:443;'.format(s.hostname))
        
    nginx_tmp = nginx_tmp.replace('{#NGINX#}', nginx_host)
    nginx_tmp = nginx_tmp.replace('{#SERVERS#}', '\n'.join(nginx_backends))

    remote = "/etc/nginx/nginx.conf"
    r = c.put_file(remote, nginx_tmp)
    
    if r[0]:
         wlogger.log(tid, "File {} uploaded".format(remote), "success")
    else:
        wlogger.log(tid, "Can't upload {0}: {1}".format(remote,r[1]), "error")
        wlogger.log(tid, "Ending server setup process.", "error")
        return False

    cmd = 'service nginx restart'
    
    run_command(tid, c, cmd, no_error='debug')
    
    wlogger.log(tid, "NGINX successfully installed")
