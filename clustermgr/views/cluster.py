"""A Flask blueprint with the views and the business logic dealing with
the servers managed in the cluster-manager
"""
import os

import requests as http_requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
http_requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from flask import Blueprint, render_template, url_for, flash, redirect, \
    session, request
from flask_login import login_required
from flask import current_app as app

from clustermgr.core.ldap_functions import LdapOLC, getLdapConn
from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cluster import  \
    installGluuServer, installNGINX, \
    setup_filesystem_replication, opendjenablereplication, \
    remove_server_from_cluster, remove_filesystem_replication, \
    opendj_disable_replication_task, update_filesystem_replication_paths

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


@cluster.route('/deploy_config/<server_id>', methods=['GET', 'POST'])
@login_required
def deploy_config(server_id):
    """Initiates replication deployement task

    Args:
        server_id (integer): id of server to be deployed
    """

    nextpage = 'index.multi_master_replication'
    whatNext = "LDAP Replication"

    s = None

    if not server_id == 'all':
        if server_id.isalnum():
            server_id = int(server_id)
            s = Server.query.get(server_id)
            if not s:
                flash("Server id {0} is not on database".format(server_id), 'warning')
                return redirect(url_for("index.multi_master_replication"))

            #Start deployment celery task
            task = setup_ldap_replication.delay(server_id)
            head = "Setting up Replication on Server: " + s.hostname

        else:
            flash("Invalid Server id {0}".format(server_id), 'warning')
            return redirect(url_for("index.multi_master_replication"))

    else:
        #Start deployment celery task
        task = setup_ldap_replication.delay(server_id)
        head = "Setting up Replication on All Servers"



    return render_template("logger.html", heading=head, server=s,
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/opendjdisablereplication/<int:server_id>/')
def opendj_disable_replication(server_id):
    server = Server.query.get(server_id)
    task = opendj_disable_replication_task.delay(
                                            server.id, 
                                        )
    head = "Disabling LDAP Replication for {}".format(server.hostname)
    nextpage = "index.multi_master_replication"
    whatNext = "Multi Master Replication"


    return render_template("logger.html", heading=head, server=server,
                           task=task, nextpage=nextpage, whatNext=whatNext)



@cluster.route('/removeserverfromcluster/<int:server_id>/')
def remove_server_from_cluster_view(server_id):
    """Initiates removal of replications"""
    remove_server = False
    
    if request.args.get('removeserver'):
        remove_server = True
    
    disable_replication = True if request.args.get(
                                    'disablereplication',''
                                    ).lower() == 'true' else False
    
    
    print request.args.get('disablereplication'), disable_replication
    
    #Start non-gluu ldap server installation celery task
    server = Server.query.get(server_id)
    task = remove_server_from_cluster.delay(
                                            server.id, 
                                            remove_server, 
                                            disable_replication
                                        )

    head = "Removing server {} from cluster".format(server.hostname)

    if request.args.get('next') == 'dashboard':
        nextpage = "index.home"
        whatNext = "Dashboard"
    else:
        nextpage = "index.multi_master_replication"
        whatNext = "Multi Master Replication"
    return render_template("logger.html", heading=head, server=server,
                           task=task, nextpage=nextpage, whatNext=whatNext)

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
    print "TASK STARTED", task.id
    head = "Removing Deployment"
    nextpage = "index.multi_master_replication"
    whatNext = "Multi Master Replication"
    return render_template("logger.html", heading=head, server=thisServer,
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/install_ldapserver')
@login_required
def install_ldap_server():
    """Initiates installation of non-gluu ldap server"""

    # Start non-gluu ldap server installation celery task
    task = InstallLdapServer.delay(session['nongluuldapinfo'])
    print "TASK STARTED", task.id
    head = "Installing Symas Open-Ldap Server on " + \
        session['nongluuldapinfo']['fqn_hostname']
    nextpage = "index.multi_master_replication"
    whatNext = "Multi Master Replication"
    return render_template("logger.html", heading=head, server="",
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/install_gluu_server/<int:server_id>/')
@login_required
def install_gluu_server(server_id):
    """Initiates installation of gluu server

    Args:
        server_id (integer): id fo server to be installed
    """

    server = Server.query.get(server_id)
    appconf = AppConfiguration.query.first()

    # Start gluu server installation celery task
    task = installGluuServer.delay(server_id)

    print "Install Gluu Server TASK STARTED", task.id
    head = "Installing Gluu Server ({0}) on {1}".format(
                                                    appconf.gluu_version,
                                                    server.hostname,
                                                    )
    nextpage = "index.home"
    whatNext = "Dashboard"
    return render_template("logger.html", heading=head, server=server.hostname,
                           task=task, nextpage=nextpage, whatNext=whatNext)

def checkNginxStatus(nginxhost):
    try:
        r=  http_requests.get('https://{}/clustermgrping'.format(nginxhost),
                                                        verify=False)
        if r.status_code == 200:
            return True, r.text.split()
    except:
        pass

    return False, []


@cluster.route('/installnginx')
@login_required
def install_nginx():
    """Initiates installation of nginx load balancer"""
    appconf = AppConfiguration.query.first()

    if not request.args.get('next') == 'install':
        status = checkNginxStatus(appconf.nginx_host)
        if status[0]:
            return render_template("nginx_home.html", servers=status[1])
        

    # Start nginx  installation celery task
    task = installNGINX.delay(appconf.nginx_host)

    head = "Configuring NGINX Load Balancer on {0}".format(appconf.nginx_host)
    nextpage = "index.multi_master_replication"
    whatNext = "LDAP Replication"
    return render_template("logger.html", heading=head, server=appconf.nginx_host,
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/opendjenablereplication/<server_id>')
def opendj_enable_replication(server_id):

    nextpage = 'index.multi_master_replication'
    whatNext = "LDAP Replication"
    if not server_id == 'all':
        server = Server.query.get(server_id)
        head = "Enabling Replication on Server: " + server.hostname
    else:
        head = "Enabling Replication on all servers"
        server = ''

    #Start openDJ replication celery task
    task = opendjenablereplication.delay(server_id)

    return render_template("logger.html", heading=head, server=server,
                           task=task, nextpage=nextpage, whatNext=whatNext)



def chekFSR(server, gluu_version):
    c = RemoteClient(server.hostname, ip=server.ip)
    
    paths = []
    
    try:
        c.startup()
    except Exception as e:
        flash("Can't establish SSH connection to {}".format(server.hostname),
              "warning")
        return False, [], paths
    
    csync_config = '/opt/gluu-server-{}/etc/csync2.cfg'.format(gluu_version)
    result = c.get_file(csync_config)
    
    if result[0]:
        
        servers = []

        paths

        for l in result[1].readlines():
            ls = l.strip()
            if ls.startswith('host') and ls.endswith(';'):
                hostname = ls.split()[1][:-1]
                servers.append(hostname)
            elif ls.startswith('include') and ls.endswith(';'):
                ipath = ls.split('include')[1].strip().strip(';').strip()
                paths.append(ipath)
        
        if servers:
            return True, servers, paths

    return False, [], paths

@cluster.route('/fsrep', methods=['GET', 'POST'])
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
            
            
            form = FSReplicationPathsForm()
            form.fs_paths.data = '\n'.join(status[2])
            
            if status[0]:
                return render_template(
                                "fsr_home.html", 
                                servers=servers, 
                                csync=csync,
                                paths=status[2],
                                form=form
                                )

    #Check if replication user (dn) and password has been configured
    if not app_config:
        flash("Repication user and/or password has not been defined."
              " Please go to 'Configuration' and set these before proceed.",
              "warning")

    #If there is no installed gluu servers, return to home

    if not servers:
        flash("Please install gluu servers", "warning")
        return redirect(url_for('index.home'))

    replicated = False

    for server in servers:
        if not server.gluu_server:
            flash("Please install gluu servers", "warning")
            return redirect(url_for('index.home'))

    fs_paths_form = FSReplicationPathsForm()


    if not request.args.get('next') == 'install':

        replication_defaults_file = os.path.join(app.root_path, 'templates',
                                    'file_system_replication',
                                    'replication_defaults.txt')

        replication_paths = open(replication_defaults_file).read()

        fs_paths_form.fs_paths.data = replication_paths

        return render_template("fsrep.html", form=fs_paths_form)


    user_fsr_file_name = os.path.join(app.config["DATA_DIR"], 'fsr_paths')

    with open(user_fsr_file_name,'w') as w:
        w.write(fs_paths_form.fs_paths.data.strip())

    task = setup_filesystem_replication.delay()

    return render_template('fsr_install_logger.html', step=1,
                           task_id=task.id, servers=servers)
                           


@cluster.route('/updatefsreppath', methods=["POST"])
def update_fsrep_path():
    servers = Server.query.all()

    fsr_paths = request.form['fs_paths']

    user_fsr_file_name = os.path.join(app.config["DATA_DIR"], 'fsr_paths')
    
    with open(user_fsr_file_name,'w') as w:
        w.write(fsr_paths)

    task = update_filesystem_replication_paths.delay()
    return render_template('fsr_install_logger.html', step=1,
                           task_id=task.id, servers=servers)

@cluster.route('/removefsrep')
def remove_file_system_replication():
    servers = Server.query.all()
    task = remove_filesystem_replication.delay()

    return render_template('fsr_remove_logger.html', step=1,
                           task_id=task.id, servers=servers)
                           
