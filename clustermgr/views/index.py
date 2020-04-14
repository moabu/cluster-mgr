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
from clustermgr.models import ConfigParam
from clustermgr.forms import AppConfigForm, SchemaForm, \
     InstallServerForm, LdapSchema  # , KeyRotationForm

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
    
    authdb = ConfigParam.get('authuser')

    if not authdb:
        return redirect(url_for('auth.signup'))
    
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next='/'))

    """This is the home view --dashboard--"""
    if 'nongluuldapinfo' in session:
        del session['nongluuldapinfo']
        
    servers = ConfigParam.get_all('gluuserver')
    load_balancer_config = ConfigParam.get('load_balancer')

    if not servers:
        return render_template('intro.html', setup='cluster', load_balancer_config=load_balancer_config)

    ask_passphrase = False
    
    c = RemoteClient(servers[0].data.ip, servers[0].data.hostname)
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
    
    settings = ConfigParam.get('settings')

    service_update_period = 300
    if settings:
        service_update_period = settings.data.get('service_update_period', 300)
        if settings.data.service_update_period != 's':
            service_update_period = service_update_period * 60

    server_id_list = [str(server.id) for server in servers]

    services = ['oxauth', 'identity']
    prop = get_setup_properties()

    if as_boolean(prop['installSaml']):
        services.append('shib')

    if as_boolean(prop['installPassport']):
        services.append('passport')

    return render_template('dashboard.html', servers=servers,
                             services=services, server_id_list=server_id_list,
                             service_update_period=service_update_period,
                        )

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
