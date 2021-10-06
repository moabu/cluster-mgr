"""A Flask blueprint with the views and the business logic dealing with
the servers managed in the cluster-manager
"""
import os

import requests as http_requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
http_requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from flask import Blueprint, render_template, url_for, flash, redirect, \
    session, request, jsonify
from flask_login import login_required
from flask import current_app as app

from clustermgr.core.ldap_functions import LdapOLC
from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cluster import installNGINX, \
    setup_filesystem_replication, opendjenablereplication, \
    remove_server_from_cluster, remove_filesystem_replication, \
    opendj_disable_replication_task, uninstallNGINX

from clustermgr.core.utils import port_status_cmd

from clustermgr.core.remote import RemoteClient

from clustermgr.forms import FSReplicationPathsForm

from clustermgr.config import Config

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.license import license_required

cluster = Blueprint('cluster', __name__, template_folder='templates')
cluster.before_request(prompt_license)
cluster.before_request(license_required)
cluster.before_request(license_reminder)

@cluster.route('/opendjdisablereplication/<int:server_id>/')
@login_required
def opendj_disable_replication(server_id):
    server = Server.query.get(server_id)
    task = opendj_disable_replication_task.delay(
                                            server.id, 
                                        )
    title = "Disabling LDAP Replication for {}".format(server.hostname)
    nextpage = url_for('index.multi_master_replication')
    whatNext = "Multi Master Replication"


    return render_template('logger_single.html', server_id=server.id,
                           title=title, steps=[], task=task,
                           nextpage=nextpage, whatNext=whatNext
                           )



@cluster.route('/removeserverfromcluster/<int:server_id>/')
@login_required
def remove_server_from_cluster_view(server_id):
    """Initiates removal of replications"""
    remove_server = False
    
    if request.args.get('removeserver'):
        remove_server = True
    
    disable_replication = True if request.args.get(
                                    'disablereplication',''
                                    ).lower() == 'true' else False

    #Start non-gluu ldap server installation celery task
    server = Server.query.get(server_id)
    task = remove_server_from_cluster.delay(
                                            server.id, 
                                            remove_server, 
                                            disable_replication
                                        )

    title = "Removing server {} from cluster".format(server.hostname)

    if request.args.get('next') == 'dashboard':
        nextpage = url_for("index.home")
        whatNext = "Dashboard"
    else:
        nextpage = "index.multi_master_replication"
        whatNext = "Multi Master Replication"
    
    return render_template('logger_single.html',
                           server_id=server_id,
                           title=title,
                           steps=[],
                           task=task,
                           cur_step=1,
                           auto_next=False,
                           multistep=False,
                           nextpage=nextpage,
                           whatNext=whatNext
                           )


@cluster.route('/remove_deployment/<int:server_id>/')
@login_required
def remove_deployment(server_id):
    """Initiates removal of replication deployment and back to slapd.conf

    Args:
        server_id (integer): id of server to be undeployed
    """

    thisServer = Server.query.get(server_id)
    servers = Server.query.filter(Server.id.isnot(server_id)).filter(
        Server.mmr.is_(True)).all()

    # We should check if this server is a provider for a server in cluster, so
    # iterate all servers in cluster
    for m in servers:
        ldp = LdapOLC('ldaps://{}:1636'.format(m.hostname),
                      "cn=config", m.ldap_password)
        r = None
        try:
            r = ldp.connect()
        except Exception as e:
            flash("Connection to LDAPserver {0} at port 1636 was failed:"
                  " {1}".format(m.hostname, e), "danger")

        if r:
            # If this server is a provider to another server, refuse to remove
            # deployment and update admin
            pd = ldp.getProviders()

            if thisServer.hostname in pd:
                flash("This server is a provider for Ldap Server {0}."
                      " Please first remove this server as provider.".format(
                          thisServer.hostname), "warning")
                return redirect(url_for('index.multi_master_replication'))

    # Start deployment removal celery task
    task = removeMultiMasterDeployement.delay(server_id)
    print("TASK STARTED", task.id)
    title = "Removing Deployment"
    nextpage = url_for('index.multi_master_replication')
    whatNext = "Multi Master Replication"
    
    
    return render_template('logger_single.html', server_id=server.id,
                       title=title, steps=[], task=task,
                       nextpage=nextpage, whatNext=whatNext
                       )

def checkNginxStatus(nginxhost):
    
    servers = {}
    status = False
    
    try:
        r =  http_requests.get('https://{}/clustermgrping'.format(nginxhost),
                                                        verify=False)
        if r.status_code == 200:
            status = True
            for server in r.text.split():
                server_status = False
                try:
                    r_identity = http_requests.get(
                                        'https://{}/identity/'.format(server),
                                        verify=False)
                
                    if r_identity.status_code == 200:
                        server_status = True
                except:
                    pass
                servers[server] = server_status
    except:
        pass

    return status, servers


@cluster.route('/nginx')
@login_required
def install_nginx():
    """Initiates installation of nginx load balancer"""
    app_conf = AppConfiguration.query.first()
    status = checkNginxStatus(app_conf.nginx_host)
    if status:
        status = checkNginxStatus(app_conf.nginx_host)
        if status[0]:
            return render_template("nginx_reinstall.html", 
                            servers=status[1],
                            )

    return render_template("nginx_home.html")


@cluster.route('/nginx/install')
@login_required
def do_install_nginx():
    app_conf = AppConfiguration.query.first()
    session_type = request.args.get('session_type')

    if session_type and not session_type in ('ip_hash', 'sticky'):
        flash("Session type should be either ip_hash or sticky", 'warning')
        return render_template("nginx_home.html")

    session_type_fn = os.path.join(app.config['DATA_DIR'], 'nginx_session_type')

    if session_type:
        with open(session_type_fn, 'w') as w:
            w.write(session_type)
    else:
        if os.path.exists(session_type_fn):
            session_type = open(session_type_fn).read().strip()
        else:
            session_type = 'ip_hash'
            with open(session_type_fn, 'w') as w:
                w.write(session_type)

    # Start nginx  installation celery task
    task = installNGINX.delay(app_conf.nginx_host, session_type)

    print("Install NGINX TASK STARTED", task.id)
    head = "Configuring NGINX Load Balancer on {0}".format(app_conf.nginx_host)

    if request.args.get('next') == 'this':
        nextpage = url_for('cluster.install_nginx')
        whatNext = "Nginx Home"
    else:
        nextpage = url_for('index.multi_master_replication')
        whatNext = "LDAP Replication"

    return render_template('logger_single.html', title=head, server=app_conf.nginx_host,
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/nginx/uninstall')
@login_required
def do_uninstall_nginx():
    app_conf = AppConfiguration.query.first()
    
    # Start nginx  uninstallation celery task
    task = uninstallNGINX.delay()
    print("Uninstall NGINX TASK STARTED", task.id)
    head = "Uninstalling NGINX Load Balancer on {0}".format(app_conf.nginx_host)

    nextpage = url_for('cluster.install_nginx')
    whatNext = "Nginx Home"

    return render_template('logger_single.html', title=head, server=app_conf.nginx_host,
                           task=task, nextpage=nextpage, whatNext=whatNext)

@cluster.route('/opendjenablereplication/<server_id>')
@login_required
def opendj_enable_replication(server_id):

    nextpage = url_for('index.multi_master_replication')
    whatNext = "LDAP Replication"
    if not server_id == 'all':
        server = Server.query.get(server_id)
        head = "Enabling Multimaster Replication on Server: " + server.hostname
    else:
        head = "Enabling Multimaster Replication on all servers"
        server = ''

    #Start openDJ replication celery task
    task = opendjenablereplication.delay(server_id)

    return render_template('logger_single.html', title=head, server=server,
                           task=task, nextpage=nextpage, whatNext=whatNext)



def chekFSR(server, gluu_version):
    print("Checking File System Replication")
    c = RemoteClient(server.hostname, ip=server.ip, ssh_port=server.ssh_port)
    try:
        c.startup()
    except Exception as e:
        flash("Can't establish SSH connection to {}".format(server.hostname),
              "warning")
        return False, []
    
    csync_config = '/opt/gluu-server/etc/csync2.cfg'
    result = c.get_file(csync_config)
    
    if result[0]:
        
        servers = []

        for l in result[1].readlines():
            ls = l.strip()
            if ls.startswith('host') and ls.endswith(';'):
                hostname = ls.split()[1][:-1]
                servers.append(hostname)
        
        if servers:
            return True, servers

    return False, []

@cluster.route('/fsrep/status', methods=['GET'])
@login_required
def fsrep_health():
    servers = Server.get_all()
    status = {}
    for server in servers:
        status[server.id]= False
        c = RemoteClient(server.hostname, ip=server.ip, ssh_port=server.ssh_port)
        try:
            c.startup()
        except Exception as e:
            print("Can't establish SSH connection to", server.hostname, "Reason:", e)
    
        csyncs2_cmd = port_status_cmd.format('localhost', 30865)
        r = c.run(csyncs2_cmd)
        if r[1].strip()=='0':
            status[server.id]= True
    return jsonify(status)

@cluster.route('/fsrep', methods=['GET', 'POST'])
@login_required
def file_system_replication():
    """File System Replication view"""

    app_config = AppConfiguration.query.first()
    servers = Server.query.all()

    csync = 0

    if request.method == 'GET':
        if not request.args.get('install') == 'yes':
            status = chekFSR(servers[0], app_config.gluu_version)
            
            for server in servers:
                if 'csync{}.gluu'.format(server.id) in status[1]:
                    server.csync = True
                    csync += 1

            if status[0]:
                return render_template("fsr_home.html", servers=servers, csync=csync)

    #Check if replication user (dn) and password has been configured
    if not app_config:
        flash("Repication user and/or password has not been defined."
              " Please go to 'Configuration' and set these before proceed.",
              "warning")

    #If there is no installed gluu servers, return to home

    if not servers:
        flash("Please install gluu servers", "warning")
        return redirect(url_for('index.home'))

    for server in servers:
        if not server.gluu_server:
            flash("Please install gluu servers", "warning")
            return redirect(url_for('index.home'))

    fs_paths_form = FSReplicationPathsForm()

    user_replication_paths_fn = os.path.join(app.config['DATA_DIR'], 'replication_defaults.txt')

    if request.method == 'POST':
        with open(user_replication_paths_fn, 'w') as w:
            w.write(fs_paths_form.fs_paths.data)

    else:
        if os.path.exists(user_replication_paths_fn):
            rep_fn = user_replication_paths_fn
        else:
        
            rep_fn = os.path.join(app.root_path, 'templates',
                                    'file_system_replication',
                                    'replication_defaults.txt')

        with open(rep_fn) as f:
            replication_paths = f.read()

        fs_paths_form.fs_paths.data = replication_paths

        return render_template("fsrep.html", form=fs_paths_form)


    task = setup_filesystem_replication.delay()

    title = "Installing File System Replication"
    nextpage=url_for('cache_mgr.index')
    whatNext="Cache Management"
    
    return render_template('logger_single.html',
                           task_id=task.id, title=title,
                           nextpage=nextpage, whatNext=whatNext,
                           task=task, multiserver=servers)
                           

@cluster.route('/removefsrep')
@login_required
def remove_file_system_replication():
    servers = Server.get_all()
    task = remove_filesystem_replication.delay()

    title = "Uninstalling File System Replication"
    nextpage=url_for('cluster.file_system_replication')
    whatNext="File System Replication Home"
    
    return render_template('logger_single.html',
                           task_id=task.id, title=title,
                           nextpage=nextpage, whatNext=whatNext,
                           task=task, multiserver=servers)
