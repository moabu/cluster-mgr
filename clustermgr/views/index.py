# -*- coding: utf-8 -*-
import os
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session
from flask import current_app as app
from werkzeug.utils import secure_filename
from celery.result import AsyncResult

from clustermgr.extensions import db, wlogger, celery
from clustermgr.models import AppConfiguration, KeyRotation, \
    Server

from clustermgr.forms import AppConfigForm, KeyRotationForm, SchemaForm, \
    ServerForm, TestUser, InstallServerForm

from clustermgr.core.ldap_functions import ldapOLC

from clustermgr.tasks.all import rotate_pub_keys
from clustermgr.core.utils import encrypt_text
from clustermgr.core.utils import generate_random_key
from clustermgr.core.utils import generate_random_iv

index = Blueprint('index', __name__)


@index.route('/')
def home():
    if 'nongluuldapinfo' in session:
        del session['nongluuldapinfo']
    servers = []
    config = {}
    print(config, servers)

    ldaps = Server.query.all()

    gluu_server = 0
    nongluu_server = 0
    for s in ldaps:
        if s.gluu_server:
            gluu_server += 1
        else:
            nongluu_server += 1

    pr_server = get_primary_server_id()

    data = {"ldapservers": ldaps, 'nongluu_server': nongluu_server,
            'gluu_server': gluu_server, 'pr_server':pr_server}

    return render_template('dashboard.html', data=data)


@index.route('/configuration/', methods=['GET', 'POST'])
def app_configuration():
    conf_form = AppConfigForm()
    sch_form = SchemaForm()
    config = AppConfiguration.query.first()
    schemafiles = os.listdir(app.config['SCHEMA_DIR'])

    ldaps = Server.query.all()

    if not ldaps:
        flash("Please go to Dahsboard and add LDAP Servers.", "warning")

    if request.method == "GET":
        
        if config:
        
            if config.gluu_version:
                conf_form.gluu_version.default = config.gluu_version
            
            if config.use_ip:
                conf_form.use_ip.default = config.use_ip
                
            conf_form.process()
        
    if conf_form.update.data and conf_form.validate_on_submit():
        if not config:
            config = AppConfiguration()
        else:
            if config.replication_dn != conf_form.replication_pw.data or replication_pw !=onf_form.replication_dn.data:
                flash('Previously deployed replications fail due to change in "Replication Manager DN"'
                        'or "Replication Manager Password". You need to Remove/Add providers', "danger")
                
        config.replication_dn = conf_form.replication_dn.data
        config.replication_pw = conf_form.replication_pw.data
        config.gluu_version = conf_form.gluu_version.data
        config.use_ip = conf_form.use_ip.data
        
        db.session.add(config)
        db.session.commit()
        flash("Gluu Replication Manager application configuration has been "
              "updated.", "success")
        if request.args.get('next'):
            return redirect(request.args.get('next'))

    elif sch_form.upload.data and sch_form.validate_on_submit():
        f = sch_form.schema.data
        filename = secure_filename(f.filename)
        if any(filename in s for s in schemafiles):
            name, extension = os.path.splitext(filename)
            matches = [s for s in schemafiles if name in s]
            filename = name + "_" + str(len(matches)) + extension
        f.save(os.path.join(app.config['SCHEMA_DIR'], filename))
        schemafiles.append(filename)
        flash("Schema: {0} has been uploaded sucessfully.".format(filename),
              "success")

    if config and config.replication_dn:
        conf_form.replication_dn.data = config.replication_dn
        conf_form.replication_pw.data = config.replication_pw

    return render_template('app_config.html', cform=conf_form, sform=sch_form,
                           config=config, schemafiles=schemafiles,
                           next=request.args.get('next'))


@index.route("/key_rotation", methods=["GET", "POST"])
def key_rotation():
    kr = KeyRotation.query.first()
    form = KeyRotationForm()
    oxauth_servers = [server for server in OxauthServer.query]

    if request.method == "GET" and kr is not None:
        form.interval.data = kr.interval
        form.type.data = kr.type
        form.oxeleven_url.data = kr.oxeleven_url
        form.inum_appliance.data = kr.inum_appliance

    if form.validate_on_submit():
        if not kr:
            kr = KeyRotation()

        kr.interval = form.interval.data
        kr.type = form.type.data
        kr.oxeleven_url = form.oxeleven_url.data
        kr.inum_appliance = form.inum_appliance.data
        kr.oxeleven_token_key = generate_random_key()
        kr.oxeleven_token_iv = generate_random_iv()
        kr.oxeleven_token = encrypt_text(
            b"{}".format(form.oxeleven_token.data),
            kr.oxeleven_token_key,
            kr.oxeleven_token_iv,
        )
        db.session.add(kr)
        db.session.commit()
        # rotate the keys immediately
        rotate_pub_keys.delay()
        return redirect(url_for("key_rotation"))
    return render_template("key_rotation.html",
                           form=form,
                           rotation=kr,
                           oxauth_servers=oxauth_servers)


@index.route("/api/oxauth_server", methods=["GET", "POST"])
def oxauth_server():
    if request.method == "POST":
        hostname = request.form.get("hostname")
        gluu_server = request.form.get("gluu_server")
        gluu_version = request.form.get("gluu_version")

        if gluu_server == "true":
            gluu_server = True
        else:
            gluu_server = False
            gluu_version = ""

        if not hostname:
            return jsonify({
                "status": 400,
                "message": "Invalid data",
                "params": "hostname can't be empty",
            }), 400

        server = OxauthServer()
        server.hostname = hostname
        server.gluu_server = gluu_server
        server.gluu_version = gluu_version
        db.session.add(server)
        db.session.commit()
        return jsonify({
            "id": server.id,
            "hostname": server.hostname,
            "gluu_server": server.gluu_server,
            "get_version": server.get_version,
        }), 201

    servers = [{
        "id": srv.id,
        "hostname": srv.hostname,
        "version": srv.get_version,
        "gluu_server": srv.gluu_server,
    } for srv in OxauthServer.query]
    return jsonify(servers)


@index.route("/api/oxauth_server/<id>", methods=["POST"])
def delete_oxauth_server(id):
    server = OxauthServer.query.get(id)
    if server:
        db.session.delete(server)
        db.session.commit()
    return jsonify({}), 204


@index.route('/log/<task_id>')
def get_log(task_id):
    msgs = wlogger.get_messages(task_id)
    result = AsyncResult(id=task_id, app=celery)
    if result.state == 'SUCCESS' or result.state == 'FAILED':
        wlogger.clean(task_id)
    log = {'task_id': task_id, 'state': result.state, 'messages': msgs}
    return jsonify(log)


def getLdapConn(addr, dn, passwd):
    ldp = ldapOLC('ldaps://{}:1636'.format(addr), dn, passwd)
    r = None
    try:
        r = ldp.connect()
    except Exception as e:
        flash("Connection to LDAPserver {0} at port 1636 was failed: {1}".format(
            addr, e), "danger")
        return
    if not r:
        flash("Connection to LDAPserver  {0} at port 1636 was failed: {1}".format(
            addr, ldp.conn.result['description']), "danger")
        return

    return ldp

def get_primary_server_id():
    pr_server = Server.query.filter_by(primary_server=True).first()
    if pr_server:
        return pr_server.id


@index.route('/server/<server_id>/', methods=['GET', 'POST'])
def edit_ldap_server(server_id):
    data = {'title': 'Add New Ldap Server', 'button': 'Add Server'}
    server_id = int(server_id)
    form = ServerForm()
    form.primary_server(disabled=True)
    
    pr_server = get_primary_server_id()

    if pr_server:
        if not get_primary_server_id() == server_id:
            form.primary_server.render_kw = {'disabled': 'disabled'}
    
    if request.method == 'GET':

        if int(server_id) > 0:

            data['title'] = 'Edit Server ID: {}'.format(server_id)
            data['button'] = 'Update Server'

            ldpsi = Server.query.filter_by(id=server_id).first()
            form.hostname.data = ldpsi.hostname
            form.ip.data = ldpsi.ip
            form.ldap_password.data = ldpsi.ldap_password
            form.primary_server.data = ldpsi.primary_server
    else:
        if form.validate_on_submit():
            if server_id > 0:
                ldps = Server.query.filter_by(id=server_id).first()
            else:
                ldps = Server()

                ldp = Server().query.filter(
                    Server.hostname == form.hostname.data).first()
                if ldp:
                    flash("{0} is already in LDAP servers List".format(
                        form.hostname.data), "warning")
                    return render_template('ldap_server.html', form=form, data=data)

            ldps.gluu_server = True
            ldps.hostname = form.hostname.data
            ldps.ip = form.ip.data
            ldps.ldap_password = form.ldap_password.data
            ldps.primary_server = form.primary_server.data
            if server_id < 0:
                db.session.add(ldps)

            db.session.commit()
            return redirect(url_for('index.home'))

    

    return render_template('ldap_server.html', data=data, form=form)


@index.route('/installldapserver', methods=['GET', 'POST'])
def install_ldap_server():
    
    if not checkAppConfig():
        return redirect(url_for('index.home'))

    if 'nongluuldapinfo' in session:
        del session['nongluuldapinfo']
    form = InstallServerForm()

    data = {'title': 'Install Symas Open-Ldap Server',
            'button': 'Install',
            }

    if request.method == 'POST':
        if form.validate_on_submit():

            ldp = Server().query.filter(
                Server.hostname == form.hostname.data).first()
            if ldp:
                flash("{0} is already in LDAP servers List".format(
                    form.hostname.data), "warning")
                return render_template('ldap_server.html', form=form,  data=data)

            session['nongluuldapinfo'] = {
                'hostname': form.hostname.data,
                'ip': form.ip.data,
                'ldap_password': form.ldap_password.data,   
                'countryCode': form.countryCode.data,
                'state': form.state.data,
                'city': form.city.data,
                'orgName': form.orgName.data,
                'admin_email': form.admin_email.data,
            }

            return redirect(url_for('cluster.install_ldap_server'))

    return render_template('ldap_server.html', form=form,  data=data)


@index.route('/server/<int:server_id>/remove/')
def remove_server(server_id):
    
    if server_id == get_primary_server_id():
        flash("This is primary server, can't remove.", "danger")
    else:
        server = Server.query.get(server_id)

        if not server.mmr:
            db.session.delete(server)
            db.session.commit()

            flash("Ldap Server {0} is removed.".format(server.hostname), "success")
        else:
            flash("Ldap Server {0} is a member of multi master replication. Can't delete.".format(server.hostname), "warning")
    return redirect(url_for('index.home'))


@index.route('/makemmrreplicator/')
def make_multi_master_replicator():
    server_id = int(request.values.get("server_id"))

    ldp = Server.query.get(server_id)
    if ldp:
        ldp.mmr = True
        db.session.commit()
        flash("Ldap Server {0} was added as Master Server".format(
            ldp.hostname), "success")
    else:
        flash("No such LDAP Server", "warning")

    return redirect(url_for('index.multi_master_replication'))


def get_mmr_list():
    ldaps = Server.query.filter(Server.mmr==True).all()
    mmrs = []
    for ldp in ldaps:
        if ldp.mmr:
            mmrs.append(ldp.id)
    return mmrs


def checkAppConfig():
    app_config = AppConfiguration.query.first()
    
    appConfigured = True
    
    repl_user = None
    repl_pass = None
    
    if app_config:
        repl_user = app_config.replication_dn
        repl_pass = app_config.replication_pw
        
    if not (repl_user or repl_pass):
        appConfigured = False
        flash(("Repication user and/or password has not been defined. "
                "Please go 'Configuration' and set these before proceed."),
                "warning")
    if not get_primary_server_id():
        appConfigured = False
        flash(("Primary Server has not been set. "
                "Please go 'Dashboard' and set one of the servers as Primar before proceed."),
                "warning")

    return appConfigured
    
@index.route('/mmr/')
def multi_master_replication():

    appConfigured=checkAppConfig()

    if 'nongluuldapinfo' in session:
        del session['nongluuldapinfo']

    ldaps = Server.query.all()
    id_host_dict = {}

    addServerButton = False

    serverStats = {}

    primary_mmr = False

    for ldp in ldaps:
        if ldp.mmr:
            addServerButton = True
            if ldp.primary_server:
                primary_mmr = True
            s = ldapOLC(
                "ldaps://{0}:1636".format(ldp.hostname), "cn=config", ldp.ldap_password)
            r = None
            try:
                r = s.connect()
            except Exception as e:
                flash("Connection to LDAPserver {0} at port 1636 was failed: {1}".format(
                    ldp.hostname, e), "warning")

            if not r:
                flash("Connection to LDAPserver {0} at port 1636 was failed".format(
                    ldp.hostname), "warning")

            if r:
                sstat = s.getMMRStatus()
                if sstat['server_id']:
                    serverStats[ldp.hostname] = sstat

    if not appConfigured:
        addServerButton = False

    if not primary_mmr:
        flash("Please add Primary LDAP Server, can't deploy without primary server.", "warning")

    return render_template('multi_master.html', ldapservers=ldaps,
                           id_host_dict=id_host_dict,
                           addServerButton=addServerButton,
                           serverStats=serverStats,
                           primary_mmr = primary_mmr
                           )


@index.route('/removemaster/')
def remove_multi_master_replicator():
    server_id = int(request.values.get("server_id"))

    if server_id == get_primary_server_id():
        flash("This is primary server, can't remove.", "danger")
    else:
        server = Server.query.get(server_id)
        
        if server:
            server.mmr = False
            db.session.commit()
            flash("Master server is removed", "success")
        else:
            flash("No such server", "danger")

    return redirect(url_for('index.multi_master_replication'))


@index.route('/addtestuser/<int:server_id>', methods=['GET', 'POST'])
def add_test_user(server_id):
    print "SERVER ID", server_id
    server = Server.query.get(server_id)

    form = TestUser()
    data = {'title': 'Add Test User [{0}]'.format(
        server.hostname), 'button': 'Add'}

    if form.validate_on_submit():

        ldp = getLdapConn(server.hostname,
                          "cn=directory manager,o=gluu", server.ldap_password)

        if ldp:
            if ldp.addTestUser(form.first_name.data, form.last_name.data, form.email.data):
                flash("Test User {0} {1} to {2} was sucessfuly added.".format(
                    form.first_name.data, form.last_name.data, server.hostname), "success")
            else:
                flash("Adding user failed: {0}".format(
                    ldp.conn.result['description']), "warning")

            return redirect(url_for('index.multi_master_replication'))

    return render_template('ldap_server.html', form=form,  data=data)


@index.route('/searchtestusers/<int:server_id>')
def search_test_users(server_id):

    print "SERVER ID", server_id
    server = Server.query.get(server_id)

    users = []
    ldp = getLdapConn(server.hostname,
                      "cn=directory manager,o=gluu", server.ldap_password)

    if ldp:

        if not ldp.searchTestUsers():
            flash("Searching user failed: {0}".format(
                ldp.conn.result['description']), "danger")
        else:
            users = ldp.conn.response
            for user in users:
                host = user['dn'].split('@')[1].split(',')[0]
                user['host'] = host

    if users:
        st = '{0}({1})'.format(server.hostname, len(users))
        return render_template('test_users.html', server_id=server_id, server=st, users=users)

    return redirect(url_for('index.multi_master_replication'))


@index.route('/deletetestuser/<server_id>/<dn>')
def delete_test_user(server_id, dn):
    server = Server.query.get(server_id)

    ldp = getLdapConn(server.hostname,
                      "cn=directory manager,o=gluu", server.ldap_password)

    if ldp:
        if ldp.delDn(dn):
            flash("Test User form {0} was deleted".format(
                server.hostname), "success")
        else:
            flash("Test User deletation failed: {0}".format(
                ldp.conn.result['description']), "danger")

    return redirect(url_for('index.search_test_users', server_id=server_id))


@index.route('/removeprovider/<consumer_id>/<provider_addr>')
def remove_provider_from_consumer(consumer_id, provider_addr):

    server = Server.query.get(consumer_id)

    ldp = getLdapConn(server.hostname, "cn=config", server.ldap_password)

    if ldp:
        r = ldp.removeProvider("ldaps://{0}:1636".format(provider_addr))
        if r:
            flash('Provder {0} from {1} is removed'.format(
                provider_addr, server.hostname), 'success')
        else:
            flash("Removing provider was failed: {0}".format(
                ldp.conn.result['description']), "danger")

    return redirect(url_for('index.multi_master_replication'))


@index.route('/addprovidertocustomer/<int:consumer_id>/<int:provider_id>')
def add_provider_to_consumer(consumer_id, provider_id):

    server = Server.query.get(consumer_id)

    app_config = AppConfiguration.query.first()

    ldp = getLdapConn(server.hostname, "cn=config", server.ldap_password)

    if ldp:

        provider = Server.query.get(provider_id)

        if app_config.use_ip:
            p_addr = provider.ip
        else:
            p_addr = provider.hostname

        replication_dn = 'cn={0},o=gluu'.format(app_config.replication_dn)

        if ldp.addProvider(provider.id, "ldaps://{0}:1636".format(p_addr), replication_dn, app_config.replication_pw):
            flash("Provider {0} was added to {1}".format(
                provider.hostname, server.hostname), "success")
        else:
            flash("Adding provider {0} to {1} was failed: {2}".format(
                provider.hostname, server.hostname, ldp.conn.result['description']), "danger")

        ldp.makeMirroMode()

    return redirect(url_for('index.multi_master_replication'))
