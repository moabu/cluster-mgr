import os
import json
from flask import Blueprint, render_template, redirect, url_for, flash, \
        request, jsonify, session
from flask import current_app as app
from werkzeug.utils import secure_filename
from celery.result import AsyncResult

from clustermgr.extensions import db, wlogger, celery
from clustermgr.models import LDAPServer, AppConfiguration, KeyRotation, \
    OxauthServer, LdapServer, MultiMaster, Provider

from clustermgr.forms import AppConfigForm, KeyRotationForm, SchemaForm, \
    LdapServerForm
    
from clustermgr.core.ldap_functions import ldapOLC 
    
from clustermgr.tasks.all import rotate_pub_keys
from clustermgr.core.utils import encrypt_text
from clustermgr.core.utils import generate_random_key
from clustermgr.core.utils import generate_random_iv

index = Blueprint('index', __name__)


@index.route('/')
def home():
    servers = []
    config = {}
    print(config, servers)

    ldaps=LdapServer.query.all()

    data = {"ldapservers": ldaps}

    return render_template('dashboard.html', data=data)


@index.route('/configuration/', methods=['GET', 'POST'])
def app_configuration():
    conf_form = AppConfigForm()
    sch_form = SchemaForm()
    config = AppConfiguration.query.first()
    schemafiles = os.listdir(app.config['SCHEMA_DIR'])

    if conf_form.update.data and conf_form.validate_on_submit():
        if not config:
            config = AppConfiguration()
        config.replication_dn = "cn={},o=gluu".format(
            conf_form.replication_dn.data)
        config.replication_pw = conf_form.replication_pw.data
        config.certificate_folder = conf_form.certificate_folder.data

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
        conf_form.replication_dn.data = config.replication_dn.replace(
            "cn=", "").replace(",o=gluu", "")
        conf_form.replication_pw.data = config.replication_pw
        conf_form.certificate_folder.data = config.certificate_folder

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


@index.route('/server/<server_id>/', methods=['GET', 'POST'])
def edit_ldap_server(server_id):
    data={'title': 'Add New Ldap Server', 'button': 'Add Server'}
    
    form = LdapServerForm()
    if request.method == 'GET':

        if int(server_id)>0:
            
            data['title'] = 'Edit Server ID: {}'.format(server_id)
            data['button'] = 'Update Server'

            ldpsi = LdapServer.query.filter_by(id=server_id).first()
            form.fqn_hostname.data = ldpsi.fqn_hostname
            form.ip_address.data = ldpsi.ip_address
            form.ldap_user.data = ldpsi.ldap_user
            form.ldap_group.data = ldpsi.ldap_group
            form.gluu_version.data = ldpsi.gluu_version
            form.ldap_password.data = ldpsi.ldap_password

        else:
            
            form.ldap_group.data = 'ldap'
            form.ldap_user.data = 'ldap'
 
    else:
        if form.validate_on_submit():
            if int(server_id)>0:
                ldps = LdapServer.query.filter_by(id=server_id).first()
            else:
                ldps=LdapServer()
            
            ldps.gluu_version = form.gluu_version.data
            ldps.fqn_hostname=form.fqn_hostname.data
            ldps.ip_address=form.ip_address.data
            ldps.ldap_password=form.ldap_password.data
            ldps.ldap_user=form.ldap_user.data
            ldps.ldap_group=form.ldap_group.data
            
            print "IP ADDR", ldps.ip_address, form.ip_address.data
            
            if int(server_id) < 0:
                db.session.add(ldps)
                
            db.session.commit()
            return redirect(url_for('index.home'))
    

    return render_template('ldap_server.html', data=data, form=form)

@index.route('/server/<int:server_id>/remove/')
def remove_server(server_id):
    ldpsi = LdapServer.query.filter_by(id=server_id).first()
    db.session.delete(ldpsi)
    db.session.commit()
    
    flash("Ldap Server {0} is removed.".format(ldpsi.fqn_hostname), "warning")
    
    return redirect(url_for('index.home'))



@index.route('/makemmrreplicator/')
def make_multi_master_replicator():
    r=0
    server_id = int(request.values.get("server_id"))
    ldp = MultiMaster()
    ldp.mmr_id = server_id
    ldp.replicator = 1
    db.session.add(ldp)
    r=1
    db.session.commit()
    
    ldp=LdapServer.query.filter_by(id=server_id).first()
    
    if r:
        flash("Ldap Server {0} is added as Master Server".format(ldp.fqn_hostname))
    else:
        flash("Master Ldap Server {0} is removed".format(ldp.fqn_hostname))

    return redirect(url_for('index.multi_master_replication'))

def get_mmr_list():
    ldaps=LdapServer.query.all()
    mmrs=[]
    for ldp in MultiMaster.query.all():
        if ldp.replicator:
            mmrs.append(ldp.mmr_id)
    return mmrs

def getConsumerProviderDict():
    pcDict={}
    providers = Provider.query.all()
    
    for p in providers:
        ldpp=LdapServer.query.filter_by(id=p.provider_id).first()
        ldpc=LdapServer.query.filter_by(id=p.consumer_id).first()
        if ldpc.id in pcDict:
            pcDict[ldpc.id].append(ldpp.id)
        else:
            pcDict[ldpc.id]=[ldpp.id]
            
    return pcDict

    
    

@index.route('/mmr/')
def multi_master_replication():

    mmrs = get_mmr_list()
    ldaps=LdapServer.query.all()
    pc = getConsumerProviderDict()
    id_host_dict ={}
    
    pca = {x:[] for x in mmrs}
    
    addServerButton = False
    if not len(ldaps) == len(mmrs):
        addServerButton = True
    
    
    for ldp in ldaps:
        print "ldpin", ldp.id,  mmrs, ldp.id in mmrs
        if ldp.id in mmrs:
            id_host_dict[ldp.id] = ldp.fqn_hostname
            for l in ldaps:
                if l.id in mmrs:
                    if not l == ldp:
                        if ldp.id not in pc:
                            pca[ldp.id].append(l.id)
                        else:
                            if not l.id in pc[ldp.id]:
                                pca[ldp.id].append(l.id)

    return render_template('multi_master.html', ldapservers=ldaps, mmrs=mmrs, pc=pc, pca=pca,
                                                id_host_dict=id_host_dict,
                                                addServerButton=addServerButton,
                                                
                                                )

@index.route('/removemaster/')
def remove_multi_master_replicator():
    server_id = int(request.values.get("server_id"))
    ldaps=Provider.query.filter_by(provider_id=server_id).first()

    if ldaps:
        flash ("This server is a provider for an Ldap Server. Please first remove this server as provider.", "warning")
        
    else:
        mmr=MultiMaster.query.filter(MultiMaster.mmr_id==server_id).first()
        db.session.delete(mmr)
        db.session.commit()
        flash("Master server is removed", "success")
    
    return redirect(url_for('index.multi_master_replication'))
            
@index.route('/addtestuser/<int:server_id>', methods=['GET', 'POST'])
def add_test_user(server_id):
    print "SERVER ID", server_id
    ldp = LdapServer.query.get(server_id)

    form = TestUser()
    data={'title': 'Add Test User [{0}]'.format(ldp.fqn_hostname), 'button': 'Add'}
    
    
    
    if form.validate_on_submit():
        
        ldp = ldapOLC('ldaps://{}:1636'.format(ldp.fqn_hostname), "cn=directory manager,o=gluu", ldp.ldap_password)
        r=None
        try:
            r = ldp.connect()
        except Exception as e:
            falsh("Connection to LDAPserver at port 1636 was failed: {0}".format(e), "error")

        if not r:
            flash("Connection to LDAPserver at port 1636 was failed: {0}".format(ldp.conn.result['description']), "error")
        
        if ldp.conn:
            if ldp.addTestUser(form.first_name.data, form.last_name.data,form.email.data):
                flash("Test User sucessfuly added.", "success")
            else:
                flash("CAdding user failed: {0}".format(ldp.conn.result['description']), "warning")

            return redirect(url_for('index.multi_master_replication'))
        
    return render_template('ldap_server.html', form=form,  data=data )
    

@index.route('/searchtestusers/<int:server_id>')
def search_test_users(server_id):
    
    print "SERVER ID", server_id
    ldps = LdapServer.query.get(server_id)
    
    users = []
    
    ldp = ldapOLC('ldaps://{}:1636'.format(ldps.fqn_hostname), "cn=directory manager,o=gluu", ldps.ldap_password)
    r=None
    try:
        r = ldp.connect()
    except Exception as e:
        falsh("Connection to LDAPserver at port 1636 was failed: {0}".format(e), "error")

    if not r:
        flash("Connection to LDAPserver at port 1636 was failed: {0}".format(ldp.conn.result['description']), "error")

    if ldp.conn:

        if not ldp.searchTestUsers():
            flash("Searching user failed: {0}".format(ldp.conn.result['description']), "error")
        else:
            users = ldp.conn.response
            print users
            for user in users:
                host = user['dn'].split('@')[1].split(',')[0]
                user['host']=host
    if users:
        st = '{0}({1})'.format(ldps.fqn_hostname, len(users))
        return render_template('test_users.html', server_id=server_id, server= st, users = users )
        
    return redirect(url_for('index.multi_master_replication'))

@index.route('/deletetestuser/<server_id>/<dn>')
def delete_test_user(server_id, dn):
    ldps = LdapServer.query.get(server_id)
    ldp = ldapOLC('ldaps://{}:1636'.format(ldps.fqn_hostname), "cn=directory manager,o=gluu", ldps.ldap_password)
    
    r=None
    try:
        r = ldp.connect()
    except Exception as e:
        falsh("Connection to LDAPserver at port 1636 was failed: {0}".format(e), "error")

    if not r:
        flash("Connection to LDAPserver at port 1636 was failed: {0}".format(ldp.conn.result['description']), "error")

    if ldp.conn:
        if ldp.delDn(dn):
            flash("Test User deleted", "success")
        else:
            flash("Test User deletation failed: {0}".format(ldp.conn.result['description']), "error")
            
    return redirect(url_for('index.search_test_users', server_id=server_id))
