# -*- coding: utf-8 -*-

import os
import uuid

from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, session

from clustermgr.extensions import db
from clustermgr.models import Server, AppConfiguration

from clustermgr.forms import ServerForm, InstallServerForm
from clustermgr.views.index import get_primary_server_id
from clustermgr.tasks.cluster import remove_provider, collect_server_details
from clustermgr.config import Config

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

        # start the background job to get system details
        collect_server_details.delay(server.id)
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

def getQuad():
    return str(uuid.uuid4())[:4].upper()

def getInums():

    baseInum = '@!%s.%s.%s.%s' % tuple([getQuad() for i in xrange(4)])
    orgTwoQuads = '%s.%s' % tuple([getQuad() for i in xrange(2)])
    inumOrg = '%s!0001!%s' % (baseInum, orgTwoQuads)
    applianceTwoQuads = '%s.%s' % tuple([getQuad() for i in xrange(2)])
    inumAppliance = '%s!0002!%s' % (baseInum, applianceTwoQuads)

    return inumOrg, inumAppliance


def getSetupProperties():
    setupProp={
                'hostname':'',
                'orgName':'',
                'countryCode':'',
                'city':'',
                'state':'',
                'jksPass':'',
                'inumOrg':'',
                'inumAppliance':'',
                'admin_email':'',
                'ip':'',
            }

    setup_properties_file = os.path.join(Config.DATA_DIR, 'setup.properties')
    if os.path.exists(setup_properties_file):
        for l in open(setup_properties_file):
            ls = l.strip().split('=')
            if ls:
                setupProp[ls[0]]=ls[1]
    
    if not setupProp['inumOrg']:
        inumOrg, inumAppliance = getInums()
        setupProp['inumOrg'] = inumOrg
        setupProp['inumAppliance'] = inumAppliance

    return setupProp



@server.route('/installgluu/<int:server_id>/', methods=['GET','POST'])
def install_gluu(server_id):

    server = Server.query.get(server_id)
    appconf = AppConfiguration.query.first()
    form = InstallServerForm()

    del form.hostname
    del form.ip_address
    del form.ldap_password
    header =  'Install Gluu Server on {0}'.format(server.hostname)

    setup_prop = getSetupProperties()

    setup_prop['hostname']  = appconf.nginx_host
    setup_prop['ip']        = server.ip
    setup_prop['ldapPass']  = server.ldap_password


    if request.method == 'POST':
        if form.validate_on_submit():

            setup_prop['countryCode'] = form.countryCode.data
            setup_prop['state']       = form.state.data
            setup_prop['city']        = form.city.data
            setup_prop['orgName']     = form.orgName.data
            setup_prop['admin_email'] = form.admin_email.data

            setup_properties_file = os.path.join(Config.DATA_DIR, 'setup.properties')

            with open(setup_properties_file,'w') as f:
                for k,v in setup_prop.items():
                    f.write('{0}={1}\n'.format(k,v))

            return redirect(url_for('cluster.install_gluu_server',server_id=server_id))
        
    else:
        form.countryCode.data = setup_prop['countryCode']
        form.state.data       = setup_prop['state']
        form.city.data        = setup_prop['city']
        form.orgName.data     = setup_prop['orgName']
        form.admin_email.data = setup_prop['admin_email']

    return render_template('new_server.html', form=form,  header=header)
