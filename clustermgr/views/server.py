# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session
from flask import current_app as app
from celery.result import AsyncResult

from clustermgr.extensions import db, wlogger, celery
from clustermgr.models import AppConfiguration, Server

from clustermgr.forms import ServerForm
from clustermgr.views.index import get_primary_server_id

# from clustermgr.core.ldap_functions import ldapOLC

server = Blueprint('server', __name__)


@server.route('/', methods=['GET', 'POST'])
def index():
    """Route for URL /server/. GET returns ServerForm to add a server,
    POST accepts the ServerForm, validates and creates a new Server object
    """
    form = ServerForm()

    if form.validate_on_submit():
        server = Server()
        server.gluu_server = form.gluu_server.data
        server.hostname = form.hostname.data
        server.ip = form.ip.data
        server.ldap_password = form.ldap_password.data

        db.session.add(server)
        db.session.commit()
        # TODO start the background job to get system details
        return redirect(url_for('index.home'))
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

    if server.mmr:
        # OLC don't allw this!!! - MB
        # TODO remove its corresponding syncrepl configs from other servers
        # TODO LATER perform checks on ther flags and add their cleanup tasks
        
        flash("Server {0} is a member of multi master replication, "
              "can't remove. You should remove deployement to remove.".format(server.hostname),
              "warning")
    elif server.primary_server:
        flash("Server {0} is Primary Server, can't remove.".format(server.hostname),
              "warning")
    else:
        db.session.delete(server)
        db.session.commit()

        flash("Server {0} is removed.".format(server.hostname), "success")
    return redirect(url_for('index.home'))
