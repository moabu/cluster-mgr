# -*- coding: utf-8 -*-
import os
import json
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session
from flask import current_app as app
from flask_login import login_required
from flask_login import current_user
from werkzeug.utils import secure_filename
from celery.result import AsyncResult


from clustermgr.extensions import db, wlogger
from clustermgr.models import AppConfiguration, Server  # , KeyRotation
from clustermgr.forms import AppConfigForm, SchemaForm, \
    TestUser, InstallServerForm, LdapSchema  # , KeyRotationForm

from ldap.schema import AttributeType, ObjectClass, LDAPSyntax
from clustermgr.core.utils import get_setup_properties
from clustermgr.core.ldap_functions import LdapOLC, getLdapConn
from clustermgr.core.ldifschema_utils import OpenDjSchema


from clustermgr.tasks.cluster import upgrade_clustermgr_task, register_objectclass
from clustermgr.core.license import license_reminder, prompt_license
from clustermgr.extensions import celery


from clustermgr.core.clustermgr_installer import Installer
from clustermgr.tasks.cluster import get_os_type

attributes = Blueprint('attributes', __name__)
attributes.before_request(prompt_license)
attributes.before_request(license_reminder)


@attributes.route('/')
@login_required
def home():
    try:
        appconf = AppConfiguration.query.first()
    except:
        return render_template('index_nodb.html')
    
    if not appconf:
        return render_template('intro.html', setup='cluster')

    print appconf.object_class_base
    
    if not appconf.object_class_base:
        return redirect(url_for('attributes.object_class'))
   
    server = Server.query.filter_by(primary_server=True).first()
   
    ldp = getLdapConn(  server.hostname,
                        "cn=directory manager",
                        server.ldap_password
                        )
    attrib_list_in_class = []
    objcl_s = ldp.getObjectClass(appconf.object_class_base)
    if objcl_s:
        objcl_obj = ObjectClass(objcl_s)
        attrib_list_in_class = list(objcl_obj.may)
   
    attrib_list = []
    attrib_list_s = ldp.getCustomAttributes()
    attrib_list = [ AttributeType(str(a)) for a in attrib_list_s ]
   
   
    return render_template('attributes.html', 
                            attrib_list_in_class=attrib_list_in_class, 
                            attrib_list=attrib_list,
                            ojectclass=appconf.object_class_base
                            )
    
@attributes.route('/objectclass')
def object_class():
    appconf = AppConfiguration.query.first()
    if appconf.object_class_base:
        flash("Object classname was allready determined")
        return redirect(url_for('attributes.home'))
    return render_template('attributes_object_class.html')
    
@attributes.route('/createobjecclass')
def create_objecclass():
    server = Server.query.filter_by(primary_server=True).first()
    #object_class_choice = request.args.get('gluuObjectClass', '1')
    #if object_class_choice == '1':
    #    object_class = 'gluuCustomPerson'
    #else:
    #    object_class = request.args.get('objectClassname')
    #    if not object_class:
    #        object_class = 'clustermgrAttributes'
            
    object_class = request.args.get('objectClassname')
    if not object_class.strip():
        object_class='clustermgrAttributes'
    
    
    
    task = register_objectclass.delay(object_class)
    head = "Registering Object Class {}".format(object_class)

    nextpage = "attributes.home"
    whatNext = "Custom Attributes"

    return render_template("logger.html", heading=head, server=server,
                           task=task, nextpage=nextpage, whatNext=whatNext)
    


def get_custom_schema_path():
    setup_prop = get_setup_properties()
    inumOrg = setup_prop['inumOrg']
    inumOrgFN = inumOrg.replace('@','').replace('!','').replace('.','')
    custom_schema_file = '102-{}.ldif'.format(inumOrgFN)
    custom_schema_path = os.path.join(app.config["DATA_DIR"], custom_schema_file)
    return custom_schema_path

@attributes.route('/editattribute', methods=['GET', 'POST'])
def edit_attribute():
    server = Server.query.filter_by(primary_server=True).first()
    appconf = AppConfiguration.query.first()
        
    editing = request.args.get('oid')
    syntax_file = os.path.join(app.config["DATA_DIR"],'syntaxes.json')
    setup_prop = get_setup_properties()
    inumOrg = setup_prop['inumOrg']
    inumOrgFN = inumOrg.replace('@','').replace('!','').replace('.','')
    
    ldp = getLdapConn(  server.hostname,
                        "cn=directory manager",
                        server.ldap_password
                        )

    
    if not os.path.exists(syntax_file):

        ldap_response = ldp.getSyntaxes()
        attr_list = []

        for ats in ldap_response[0]['attributes']['ldapSyntaxes']:
            a=AttributeType(str(ats))
            attr_list.append((a.oid, a.desc))

        with open(syntax_file, 'w') as sf:
            json.dump(attr_list, sf)
    else:
        attr_list = json.loads(open(syntax_file).read())
    
    form = LdapSchema()
    form.syntax.choices = attr_list
    
    if request.method == 'GET':
        if editing:
        
            a_s=ldp.getAttributebyOID(editing)
            if a_s:
                a = AttributeType(str(a_s))
        
                form.oid.data = a.oid
                form.names.data = ' '.join(a.names)
                form.desc.data = a.desc
                form.syntax_len.data = a.syntax_len
                form.syntax.data = a.syntax
                form.single_value.data = a.single_value
                form.collective.data = a.collective
                if a.substr:
                    form.substr.data = a.substr
                if a.equality:
                    form.equality.data = a.equality
                if a.ordering:
                    form.ordering.data = a.ordering
        
    if request.method == 'POST':
                
        if form.validate_on_submit():

            oid = form.oid.data
            if not oid:
                if not appconf.attribute_oid:
                    appconf.attribute_oid = 100
                oid_postfix = appconf.attribute_oid 
                
                oid = '1.3.6.1.4.1.48710.1.5.{}'.format(oid_postfix)
                
                appconf.attribute_oid  += 1
                db.session.commit()
                
            names = form.names.data.strip().replace(' ','')
            x_origin = inumOrgFN
            desc = form.desc.data.strip()
            syntax_len = form.syntax_len.data
            syntax = form.syntax.data
            substr = form.substr.data
            single_value = form.single_value.data
            collective = form.collective.data
            equality = form.equality.data
            ordering = form.ordering.data

            a=AttributeType()
            a = AttributeType()
            a.oid = str(oid)
            a.names = (str(names),)
            a.syntax = str(syntax)
            a.x_origin = str(x_origin)
            a.desc = str(desc)
            a.sup = ()
            a.equality = str(equality)
            a.substr = str(substr)
            a.single_value = single_value
            a.x_ordered = ''
            a.ordering = str(ordering)
            a.syntax_len = syntax_len
            a.collective = collective
            a.no_user_mod = False
            a.usage = False
            a.obsolete = False
            result = ldp.addAttribute(a, editing, appconf.object_class_base)
            
            if not result[0]:
                flash(result[1], 'danger')
            else:
                flash('Attribute {} was added'.format(names), 'success')
                
                r = ldp.addAtributeToObjectClass(appconf.object_class_base, names)
                if r[0]:
                    flash('Attribute {} was added to object class {}'.format(names, appconf.object_class_base), 'success')
                    return redirect(url_for('attributes.home'))
                else:
                    flash('Could not add attribute {} to object class {}. Reason: {}'.format(names, appconf.object_class_base, r[1]), 'danger')
        
    return render_template('schema_form.html', form=form)

@attributes.route('/uploadschemaprimary')
def upload_schema_to_primary():
    server = Server.query.filter_by(primary_server=True).first()
    appconf = AppConfiguration.query.first()
    
    my_schema = OpenDjSchema(custom_schema_path)
    custom_schema = OpenDjSchema('/tmp/77-customAttributes.ldif')
    
    oc = custom_schema.get_class_by_name('gluuCustomPerson')
    may_list = list(oc.may)
    changed = False
    for a in my_schema.attribute_names:
        if not a in may_list:
            may_list.append(a)
            changed = True
            
    if changed:
        oc.may = tuple(may_list)
        custom_schema.write()
        installer.c.upload('/tmp/77-customAttributes.ldif', custom_attrib)

    installer.run('/etc/init.d/opendj restart')

    flash("Schema file is uploaded to server", "success")
    return redirect(url_for('index.app_configuration'))

@attributes.route('/removeattribute/<oid>/<name>')
def remove_attribute(oid,name):
    server = Server.query.filter_by(primary_server=True).first()
    appconf = AppConfiguration.query.first()
    ldp = getLdapConn(  server.hostname,
                        "cn=directory manager",
                        server.ldap_password
                        )
    ldp.removeAtributeFromObjectClass(appconf.object_class_base, name)
    ldp.removeAttribute(oid)

    return redirect(url_for('attributes.home'))


@attributes.route('/repopulateobjectclass')
def repopulate_objectclass():
    server = Server.query.filter_by(primary_server=True).first()
    appconf = AppConfiguration.query.first()
        
    setup_prop = get_setup_properties()
    inumOrg = setup_prop['inumOrg']
    inumOrgFN = inumOrg.replace('@','').replace('!','').replace('.','')
    ldp = getLdapConn(  server.hostname,
                        "cn=directory manager",
                        server.ldap_password
                        )

    ldp = getLdapConn(  server.hostname,
                        "cn=directory manager",
                        server.ldap_password
                        )
                        
    attrib_list_in_class = []
    
    objcl_s = ldp.getObjectClass(appconf.object_class_base)

    attrib_list_s = ldp.getCustomAttributes()
    attrib_list = [ AttributeType(str(a)) for a in attrib_list_s ]
    attrib_name_list = [ a.names[0] for a in attrib_list ]

    r = ldp.addAtributeToObjectClass(appconf.object_class_base, attrib_name_list)

    if not r[0]:
        flash(r[1], 'danger')
    else:
        flash("Object Class re-populated", 'success')
    return redirect(url_for('attributes.home'))
