# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session
from flask import current_app as app
from celery.result import AsyncResult

from clustermgr.extensions import db, wlogger, celery
from clustermgr.models import AppConfiguration, Server

from clustermgr.forms import ServerForm

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
        return redirect(url_for('index.home'))
    return render_template('new_server.html', form=form)


@server.route('/remove/<int:server_id>/')
def remove(server_id):
    server = Server.query.filter_by(id=server_id).first()

    if server.mmr:
        # TODO remove its corresponding syncrepl configs from other servers
        # TODO LATER perform checks on ther flags and add their cleanup tasks
        pass

    db.session.delete(server)
    db.session.commit()

    flash("Server {0} is removed.".format(server.hostname), "success")
    return redirect(url_for('index.home'))
