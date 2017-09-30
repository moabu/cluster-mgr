"""A Flask blueprint with the views and the business logic dealing with
the servers managed in the cluster-manager
"""
from flask import Blueprint, render_template, url_for, flash, redirect, \
    request, session

from clustermgr.core.ldap_functions import ldapOLC
from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cluster import setupMmrServer, InstallLdapServer, \
    removeMultiMasterDeployement, installGluuServer

import clustermgr.tasks.cluster

cluster = Blueprint('cluster', __name__, template_folder='templates')


@cluster.route('/deployconfig/<int:server_id>', methods=['GET', 'POST'])
def deploy_config(server_id):
    s = Server.query.get(server_id)
    nextpage = 'index.multi_master_replication'
    whatNext = "LDAP Replication"
    if not s:
        flash("Server id {0} is not on database".format(server_id), 'warning')
        return redirect(url_for("index.multi_master_replication"))
    task = setupMmrServer.delay(server_id)
    head = "Setting up server: " + s.hostname
    return render_template("logger.html", heading=head, server=s,
                           task=task, nextpage=nextpage, whatNext=whatNext)


# FIXME Needs MMR cleanup
@cluster.route('/removedeployment')
def remove_deployment():
    server_id = int(request.values.get("server_id"))
    masterServer = server = Server.query.get(server_id)
    mmr = MultiMaster.query.all()

    for m in mmr:
        if not m.mmr_id == server_id:
            server = Server.query.get(m.mmr_id)
            ldp = ldapOLC('ldaps://{}:1636'.format(server.hostname),
                          "cn=config", server.ldap_password)
            r = None
            try:
                r = ldp.connect()
            except Exception as e:
                flash("Connection to LDAPserver {0} at port 1636 was failed:"
                      " {1}".format(server.hostname, e), "danger")

            if r:
                pd = ldp.getProviders()

                if masterServer.hostname in pd:
                    flash("This server is a provider for Ldap Server {0}."
                          " Please first remove this server as provider.".format(
                              masterServer.hostname), "warning")
                    return redirect(url_for('index.multi_master_replication'))

    task = removeMultiMasterDeployement.delay(server_id)
    print "TASK STARTED", task.id
    head = "Removing Deployment"
    nextpage = "index.multi_master_replication"
    whatNext = "Multi Master Replication"
    return render_template("logger.html", heading=head, server="",
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/installldapserver')
def install_ldap_server():

    task = InstallLdapServer.delay(session['nongluuldapinfo'])

    print "TASK STARTED", task.id
    head = "Installing Symas Open-Ldap Server on " + \
        session['nongluuldapinfo']['fqn_hostname']
    nextpage = "index.multi_master_replication"
    whatNext = "Multi Master Replication"
    return render_template("logger.html", heading=head, server="",
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/installgluuserver/<int:server_id>/')
def install_gluu_server(server_id):
    server = Server.query.get(server_id)
    appconf = AppConfiguration.query.first()

    task = installGluuServer.delay(server_id)

    print "Install Gluu Server TASK STARTED", task.id
    head = "Installing Gluu Server ({0}) on {1}".format(appconf.gluu_version, server.hostname)
    nextpage = "index.home"
    whatNext = "Dashboard"
    return render_template("logger.html", heading=head, server=server.hostname,
                           task=task, nextpage=nextpage, whatNext=whatNext)
