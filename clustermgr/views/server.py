# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request

from clustermgr.extensions import db
from clustermgr.models import Server, AppConfiguration

from clustermgr.forms import ServerForm
from clustermgr.views.index import get_primary_server_id
from clustermgr.tasks.cluster import remove_provider

server = Blueprint('server', __name__)


@server.route('/', methods=['GET', 'POST'])
def index():
    """Route for URL /server/. GET returns ServerForm to add a server,
    POST accepts the ServerForm, validates and creates a new Server object
    """
    appconfig = AppConfiguration.query.first()
    if not appconfig:
        flash("Kindly set default values for the application before adding"
              " servers.", "info")
        return redirect(url_for('index.app_configuration', next="/server/"))
    form = ServerForm()

    if form.validate_on_submit():
        server = Server()
        server.gluu_server = form.gluu_server.data
        server.hostname = form.hostname.data
        server.ip = form.ip.data
        server.ldap_password = form.ldap_password.data
        server.mmr = False

        db.session.add(server)
        db.session.commit()
        # TODO start the background job to get system details
        return redirect(url_for('index.home'))
    flash('Cluster Manager will connect to this server via SSH to perform its'
          ' tasks. Ensure the server running Cluster Manager has'
          '"Password-less" SSH access via shared keys to the server.', 'info')
    return render_template('new_server.html', form=form, header="New Server")


@server.route('/edit/<int:server_id>', methods=['GET', 'POST'])
def edit(server_id):
    server = Server.query.get(server_id)
    if not server:
        flash('There is no server with the ID: %s' % server_id, "warning")
        return redirect(url_for('index.home'))

    form = ServerForm()

    pr_server = get_primary_server_id()

    if pr_server:
        if not get_primary_server_id() == server_id:
            form.primary_server.render_kw = {'disabled': 'disabled'}

    if request.method == 'POST' and not form.ldap_password.data:
        form.ldap_password.data = '**dummy**'

    if form.validate_on_submit():
        server.gluu_server = form.gluu_server.data
        server.hostname = form.hostname.data
        server.ip = form.ip.data
        server.primary_server = form.primary_server.data
        if form.ldap_password.data is not '**dummy**':
            server.ldap_password = form.ldap_password.data
        db.session.commit()
        return redirect(url_for('index.home'))

    form.gluu_server.data = server.gluu_server
    form.hostname.data = server.hostname
    form.ip.data = server.ip
    form.ldap_password.data = server.ldap_password
    form.primary_server.data = server.primary_server
    return render_template('new_server.html', form=form,
                           header="Update Server Details")


@server.route('/remove/<int:server_id>/')
def remove(server_id):
    server = Server.query.filter_by(id=server_id).first()
    # remove its corresponding syncrepl configs from other servers
    if server.mmr:
        remove_provider.delay(server.id)
    # TODO LATER perform checks on ther flags and add their cleanup tasks
    db.session.delete(server)
    db.session.commit()

    flash("Server {0} is removed.".format(server.hostname), "success")
    return redirect(url_for('index.home'))
