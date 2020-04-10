"""A Flask blueprint with the views and the business logic dealing with
the servers managed in the cluster-manager
"""
import os
import base64

import requests as http_requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
http_requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from flask import Blueprint, render_template, url_for, flash, redirect, \
    session, request
from flask_login import login_required
from flask import current_app as app
from flask_menu import register_menu

from clustermgr.extensions import db
from clustermgr.core.ldap_functions import LdapOLC
from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cluster import installNGINX, \
    setup_filesystem_replication, opendjenablereplication, \
    remove_server_from_cluster, remove_filesystem_replication, \
    opendj_disable_replication_task

from clustermgr.core.utils import get_setup_properties, \
    get_opendj_replication_status, random_chars
from clustermgr.core.remote import RemoteClient

from clustermgr.forms import FSReplicationPathsForm

from clustermgr.config import Config

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.license import license_required

replication = Blueprint('replication', __name__, template_folder='templates')
replication.before_request(prompt_license)
replication.before_request(license_required)
replication.before_request(license_reminder)

@replication.route('/menuindex')
@register_menu(replication, '.gluuServerCluster.replication', 'Replication', order=2, icon='fa fa-refresh')
def menuIndex():
    return redirect(url_for('replication.multi_master_replication'))

@login_required
@replication.route('/mmr/opendjdisablereplication/<int:server_id>/')
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



@login_required
@replication.route('/removeserverfromcluster/<int:server_id>/')
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


@replication.route('/mmr/remove_deployment/<int:server_id>/')
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

@login_required
@replication.route('/mmr/opendjenablereplication/<server_id>')
def opendj_enable_replication(server_id):

    nextpage = url_for('replication.multi_master_replication')
    whatNext = "LDAP Replication"
    if not server_id == 'all':
        server = Server.query.get(server_id)
        head = "Enabling Multimaster Replication on Server: " + server.hostname
    else:
        head = "Enabling Multimaster Replication on all servers"
        server = ''

    #Start openDJ replication celery task
    #task = opendjenablereplication.delay(server_id)

    app_config = AppConfiguration.query.first()
    if not app_config.replication_pw:
        app_config.replication_pw = random_chars(8)
        db.session.commit()

    return app_config.replication_pw

    return render_template('logger_single.html', title=head, server=server,
                           task=task, nextpage=nextpage, whatNext=whatNext)



def chekFSR(server, gluu_version):
    c = RemoteClient(server.hostname, ip=server.ip)
    try:
        c.startup()
    except Exception as e:
        flash("Can't establish SSH connection to {}".format(server.hostname),
              "warning")
        return False, []
    
    csync_config = '/opt/gluu-server-{}/etc/csync2.cfg'.format(gluu_version)
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

@login_required
@register_menu(replication, '.gluuServerCluster.replication.fileSystem', 'File System', order=2)
@replication.route('/fsrep', methods=['GET', 'POST'])
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
                           
@login_required
@replication.route('/removefsrep')
def remove_file_system_replication():
    servers = Server.query.all()
    task = remove_filesystem_replication.delay()

    title = "Uninstalling File System Replication"
    nextpage=url_for('index.home')
    whatNext="Dashboard"
    
    return render_template('logger_single.html',
                           task_id=task.id, title=title,
                           nextpage=nextpage, whatNext=whatNext,
                           task=task, multiserver=servers)


@replication.route('/mmr/setpassword', methods=['POST'])
@login_required
def set_replication_password():

    replication_pw = request.form.get('replication_password')

    app_config = AppConfiguration.query.first()
    if not app_config:
        app_config = AppConfiguration()
        db.session.add(app_config)
    app_config.replication_pw = replication_pw
    db.session.commit()

    return redirect(url_for('replication.multi_master_replication')) 

@replication.route('/mmr/')
@register_menu(replication, '.gluuServerCluster.replication.multiMaster', 'LDAP', order=1)
@login_required
def multi_master_replication():
    """Multi Master Replication view for OpenDJ"""

    # Check if replication user (dn) and password has been configured
    app_config = AppConfiguration.query.first()
    if not app_config:
        app_config = AppConfiguration()
        db.session.add(app_config)
        db.session.commit()

    ldaps = Server.query.all()
    primary_server = Server.query.filter_by(primary_server=True).first()

    if not ldaps:
        flash("Servers has not been added. "
              "Please add servers",
              "warning")
        return redirect(url_for('index.home'))


    ldap_errors = []

    prop = get_setup_properties()
    stat = ''
    replication_pw_base64 = ''
    if app_config.replication_pw:
        replication_pw_base64 = base64.encodestring(app_config.replication_pw)
        if replication_pw_base64.endswith('\n'):
            replication_pw_base64 = replication_pw_base64[:-1]

    if app_config.replication_pw:
        rep_status = get_opendj_replication_status()

        if not rep_status[0]:
            flash(rep_status[1], "warning")
        else:
            stat = rep_status[1]
    else:
        rep_status = None

    return render_template('opendjmmr.html',
                           servers=ldaps,
                           stat = stat,
                           app_conf=app_config,
                           replication_pw_base64=replication_pw_base64
                           )