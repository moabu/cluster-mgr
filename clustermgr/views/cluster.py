"""A Flask blueprint with the views and the business logic dealing with
the servers managed in the cluster-manager
"""
from flask import Blueprint, render_template, url_for, flash, redirect, \
    request, session

from clustermgr.core.ldap_functions import LdapOLC
from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cluster import setup_ldap_replication, \
    InstallLdapServer, installGluuServer, remove_provider, \
    removeMultiMasterDeployement, installNGINX

cluster = Blueprint('cluster', __name__, template_folder='templates')


@cluster.route('/deploy_config/<int:server_id>', methods=['GET', 'POST'])
def deploy_config(server_id):
    s = Server.query.get(server_id)
    nextpage = 'index.multi_master_replication'
    whatNext = "LDAP Replication"
    if not s:
        flash("Server id {0} is not on database".format(server_id), 'warning')
        return redirect(url_for("index.multi_master_replication"))
    task = setup_ldap_replication.delay(server_id)
    head = "Setting up Replication on Server: " + s.hostname
    return render_template("logger.html", heading=head, server=s,
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/remove_deployment/<int:server_id>/')
def remove_deployment(server_id):
    
    #server = Server.query.get(server_id)
    #if server.mmr:
    #    remove_provider.delay(server.id)
    #return redirect(url_for('index.multi_master_replication'))

    thisServer = Server.query.get(server_id)
    servers = Server.query.filter(Server.id.isnot(server_id)).filter(
                                    Server.mmr.is_(True)).all()

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
            pd = ldp.getProviders()

            if thisServer.hostname in pd:
                flash("This server is a provider for Ldap Server {0}."
                      " Please first remove this server as provider.".format(
                          thisServer.hostname), "warning")
                return redirect(url_for('index.multi_master_replication'))

    task = removeMultiMasterDeployement.delay(server_id)
    print "TASK STARTED", task.id
    head = "Removing Deployment"
    nextpage = "index.multi_master_replication"
    whatNext = "Multi Master Replication"
    return render_template("logger.html", heading=head, server=thisServer,
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/install_ldapserver')
def install_ldap_server():

    task = InstallLdapServer.delay(session['nongluuldapinfo'])

    print "TASK STARTED", task.id
    head = "Installing Symas Open-Ldap Server on " + \
        session['nongluuldapinfo']['fqn_hostname']
    nextpage = "index.multi_master_replication"
    whatNext = "Multi Master Replication"
    return render_template("logger.html", heading=head, server="",
                           task=task, nextpage=nextpage, whatNext=whatNext)


@cluster.route('/install_gluu_server/<int:server_id>/')
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



@cluster.route('/installnginx/')
def install_nginx():
    
    appconf = AppConfiguration.query.first()

    task = installNGINX.delay(appconf.nginx_host)

    print "Install NGINX TASK STARTED", task.id
    head = "Installing NGINX Server on {0}".format(appconf.nginx_host)
    nextpage = "index.multi_master_replication"
    whatNext = "LDAP Replication"
    return render_template("logger.html", heading=head, server=appconf.nginx_host,
                           task=task, nextpage=nextpage, whatNext=whatNext)
