# -*- coding: utf-8 -*-
import os
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session
from flask import current_app as app
from werkzeug.utils import secure_filename
from celery.result import AsyncResult

from clustermgr.extensions import db, wlogger, celery
from clustermgr.models import AppConfiguration, KeyRotation, Server
from clustermgr.forms import AppConfigForm, KeyRotationForm, SchemaForm, \
    TestUser, InstallServerForm

from clustermgr.core.ldap_functions import LdapOLC
from clustermgr.tasks.all import rotate_pub_keys
from clustermgr.core.utils import encrypt_text
from clustermgr.core.utils import generate_random_key
from clustermgr.core.utils import generate_random_iv

index = Blueprint('index', __name__)


@index.route('/')
def home():
    """This is the home view --dashboard--"""
    if 'nongluuldapinfo' in session:
        del session['nongluuldapinfo']
    appconf = AppConfiguration.query.first()
    if not appconf:
        return render_template('intro.html', setup='cluster')

    servers  = Server.query.all()
    if not servers:
        return render_template('intro.html', setup='server')

    return render_template('dashboard.html', servers=servers, app_conf=appconf)

@index.route('/configuration/', methods=['GET', 'POST'])
def app_configuration():
    """This view provides application configuration forms"""
    
    #create forms
    conf_form = AppConfigForm()
    sch_form = SchemaForm()
    config = AppConfiguration.query.first()
    schemafiles = os.listdir(app.config['SCHEMA_DIR'])

    #If the form is sumtted and password for replication user was not
    #not supplied, make password "**dummu**", so don't change 
    #what we have before
    if request.method == 'POST' and not conf_form.replication_pw.data.strip():
        conf_form.replication_pw.data = '**dummy**'
        conf_form.replication_pw_confirm.data = '**dummy**'

    #If form is submitted and ladidated process it
    if conf_form.update.data and conf_form.validate_on_submit():
        #If prviously configured and admin changed replcation user (dn) and it's
        #password .this will break replication, check and war admin.
        replication_dn = "cn={},o=gluu".format(
                                        conf_form.replication_dn.data.strip())
        if not config:
            config = AppConfiguration()
        else:
            if config.replication_dn != replication_dn:
                flash("You changed Replication Manager dn. "
                      "This will break replication. "
                      "Please re-deploy all LDAP Servers.",
                       "danger")


        if conf_form.replication_pw.data and \
                conf_form.replication_pw_confirm.data is not '**dummy**':
            config.replication_pw = conf_form.replication_pw.data.strip()
            flash("You changed Replication Manager password. "
                    "This will break replication. "
                    "Please re-deploy all LDAP Servers.",
                    "danger")
        
        config.replication_dn = replication_dn
        config.gluu_version = conf_form.gluu_version.data.strip()
        config.use_ip = conf_form.use_ip.data
        config.nginx_host = conf_form.nginx_host.data.strip()
        
        config.replication_dn = replication_dn
        config.gluu_version = conf_form.gluu_version.data.strip()
        config.use_ip = conf_form.use_ip.data
        config.nginx_host = conf_form.nginx_host.data.strip()
        
        purge_age_day = conf_form.purge_age_day.data
        purge_age_hour = conf_form.purge_age_hour.data
        purge_age_min = conf_form.purge_age_min.data
        purge_interval_day = conf_form.purge_interval_day.data
        purge_interval_hour = conf_form.purge_interval_hour.data
        purge_interval_min = conf_form.purge_interval_min.data
        
        log_purge = "{}:{}:{} {}:{}:{}".format( 
                                            purge_age_day, purge_age_hour,
                                            purge_age_min, purge_interval_day, 
                                            purge_interval_hour, 
                                            purge_interval_min)
        config.log_purge = log_purge
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
        flash("Schema: {0} has been uploaded sucessfully. "
              "Please edit slapd.conf of primary server and "
              "re-deploy all servers.".format(filename),
              "success")

    # request.method == GET gets processed here
    if config and config.replication_dn:
        conf_form.replication_dn.data = config.replication_dn.replace(
            "cn=", "").replace(",o=gluu", "")
        conf_form.replication_pw.data = config.replication_pw
        conf_form.nginx_host.data = config.nginx_host
        conf_form.use_ip.data = config.use_ip
        if config.gluu_version:
            conf_form.gluu_version.data = config.gluu_version

        if config.log_purge:
            a, i = config.log_purge.split()
            pa = a.split(':')
            pi = i.split(':')
            conf_form.purge_age_day.data = pa[0]
            conf_form.purge_age_hour.data = pa[1]
            conf_form.purge_age_min.data = pa[2]
            conf_form.purge_interval_day.data = pi[0]
            conf_form.purge_interval_hour.data = pi[1]
            conf_form.purge_interval_min.data = pi[2]


    return render_template('app_config.html', cform=conf_form, sform=sch_form,
                           config=config, schemafiles=schemafiles,
                           next=request.args.get('next'))


@index.route("/key_rotation", methods=["GET", "POST"])
def key_rotation():
    kr = KeyRotation.query.first()
    form = KeyRotationForm()
    oxauth_servers = [server for server in Server.query]

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

        if gluu_server == "true":
            gluu_server = True
        else:
            gluu_server = False

        if not hostname:
            return jsonify({
                "status": 400,
                "message": "Invalid data",
                "params": "hostname can't be empty",
            }), 400

        server = Server()
        server.hostname = hostname
        server.gluu_server = gluu_server
        db.session.add(server)
        db.session.commit()
        return jsonify({
            "id": server.id,
            "hostname": server.hostname,
            "gluu_server": server.gluu_server,
        }), 201

    servers = [{
        "id": srv.id,
        "hostname": srv.hostname,
        "gluu_server": srv.gluu_server,
    } for srv in Server.query]
    return jsonify(servers)


@index.route("/api/oxauth_server/<id>", methods=["POST"])
def delete_oxauth_server(id):
    server = Server.query.get(id)
    if server:
        db.session.delete(server)
        db.session.commit()
    return jsonify({}), 204


@index.route('/log/<task_id>')
def get_log(task_id):
    msgs = wlogger.get_messages(task_id)
    result = AsyncResult(id=task_id, app=celery)
    value = 0
    if result.state == 'SUCCESS' or result.state == 'FAILED':
        value = result.result
        wlogger.clean(task_id)
    log = {'task_id': task_id, 'state': result.state, 'messages': msgs,
           'result': value}
    return jsonify(log)


def getLdapConn(addr, dn, passwd):
    """this function gets address, dn and password for ldap server, makes
    connection and return LdapOLC object."""
    
    ldp = LdapOLC('ldaps://{}:1636'.format(addr), dn, passwd)
    r = None
    try:
        r = ldp.connect()
    except Exception as e:
        flash("Connection to LDAPserver {0} at port 1636 failed: {1}".format(
            addr, e), "danger")
        return
    if not r:
        flash("Connection to LDAPserver {0} at port 1636 failed: {1}".format(
            addr, ldp.conn.result['description']), "danger")
        return
    return ldp


@index.route('/install_ldapserver', methods=['GET', 'POST'])
def install_ldap_server():
    """This view provides installing non-gluu ldap server - depreceated"""
    if 'nongluuldapinfo' in session:
        del session['nongluuldapinfo']
    form = InstallServerForm()

    data = {'title': 'Install Symas Open-Ldap Server',
            'button': 'Install',
            }

    if request.method == 'POST':
        if form.validate_on_submit():
            ldp = Server.query.filter(
                Server.hostname == form.hostname.data).first()
            if ldp:
                flash("{0} is already in LDAP servers List".format(
                    form.hostname.data), "warning")
                return render_template('new_server.html', form=form,
                                       data=data)

            session['nongluuldapinfo'] = {
                'fqn_hostname': form.hostname.data.strip(),
                'ip_address': form.ip_address.data.strip(),
                'ldap_password': form.ldap_password.data.strip(),
                'ldap_user': 'ldap',
                'ldap_group': 'ldap',
                'countryCode': form.countryCode.data.strip(),
                'state': form.state.data.strip(),
                'city': form.city.data.strip(),
                'orgName': form.orgName.data.strip(),
                'admin_email': form.admin_email.data.strip(),
            }

            return redirect(url_for('cluster.install_ldap_server'))

    return render_template('new_server.html', form=form,  data=data)


@index.route('/mmr/')
def multi_master_replication():
    """Multi Master Replication view"""
    
    #Check if replication user (dn) and password has been configured
    app_config = AppConfiguration.query.first()
    if not app_config:
        flash("Repication user and/or password has not been defined."
              " Please go to 'Configuration' and set these before proceed.",
              "warning")

    if 'nongluuldapinfo' in session:
        del session['nongluuldapinfo']

    ldap_errors = []

    ldaps = Server.query.all()
    serverStats = {}


    #Collect replication information for all configured servers
    for ldp in ldaps:

        s = LdapOLC(
            "ldaps://{0}:1636".format(ldp.hostname), "cn=config",
            ldp.ldap_password)
        r = None
        try:
            r = s.connect()
        except Exception as e:
            ldap_errors.append(
                "Connection to LDAPserver {0} at port 1636 was failed:"
                " {1}".format(ldp.hostname, e))

        if r:
            sstat = s.getMMRStatus()
            if sstat['server_id']:
                serverStats[ldp.hostname] = sstat

    #If there is no ldap server, return to home
    if not ldaps:
        flash("Please add ldap servers.", "warning")
        return redirect(url_for('index.home'))
        
    return render_template('multi_master.html', 
                           ldapservers=ldaps,
                           serverStats=serverStats,
                           ldap_errors=ldap_errors,
                           )


@index.route('/addtestuser/<int:server_id>', methods=['GET', 'POST'])
def add_test_user(server_id):
    """This view provides adding test user UI"""
    
    server = Server.query.get(server_id)
    
    form = TestUser()
    header = 'Add Test User [{0}]'.format(server.hostname)

    #If form is submitted and validated, add user to specified server_id
    if form.validate_on_submit():
        #Make ldap connection
        ldp = getLdapConn(server.hostname, "cn=directory manager,o=gluu",
                          server.ldap_password)

        #If connection was established try to add test user
        if ldp:
            if ldp.addTestUser(form.first_name.data.strip(), form.last_name.data.strip(),
                               form.email.data.strip()):
                flash("Test User {0} {1} to {2} was sucessfuly added.".format(
                    form.first_name.data.strip(), form.last_name.data.strip(),
                    server.hostname.strip()), "success")
            else:
                flash("Adding user failed: {0}".format(
                    ldp.conn.result['description']), "warning")

            return redirect(url_for('index.multi_master_replication'))

    return render_template('new_server.html', form=form,  header=header)


@index.route('/searchtestusers/<int:server_id>')
def search_test_users(server_id):
    """This view provides searcing test user UI. Searched user on server 
    identified by server_id and displays within table"""

    print "SERVER ID", server_id
    server = Server.query.get(server_id)

    users = []
    
    #Make ldap connection
    ldp = getLdapConn(server.hostname,
                      "cn=directory manager,o=gluu", server.ldap_password)

    #If connection was established try to display test users
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
        return render_template('test_users.html', server_id=server_id,
                               server=st, users=users)

    return redirect(url_for('index.multi_master_replication'))


@index.route('/deletetestuser/<server_id>/<dn>')
def delete_test_user(server_id, dn):
    """This view delates test user"""
    server = Server.query.get(server_id)

    #Make ldap connection
    ldp = getLdapConn(server.hostname,
                      "cn=directory manager,o=gluu", server.ldap_password)

    #If connection was established try to delete test user
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
    """This view delates provider from consumer"""
    
    server = Server.query.get(consumer_id)

    #Make ldap connection
    ldp = getLdapConn(server.hostname, "cn=config", server.ldap_password)

    #If connection was established try to delete provider
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
    """This view adds provider to consumer"""
    server = Server.query.get(consumer_id)

    app_config = AppConfiguration.query.first()

    #Make ldap connection
    ldp = getLdapConn(server.hostname, "cn=config", server.ldap_password)

    #If connection was established try to add provider
    if ldp:
        provider = Server.query.get(provider_id)

        if app_config.use_ip:
            p_addr = provider.ip
        else:
            p_addr = provider.hostname

        status = ldp.add_provider(
            provider.id, "ldaps://{0}:1636".format(p_addr),
            app_config.replication_dn, app_config.replication_pw)

        if status:
            flash("Provider {0} was added to {1}".format(
                provider.hostname, server.hostname), "success")
        else:
            flash("Adding provider {0} to {1} was failed: {2}".format(
                provider.hostname, server.hostname,
                ldp.conn.result['description']), "danger")

        if not ldp.checkMirroMode():
            ldp.makeMirroMode()

    return redirect(url_for('index.multi_master_replication'))

@index.route('/removecustomschema/<schema_file>')
def remove_custom_schema(schema_file):
    """This view deletes custom schema file"""
    
    file_path = os.path.join(app.config['SCHEMA_DIR'], schema_file)
    if os.path.exists(file_path):
        os.remove(file_path)
    return redirect(url_for('index.app_configuration'))
