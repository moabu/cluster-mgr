# -*- coding: utf-8 -*-

import os
import uuid

from flask import Blueprint, render_template, redirect, url_for, flash, \
    request

from clustermgr.extensions import db
from clustermgr.models import Server, AppConfiguration

from clustermgr.forms import ServerForm, InstallServerForm
from clustermgr.views.index import get_primary_server_id
from clustermgr.tasks.cluster import remove_provider, collect_server_details
from clustermgr.config import Config
from clustermgr.core.remote import RemoteClient, ClientNotSetupException

server_view = Blueprint('server', __name__)

def sync_ldap_passwords(password):
    non_primary_servers = Server.query.filter(Server.primary_server.isnot(True)).all()
    for server in non_primary_servers:
        server.ldap_password = password
    db.session.commit()

def get_primary_server_password():
    primary_server =  Server.query.filter_by(primary_server=True).first()
    if primary_server:
        return primary_server.ldap_password

@server_view.route('/', methods=['GET', 'POST'])
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

    header="New Server"

    pr_server = get_primary_server_id()
    
    
    if not pr_server:
         header="New Server - Primary Server"
    else:
        del form.ldap_password
        del form.ldap_password_confirm

    if form.validate_on_submit():
        server = Server()
        server.hostname = form.hostname.data.strip()
        server.ip = form.ip.data.strip()
        server.mmr = False
        if not pr_server:
            server.ldap_password = form.ldap_password.data.strip()
            server.primary_server = True
        else:
            server.ldap_password = get_primary_server_password()

        db.session.add(server)
        db.session.commit()

        # start the background job to get system details
        collect_server_details.delay(server.id)
        return redirect(url_for('index.home'))

    return render_template('new_server.html', form=form, header=header)


@server_view.route('/edit/<int:server_id>/', methods=['GET', 'POST'])
def edit(server_id):
    server = Server.query.get(server_id)
    if not server:
        flash('There is no server with the ID: %s' % server_id, "warning")
        return redirect(url_for('index.home'))

    is_this_primary = get_primary_server_id() == server_id
    form = ServerForm()

    pr_server = get_primary_server_id()

    header="Update Server Details"

    if not pr_server:
        header="Update Primary Server Details"

    if pr_server:
        if is_this_primary:
            header="Update Primary Server Details"
            if request.method == 'POST' and not form.ldap_password.data.strip():
                form.ldap_password.data = '**dummy**'
                form.ldap_password_confirm.data = '**dummy**'
        else:
            del form.ldap_password
            del form.ldap_password_confirm


    if form.validate_on_submit():
        server.hostname = form.hostname.data.strip()
        server.ip = form.ip.data.strip()
        if is_this_primary:
            if form.ldap_password.data and form.ldap_password_confirm.data is not '**dummy**':
                server.ldap_password = form.ldap_password.data.strip()
                sync_ldap_passwords(server.ldap_password)
        db.session.commit()
        # start the background job to get system details
        collect_server_details.delay(server.id)
        return redirect(url_for('index.home'))

    form.hostname.data = server.hostname
    form.ip.data = server.ip
    if is_this_primary:
        form.ldap_password.data = server.ldap_password
    
    return render_template('new_server.html', form=form, server=True,
                           header=header)


@server_view.route('/remove/<int:server_id>/')
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


def get_quad():
    return str(uuid.uuid4())[:4].upper()


def get_inums():
    base_inum = '@!%s.%s.%s.%s' % tuple([get_quad() for _ in xrange(4)])
    org_two_quads = '%s.%s' % tuple([get_quad() for _ in xrange(2)])
    inum_org = '%s!0001!%s' % (base_inum, org_two_quads)
    appliance_two_quads = '%s.%s' % tuple([get_quad() for _ in xrange(2)])
    inum_appliance = '%s!0002!%s' % (base_inum, appliance_two_quads)
    return inum_org, inum_appliance


def get_setup_properties():
    setup_prop = {
        'hostname': '',
        'orgName': '',
        'countryCode': '',
        'city': '',
        'state': '',
        'jksPass': '',
        'inumOrg': '',
        'inumAppliance': '',
        'admin_email': '',
        'ip': '',
        'installOxAuth':True,
        'installOxTrust':True,
        'installLDAP':True,
        'installHTTPD':True,
        'installJce':True,
        'installSaml':False,
        'installAsimba':False,
        'installCas':False,
        'installOxAuthRP':False,
        'installPassport':False,
        }

    setup_properties_file = os.path.join(Config.DATA_DIR, 'setup.properties')
    if os.path.exists(setup_properties_file):
        for l in open(setup_properties_file):
            ls = l.strip().split('=')
            if ls:
                k,v = tuple(ls)
                if v == 'True':
                    v = True
                elif v == 'False':
                    v = False
                setup_prop[k] = v
    
    
    inum_org, inum_appliance = get_inums()
    setup_prop['inumOrg'] = inum_org
    setup_prop['inumAppliance'] = inum_appliance

    return setup_prop


@server_view.route('/installgluu/<int:server_id>/', methods=['GET', 'POST'])
def install_gluu(server_id):
    pserver = Server.query.filter_by(primary_server=True).first()
    if not pserver:
        flash("Please identify primary server before starting to install Gluu "
              "Server.", "warning")
        return redirect(url_for('index.home')) 

    

    #if not (server_id == pserver.id or pserver.gluu_server):
    #    flash("Please first install primary server.", "warning")
    #    return redirect(url_for('index.home')) 


    server = Server.query.get(server_id)
    
    if not server.primary_server:
        return redirect(url_for('cluster.install_gluu_server',
                                server_id=server_id))
    
    
    if not server.os:
        flash("Server OS version hasn't been identified yet. Checking Now",
              "warning")
        
        collect_server_details(server_id, True)
        
        return redirect(url_for('index.home'))
    
    appconf = AppConfiguration.query.first()
    form = InstallServerForm()

    del form.hostname
    del form.ip_address
    del form.ldap_password
    header = 'Install Gluu Server on {0}'.format(server.hostname)

    setup_prop = get_setup_properties()

    setup_prop['hostname'] = appconf.nginx_host
    setup_prop['ip'] = server.ip
    setup_prop['ldapPass'] = server.ldap_password

    if form.validate_on_submit():
        setup_prop['countryCode'] = form.countryCode.data.strip()
        setup_prop['state'] = form.state.data.strip()
        setup_prop['city'] = form.city.data.strip()
        setup_prop['orgName'] = form.orgName.data.strip()
        setup_prop['admin_email'] = form.admin_email.data.strip()
        setup_prop['inumOrg'] = form.inumOrg.data.strip()
        setup_prop['inumAppliance'] = form.inumAppliance.data.strip()
        for o in ('installOxAuth',
                    'installOxTrust',
                    'installLDAP',
                    'installHTTPD',
                    'installJce',
                    'installSaml',
                    'installAsimba',
                    'installCas',
                    'installOxAuthRP',
                    'installPassport',

                    ):
            setup_prop[o] = getattr(form, o).data


        setup_properties_file = os.path.join(Config.DATA_DIR,
                                             'setup.properties')

        with open(setup_properties_file, 'w') as f:
            for k, v in setup_prop.items():
                f.write('{0}={1}\n'.format(k, v))

        return redirect(url_for('cluster.install_gluu_server',
                                server_id=server_id))
        
    if request.method == 'GET':
        form.countryCode.data = setup_prop['countryCode']
        form.state.data = setup_prop['state']
        form.city.data = setup_prop['city']
        form.orgName.data = setup_prop['orgName']
        form.admin_email.data = setup_prop['admin_email']
        form.inumOrg.data = setup_prop['inumOrg']
        form.inumAppliance.data = setup_prop['inumAppliance'] 
        
        for o in ('installOxAuth',
                    'installOxTrust',
                    'installLDAP',
                    'installHTTPD',
                    'installJce',
                    'installSaml',
                    'installAsimba',
                    'installCas',
                    'installOxAuthRP',
                    'installPassport',
                    ):
            getattr(form, o).data = setup_prop[o]
        
    return render_template('new_server.html', form=form,  header=header)


@server_view.route('/editslapdconf/<int:server_id>/', methods=['GET', 'POST'])
def edit_slapd_conf(server_id):
    server = Server.query.get(server_id)
    appconf = AppConfiguration.query.first()
    
    if not server:
        print "Yoook"
        flash("No such server.", "warning")
        return redirect(url_for('index.home'))

    if not server.gluu_server:
        chroot = '/'
    else:
        chroot = '/opt/gluu-server-' + appconf.gluu_version
        
    c = RemoteClient(server.hostname, ip=server.ip)
    try:
        c.startup()
    except ClientNotSetupException as e:
        flash(str(e), "danger")
        return redirect(url_for('index.home'))

    slapd_conf_file = os.path.join(chroot, 'opt/symas/etc/openldap/slapd.conf')
    
    if request.method == 'POST':
    
        config = request.form.get('conf')
        r = c.put_file(slapd_conf_file, config)
        if not r[0]:
            flash("Cant' saved to server: {0}".format(r[1]), "danger")
        else:
            flash('File {0} was saved on {1}'.format(slapd_conf_file,
                                                     server.hostname))
            return redirect(url_for('index.home'))
            
    r = c.get_file(slapd_conf_file)
    
    if not r[0]:
        flash("Cant't get file {0}: {1}".format(slapd_conf_file, r[1]),
              "success")
        return redirect(url_for('index.home'))
    
    config = r[1].read()

    return render_template('conf_editor.html', config=config,
                           hostname=server.hostname)


