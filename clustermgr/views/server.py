# -*- coding: utf-8 -*-

import os
import time

from flask import Blueprint, render_template, redirect, url_for, \
    flash, request, jsonify, current_app

from flask_login import login_required

from clustermgr.extensions import db
from clustermgr.models import Server, AppConfiguration

import ldap3

from clustermgr.forms import ServerForm, InstallServerForm, \
    SetupPropertiesLastForm
from clustermgr.tasks.server import collect_server_details

from clustermgr.tasks.server import task_install_gluu_server, task_test

from clustermgr.core.remote import RemoteClient, ClientNotSetupException
from ..core.license import license_required
from ..core.license import license_reminder
from ..core.license import prompt_license

from clustermgr.core.utils import parse_setup_properties, \
    write_setup_properties_file, get_setup_properties, \
    port_status_cmd, as_boolean, get_proplist

from clustermgr.core.ldap_functions import getLdapConn


server_view = Blueprint('server', __name__)
server_view.before_request(prompt_license)
server_view.before_request(license_required)
server_view.before_request(license_reminder)


def sync_ldap_passwords(password):
    non_primary_servers = Server.query.filter(
        Server.primary_server.isnot(True)).all()
    for server in non_primary_servers:
        server.ldap_password = password
    db.session.commit()


@server_view.route('/', methods=['GET', 'POST'])
@login_required
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
    header = "New Server"
    primary_server = Server.query.filter(
        Server.primary_server.is_(True)).first()

    if primary_server:
        del form.ldap_password
        del form.ldap_password_confirm
    else:
        header = "New Server - Primary Server"

    if form.validate_on_submit():
        
        server = Server()
        server.hostname = form.hostname.data.strip()
        server.ip = form.ip.data.strip()
        server.ssh_port = form.ssh_port.data
        print(("SSH Port", server.ssh_port))
        server.mmr = False
        ask_passphrase = False

        server_exist = Server.query.filter_by(
                    hostname=server.hostname).first()

        if server_exist:
            flash("Server with hostname {} is already in cluster".format(
                server_exist.hostname), "warning")
            return redirect(url_for('index.home'))

        c = RemoteClient(server.hostname, server.ip, ssh_port=server.ssh_port)
        try:
            c.startup()

        except ClientNotSetupException as e:

            if str(e) == 'Pubkey is encrypted.':
                ask_passphrase = True
                flash("Pubkey seems to password protected. "
                    "After setting your passphrase re-submit this form.",
                    'warning')
            elif str(e) == 'Could not deserialize key data.':
                ask_passphrase = True
                flash("Password you provided for pubkey did not work. "
                    "After setting your passphrase re-submit this form.",
                    'warning')
            else:
                flash("SSH connection to {} failed. Please check if your pub key is "
                    "added to /root/.ssh/authorized_keys on this server. Reason: {}".format(
                                                    server.hostname, e), 'error')

        
        #except:
        #    flash("SSH connection to {} failed. Please check if your pub key is "
        #        "added to /root/.ssh/authorized_keys on this server".format(
        #                                            server.hostname))
        
            print("ask_passphrase", ask_passphrase)
        
            return render_template('new_server.html',
                       form=form,
                       header=header,
                       server_id=None,
                       ask_passphrase=ask_passphrase,
                       next=url_for('server.index')
                       )
        
        if primary_server:
            server.ldap_password = primary_server.ldap_password
        else:
            server.ldap_password = form.ldap_password.data.strip()
            server.primary_server = True
        
        if not server.hostname == appconfig.nginx_host:
            db.session.add(server)
            db.session.commit()
            # start the background job to get system details
            collect_server_details.delay(server.id)
            return redirect(url_for('index.home'))

        else:
            flash("Load balancer can't be used as gluu server", 'danger')


    return render_template('new_server.html',
                           form=form,
                           header=header,
                           server_id=None)


@server_view.route('/edit/<int:server_id>/', methods=['GET', 'POST'])
@login_required
def edit(server_id):
    server = Server.query.get(server_id)
    if not server:
        flash('There is no server with the ID: %s' % server_id, "warning")
        return redirect(url_for('index.home'))

    form = ServerForm()
    header = "Update Server Details"
    if server.primary_server:
        header = "Update Primary Server Details"
        if request.method == 'POST' and not form.ldap_password.data.strip():
            form.ldap_password.data = '**dummy**'
            form.ldap_password_confirm.data = '**dummy**'
    else:
        del form.ldap_password
        del form.ldap_password_confirm

    if form.validate_on_submit():
        server.hostname = form.hostname.data.strip()
        server.ip = form.ip.data.strip()
        server.ssh_port = form.ssh_port.data
        
        if server.primary_server and form.ldap_password.data != '**dummy**':
            server.ldap_password = form.ldap_password.data.strip()
            sync_ldap_passwords(server.ldap_password)
        db.session.commit()
        # start the background job to get system details
        collect_server_details.delay(server.id)
        return redirect(url_for('index.home'))

    form.hostname.data = server.hostname
    form.ip.data = server.ip
    form.ssh_port.data = server.ssh_port
    if server.primary_server:
        form.ldap_password.data = server.ldap_password

    return render_template('new_server.html', form=form, header=header)


@server_view.route('/remove/<int:server_id>')
@login_required
def remove_server(server_id):

    appconfig = AppConfiguration.query.first()
    server = Server.query.filter_by(id=server_id).first()
    all_servers = Server.get_all()
    
    if len(all_servers) > 1:
        if server.primary_server:
            flash("Please first remove non-primary servers ", "danger")
            return redirect(url_for('index.home'))

    if (not server.gluu_server) or (request.args.get('removefromdashboard') == 'true'):
        db.session.delete(server)
        db.session.commit()
        flash("Server {0} is removed.".format(server.hostname), "success")

        return redirect(url_for('index.home'))


    disable_replication = True if request.args.get('disablereplication') == \
                               'true' else False

    return redirect(url_for('cluster.remove_server_from_cluster_view',
                                server_id=server_id, removeserver=True,
                                disablereplication=disable_replication,
                                next='dashboard',
                                ))

 
    # TODO LATER perform checks on ther flags and add their cleanup tasks

    return redirect(url_for('index.home'))


@server_view.route('/installgluu/<int:server_id>/', methods=['GET', 'POST'])
@login_required
def install_gluu(server_id):
    """Gluu server installation view. This function creates setup.properties
    file and redirects to install_gluu_server which does actual installation.
    """

    # If current server is not primary server, first we should identify
    # primary server. If primary server is not installed then redirect
    # to home to install primary.
    pserver = Server.query.filter_by(primary_server=True).first()
    if not pserver:
        flash("Please identify primary server before starting to install Gluu "
              "Server.", "warning")
        return redirect(url_for('index.home'))

    server = Server.query.get(server_id)

    # We need os type to perform installation. If it was not identified,
    # return to home and wait until it is identifed.
    if not server.os:
        flash("Server OS version hasn't been identified yet. Checking Now",
              "warning")
        collect_server_details.delay(server_id)
        return redirect(url_for('index.home'))

    # If current server is not primary server, and primary server was installed,
    # start installation by redirecting to cluster.install_gluu_server
    if not server.primary_server:

        return redirect(url_for('server.install_gluu_server',
                                server_id=server_id))

    # If we come up here, it is primary server and we will ask admin which
    # components will be installed. So prepare form by InstallServerForm
    appconf = AppConfiguration.query.first()
    form = InstallServerForm()

    # We don't require these for server installation. These fields are required
    # for adding new server.
    del form.hostname
    del form.ip_address
    del form.ldap_password

    if appconf.gluu_version >= '4.3.0':
        del form.installOxAuthRP


    header = 'Install Gluu Server on {0}'.format(server.hostname)

    # Get default setup properties.
    setup_prop = get_setup_properties()

    setup_prop['hostname'] = appconf.nginx_host
    setup_prop['ip'] = server.ip
    setup_prop['ldapPass'] = server.ldap_password

    services = ['installOxAuth',
              'installOxTrust',
              'installLdap',
              'installHTTPD',
              'installSaml',
              'installOxAuthRP',
              'installPassport',
              'installOxd',
              'installCasa',
              ]

    if appconf.gluu_version >= '4.3.0':
        services.remove('installOxAuthRP')

    # If form is submitted and validated, create setup.properties file.
    if form.validate_on_submit():
        setup_prop['countryCode'] = form.countryCode.data.strip()
        setup_prop['state'] = form.state.data.strip()
        setup_prop['city'] = form.city.data.strip()
        setup_prop['orgName'] = form.orgName.data.strip()
        setup_prop['admin_email'] = form.admin_email.data.strip()
        setup_prop['application_max_ram'] = str(form.application_max_ram.data)



        for o in services + ['application_max_ram', 'oxd_use_gluu_storage']:
            setup_prop[o] = getattr(form, o).data
        setup_prop['ldap_type'] = 'opendj'
        setup_prop['opendj_type'] = 'wrends'
        setup_prop['installJce'] = True
        setup_prop['installLdap'] = True
        setup_prop['oxd_server_https'] = 'https://localhost:8443'
        setup_prop['clustering'] = True

        if setup_prop['installCasa']:
            setup_prop['installOxd'] = True

        write_setup_properties_file(setup_prop)

        # Redirect to cluster.install_gluu_server to start installation.
        
        return redirect(url_for('server.confirm_setup_properties', server_id=server_id))
        
        #return redirect(url_for('cluster.install_gluu_server',
        #                        server_id=server_id))

    # If this view is requested, rather than post, display form to
    # admin to determaine which elements to be installed.
    if request.method == 'GET':
        form.countryCode.data = setup_prop['countryCode']
        form.state.data = setup_prop['state']
        form.city.data = setup_prop['city']
        form.orgName.data = setup_prop['orgName']
        form.admin_email.data = setup_prop['admin_email']
        form.application_max_ram.data = setup_prop['application_max_ram']
        form.oxd_use_gluu_storage = setup_prop['oxd_use_gluu_storage']

        for o in services:
            print(o)
            getattr(form, o).data = as_boolean(setup_prop.get(o, ''))

    form['application_max_ram'].data = setup_prop['application_max_ram']

    setup_properties_form = SetupPropertiesLastForm()

    return render_template('new_server.html',
                           form=form,
                           server_id=server_id,
                           setup_properties_form=setup_properties_form,
                           header=header)


@server_view.route('/uploadsetupproperties/<int:server_id>', methods=['POST'])
def upload_setup_properties(server_id):
    setup_properties_form = SetupPropertiesLastForm()

    if setup_properties_form.upload.data and \
            setup_properties_form.validate_on_submit():

        f = setup_properties_form.setup_properties.data
        try:
            setup_prop = parse_setup_properties(f.stream)
        except:
            flash("Can't parse, please upload valid setup.properties file.",
                    "danger")
            return redirect(url_for('install_gluu', server_id=1))
            
        for prop in (
                    'countryCode', 'orgName', 'application_max_ram', 'city',
                    'state', 'admin_email'):

            if not prop in setup_prop:
                flash("'{0}' is missing, please upload valid setup.properties file.".format(prop),
                "danger")
                return redirect(url_for('server.install_gluu', server_id=1))

        for rf in get_proplist():
            if rf in setup_prop:
                del setup_prop[rf]

        appconf = AppConfiguration.query.first()
        server = Server.query.get(server_id)

        setup_prop['hostname'] = appconf.nginx_host
        setup_prop['ip'] = server.ip
        setup_prop['ldapPass'] = server.ldap_password
        setup_prop['ldap_type'] = 'opendj'
        
        write_setup_properties_file(setup_prop)

        flash("Setup properties file has been uploaded sucessfully. ",
              "success")

        return redirect(url_for('server.confirm_setup_properties', server_id=server_id))
        
        #return redirect(url_for('cluster.install_gluu_server',
        #                       server_id=server_id))
    else:
        flash("Please upload valid setup properties file", "danger")

        
        
        return redirect(url_for('server.install_gluu', server_id=server_id))


@server_view.route('/confirmproperties/<int:server_id>/', methods=['GET'])
@login_required
def confirm_setup_properties(server_id):

    setup_prop = get_setup_properties()

    appconf = AppConfiguration.query.first()
    server = Server.query.get(server_id)

    setup_prop['hostname'] = appconf.nginx_host
    setup_prop['ip'] = server.ip
    setup_prop['ldapPass'] = server.ldap_password

    if appconf.gluu_version >= '4.3.0':
        del setup_prop['installOxAuthRP']

    keys = list(setup_prop.keys())
    keys.sort()

    return render_template(
                        'server_confirm_properties.html',
                        server_id = server_id,
                        setup_prop = setup_prop,
                        keys = keys,
                    )



@server_view.route('/ldapstat/<int:server_id>/')
def get_ldap_stat(server_id):

    server = Server.query.get(server_id)
    if server:
        try:
            ldap_server = ldap3.Server('ldaps://{}:1636'.format(server.hostname))
            conn = ldap3.Connection(ldap_server)
            if conn.bind(): 
                return "1"
        except:
            pass
    return "0"


def test_port(server, client, port, port_status_cmd):
    
    try:
        channel = server.client.get_transport().open_session()
        channel.get_pty()
        cmd = '''python -c "import time, socket;sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.bind(('{}', {})); sock.listen(5); time.sleep(20)"'''.format(server.ip, port)

        if server.use_py3:
            cmd = cmd.replace('python', 'python3')

        channel.exec_command(cmd)

        i = 1
        while True:
            if channel.exit_status_ready():
                break
            time.sleep(0.1)
            cmd2 = port_status_cmd.format(server.ip, port)
            if client.use_py3:
                cmd2 = cmd2.replace('python', 'python3')

            r = client.run(cmd2)
            if r[1].strip()=='0':
                return True
            i += 1
            if i > 5:
                break
    except Exception as e:
        print(e)
        return False


@server_view.route('/dryrun/<int:server_id>')
def dry_run(server_id):

    #return jsonify({'nginx': {'port_status': {7777: True, 1636: True, 80: True, 30865: True, 1689: True, 443: True, 4444: False, 8989: True}, 'ssh': True}, 'server': {'port_status': {7777: True, 1636: True, 80: True, 30865: True, 1689: True, 443: True, 4444: False, 8989: False}, 'ssh': True}})
    
    
    result = {'server':{'ssh':False, 'port_status':{}}, 'nginx':{'ssh':False, 'port_status':{}}}
    server_ports = [16379, 443, 4444, 1636, 80, 8989, 30865]
    
    for p in server_ports:
        result['nginx']['port_status'][p] = False
        result['server']['port_status'][p] = False
    
    server = Server.query.get(server_id)
    appconf = AppConfiguration.query.first()

    c = RemoteClient(server.hostname, server.ip, ssh_port=server.ssh_port)

    try:
        c.startup()
        result['server']['ssh']=True
    except Exception as e:
        print(e)
        pass

    c.use_py3 = False
    if c.run('which python3')[1].strip():
        c.use_py3 = True

    if result['server']['ssh']:
        #Test is any process listening ports that will be used by gluu-server
        for p in server_ports:
            cmd = port_status_cmd.format(server.ip, p)
            if c.use_py3:
                cmd = cmd.replace('python', 'python3')
            r = c.run(cmd)
            if r[1].strip()=='0':
                result['server']['port_status'][p] = True

        ssh_port = 22
        if appconf.external_load_balancer:
            c_host = appconf.cache_host
            c_ip = appconf.cache_ip
        else:
            c_host = appconf.nginx_host
            c_ip = appconf.nginx_ip
            ssh_port = appconf.nginx_ssh_port

        c_nginx = RemoteClient(c_host, c_ip, ssh_port=ssh_port)
        try:
            c_nginx.startup()
            result['nginx']['ssh']=True
        except Exception as e:
            print(e)

        c_nginx.use_py3 = False
        if c_nginx.run('which python3')[1].strip():
            c_nginx.use_py3 = True

        if result['nginx']['ssh']:
            for p in server_ports:
                if not result['server']['port_status'][p]:
                    r = test_port(c, c_nginx, p, port_status_cmd=port_status_cmd)
                    if r:
                        result['nginx']['port_status'][p] = True
                else:
                    cmd = port_status_cmd.format(server.ip, p)
                    if c_nginx.use_py3:
                        cmd = cmd.replace('python', 'python3')
                    r = c_nginx.run(cmd)
                    if r[1].strip()=='0':
                        result['nginx']['port_status'][p] = True

    return jsonify(result)


@server_view.route('/makeprimary/<int:server_id>', methods=['GET'])
@login_required
def make_primary(server_id):
    cur_primary = Server.query.filter_by(primary_server=True).first()
    
    if cur_primary:
        cur_primary.primary_server = None
    server = Server.query.get(server_id)
    
    if server:
        server.primary_server = True
    
    db.session.commit()
    
    flash("Server {} was set as Primary Server".format(server.hostname), "info")
    
    return redirect(url_for('index.home'))


@server_view.route('/installgluuserver/<int:server_id>/', methods=['GET'])
@login_required
def install_gluu_server(server_id):
    
    print("Installing Gluu Server")
    
    task = task_install_gluu_server.delay(server_id)
    
    steps = ['Perpare Server', 'Install Gluu Container', 'Run setup.py', 'Post Installation']

    server = Server.query.get(server_id)

    title = "Installing Gluu Server on " + server.hostname

    nextpage = url_for('index.home')
    whatNext = "Dashboard"

    return render_template('logger_single.html',
                           server_id=server_id,
                           title=title,
                           steps=steps,
                           task=task,
                           cur_step=1,
                           auto_next=True,
                           multistep=True,
                           nextpage=nextpage,
                           whatNext=whatNext
                           )


@server_view.route('/test', methods=['GET'])
def test_view():
    print("Test View")
    
    task = task_test.delay()
    
    steps = ['Perpare Server', 'Install Gluu Container', 'Run setup.py', 'Post Installation']

    server = Server.query.first()
    servers = Server.get_all()
    title = "You should not come this page!!!"

    nextpage = url_for('index.home')
    whatNext = "Dashboard"

    return render_template('logger_single.html',
                           title=title,
                           steps=steps,
                           task=task,
                           cur_step=2,
                           auto_next=False,
                           multiserver=servers,
                           nextpage=nextpage,
                           whatNext=whatNext
                           )

@server_view.route('/getostype', methods=['GET'])
@login_required
def get_os_type():
    servers = Server.get_all()

    data = {}
    for server in servers:
        data[str(server.id)] = server.os

    return jsonify(data)
