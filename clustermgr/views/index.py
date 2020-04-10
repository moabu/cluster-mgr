# -*- coding: utf-8 -*-
import os
import glob

from time import strftime
import json
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session, current_app
from flask import current_app as app
from flask_login import login_required
from flask_login import current_user
from werkzeug.utils import secure_filename
from celery.result import AsyncResult
from flask_menu import register_menu


from clustermgr.extensions import db, wlogger, csrf
from clustermgr.models import AppConfiguration, Server  # , KeyRotation
from clustermgr.forms import AppConfigForm, SchemaForm, \
    TestUser, InstallServerForm, LdapSchema  # , KeyRotationForm

from celery.result import AsyncResult
from ldap.schema import AttributeType, ObjectClass, LDAPSyntax
from clustermgr.core.utils import get_setup_properties, logger, encode
from clustermgr.core.ldap_functions import LdapOLC
from clustermgr.core.ldifschema_utils import OpenDjSchema



from clustermgr.tasks.cluster import upgrade_clustermgr_task
from clustermgr.core.license import license_reminder
from clustermgr.extensions import celery
from clustermgr.core.license import prompt_license, license_required

from clustermgr.core.remote import RemoteClient, FakeRemote, ClientNotSetupException

from clustermgr.core.clustermgr_installer import Installer

from clustermgr.core.utils import get_setup_properties, \
    get_opendj_replication_status, as_boolean

from clustermgr.core.ldifschema_utils import OpenDjSchema

from clustermgr.tasks.server import collect_server_details

index = Blueprint('index', __name__)
index.before_request(prompt_license)
index.before_request(license_reminder)
index.before_request(license_required)

msg_text = ''

@index.route('/gluuServerCluster')
@register_menu(index, '.gluuServerCluster', 'Gluu Server Cluster', order=0, icon='fa fa-folder')
def menuIndex():
    return redirect(url_for('index.home'))


@index.route('/')
@register_menu(index, '.gluuServerCluster.servers', 'Gluu Servers', order=0, icon='fa fa-server')
def home():
    cfg_file = app.config["AUTH_CONFIG_FILE"]
    oxd_file_config = app.config["OXD_CLIENT_CONFIG_FILE"]
    
    if not os.path.exists(cfg_file):
        if not os.path.exists(oxd_file_config):
            return redirect(url_for('auth.signup'))
    
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next='/'))

    """This is the home view --dashboard--"""
    if 'nongluuldapinfo' in session:
        del session['nongluuldapinfo']
    
    try:
        appconf = AppConfiguration.query.first()
    except:
        return render_template('index_nodb.html')
    
    if not appconf:
        return render_template('intro.html', setup='cluster')

    servers = Server.query.all()
    if not servers:
        return render_template('intro.html', setup='server')


    ask_passphrase = False
    
    c = RemoteClient(servers[0].ip, servers[0].hostname)
    try:
        c.startup()
    
    except ClientNotSetupException as e:

        if str(e) == 'Pubkey is encrypted.':
            ask_passphrase = True
            flash("Pubkey seems to password protected. "
                "Please set passphrase.",
                'warning')
        elif str(e) == 'Could not deserialize key data.':
            ask_passphrase = True
            flash("Password you provided for pubkey did not work. "
                "Please set valid passphrase.",
                'warning')
        else:
            flash("SSH connection to {} failed. Please check if your pub key is "
                "added to /root/.ssh/authorized_keys on this server. Reason: {}".format(
                                                servers[0].hostname, e), 'error')

        if ask_passphrase:
            return render_template('index_passphrase.html', e=e, 
                ask_passphrase=ask_passphrase, next='/',
                warning_text="Error accessing primary server")
    
    service_update_period = 300
    
    if appconf.ldap_update_period:
        service_update_period = appconf.ldap_update_period
        if appconf.ldap_update_period_unit != 's':
            service_update_period = service_update_period * 60


    server_id_list = [str(server.id) for server in servers]
    
    services = ['oxauth', 'identity']
    prop = get_setup_properties()

    if as_boolean(prop['installSaml']):
        services.append('shib')

    if as_boolean(prop['installPassport']):
        services.append('passport')


    return render_template('dashboard.html', servers=servers, app_conf=appconf,
                             services=services, server_id_list=server_id_list,
                             service_update_period=service_update_period
                        )

# @index.route("/key_rotation", methods=["GET", "POST"])
# def key_rotation():
#     kr = KeyRotation.query.first()
#     form = KeyRotationForm()
#     oxauth_servers = [server for server in Server.query]

#     if request.method == "GET" and kr is not None:
#         form.interval.data = kr.interval
#         form.type.data = kr.type
#         form.oxeleven_url.data = kr.oxeleven_url
#         form.inum_appliance.data = kr.inum_appliance

#     if form.validate_on_submit():
#         if not kr:
#             kr = KeyRotation()

#         kr.interval = form.interval.data
#         kr.type = form.type.data
#         kr.oxeleven_url = form.oxeleven_url.data
#         kr.inum_appliance = form.inum_appliance.data
#         kr.oxeleven_token_key = generate_random_key()
#         kr.oxeleven_token_iv = generate_random_iv()
#         kr.oxeleven_token = encrypt_text(
#             b"{}".format(form.oxeleven_token.data),
#             kr.oxeleven_token_key,
#             kr.oxeleven_token_iv,
#         )
#         db.session.add(kr)
#         db.session.commit()
#         # rotate the keys immediately
#         rotate_pub_keys.delay()
#         return redirect(url_for("key_rotation"))
#     return render_template("key_rotation.html",
#                            form=form,
#                            rotation=kr,
#                            oxauth_servers=oxauth_servers)


# @index.route("/api/oxauth_server", methods=["GET", "POST"])
# def oxauth_server():
#     if request.method == "POST":
#         hostname = request.form.get("hostname")
#         gluu_server = request.form.get("gluu_server")

#         if gluu_server == "true":
#             gluu_server = True
#         else:
#             gluu_server = False

#         if not hostname:
#             return jsonify({
#                 "status": 400,
#                 "message": "Invalid data",
#                 "params": "hostname can't be empty",
#             }), 400

#         server = Server()
#         server.hostname = hostname
#         server.gluu_server = gluu_server
#         db.session.add(server)
#         db.session.commit()
#         return jsonify({
#             "id": server.id,
#             "hostname": server.hostname,
#             "gluu_server": server.gluu_server,
#         }), 201

#     servers = [{
#         "id": srv.id,
#         "hostname": srv.hostname,
#         "gluu_server": srv.gluu_server,
#     } for srv in Server.query]
#     return jsonify(servers)


# @index.route("/api/oxauth_server/<id>", methods=["POST"])
# def delete_oxauth_server(id):
#     server = Server.query.get(id)
#     if server:
#         db.session.delete(server)
#         db.session.commit()
#     return jsonify({}), 204




@index.route('/log/<task_id>')
@login_required
def get_log(task_id):
    
    global msg_text
    
    msgs = wlogger.get_messages(task_id)
    result = AsyncResult(id=task_id, app=celery)
    value = 0

    error_message = ''

    if result.result != None:
        if getattr(result, 'traceback'):
            error_message = str(result.traceback)
            
    if result.state == 'SUCCESS' or result.state == 'FAILED':
        if result.result:
            if type(result.result) != type(True):
                try:
                    value = result.result.message
                except:
                    value = result.result
        wlogger.clean(task_id)
    log = {'task_id': task_id, 'state': result.state, 'messages': msgs,
           'result': value, 'error_message': error_message}

    ts = strftime('[%Y-%b-%d %H:%M]')
    
    log_ = False
    
    if msgs:
        if msgs[-1].get('msg','') != msg_text:
            
            msg_text = msgs[-1].get('msg','')
            log_ = True
    
    if log_ or error_message:
        
        logger.error('%s [Celery] %s %s %s %s',
                          ts,
                          result.state,
                          msg_text,
                          value,
                          error_message
                    )

    return jsonify(log)


@index.route('/setpassphrase/', methods=['POST','GET'])
@login_required
@csrf.exempt
def set_passphrase():
    passphrase = request.form['passphrase']

    encoded_passphrase = encode(os.getenv('NEW_UUID'), passphrase)

    with open(os.path.join(current_app.config['DATA_DIR'], '.pw'),'w') as f:
        f.write(encoded_passphrase)

    next_url = request.args.get('next')
    if not next_url:
        next_url = '/'
    
    return redirect(next_url)
