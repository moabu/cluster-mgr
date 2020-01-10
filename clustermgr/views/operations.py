# -*- coding: utf-8 -*-
import os
from time import strftime
import json
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session, current_app
from flask import current_app as app
from flask_login import login_required
from flask_login import current_user
from flask_menu import register_menu

from celery.result import AsyncResult
from clustermgr.models import AppConfiguration, Server


from clustermgr.core.license import license_reminder
from clustermgr.core.license import prompt_license


from clustermgr.forms import httpdCertificatesForm, SchemaForm
from clustermgr.core.clustermgr_installer import Installer

from clustermgr.tasks.cluster import update_httpd_certs_task

operations = Blueprint('operations', __name__)
operations.before_request(prompt_license)
operations.before_request(license_reminder)

msg_text = ''

@operations.route('/menuindex')
@register_menu(operations, '.gluuServerCluster.operations', 'Operations', order=8, icon='fa fa-cogs')
def menuIndex():
    return redirect(url_for('operations.httpd_certs'))

@login_required
@operations.route('/httpdcerts')
@register_menu(operations, '.gluuServerCluster.operations.httpdCertificates', 'Web Certificates', order=1)
def httpd_certs():

    app_config = AppConfiguration.query.first()
    
    server = Server.query.filter_by(primary_server=True).first()

    installer = Installer(server, app_config.gluu_version)
    httpd_key = installer.get_file(os.path.join(installer.container, 'etc/certs/httpd.key'))

    httpd_crt = installer.get_file(os.path.join(installer.container, 'etc/certs/httpd.crt'))
    
    cert_form = httpdCertificatesForm()
    cert_form.httpd_key.data = httpd_key
    cert_form.httpd_crt.data = httpd_crt
    
    return render_template('httpd_certificates.html', cert_form=cert_form)

@login_required
@operations.route('/updatehttpdcertificate', methods=['POST'])
def update_httpd_certificate():
    cert_form = httpdCertificatesForm()
    httpd_key = cert_form.httpd_key.data
    httpd_crt = cert_form.httpd_crt.data
    
    task = update_httpd_certs_task.delay(httpd_key, httpd_crt)
    print "TASK STARTED", task.id
    head = "Updating HTTPD Certificate"
    nextpage = "index.home"
    whatNext = "Go to Dashboard"
    return render_template("logger_single.html", heading=head, server="",
                           task=task, nextpage=nextpage, whatNext=whatNext)

@login_required
@register_menu(operations, '.gluuServerCluster.operations.customSchema', 'Custom Schema', order=2)
@operations.route('/customschema', methods=['GET', 'POST'])
def custom_schema():
    sform = SchemaForm()
    schemafiles = os.listdir(app.config['SCHEMA_DIR'])
    return render_template("custom_schema.html",
                schemafiles=schemafiles,
                sform=sform
                )

@login_required
@operations.route('/removecustomschema/<schema_file>')
def remove_custom_schema(schema_file):
    """This view deletes custom schema file"""

    file_path = os.path.join(app.config['SCHEMA_DIR'], schema_file)
    if os.path.exists(file_path):
        os.remove(file_path)
    return redirect(url_for('index.app_configuration'))


def isUpgradeAvailable():
    return True

@login_required
@register_menu(operations, '.gluuServerCluster.operations.upgrade', 'Upgrade', order=3, visible_when=isUpgradeAvailable)
@operations.route('/upgrade', methods=['GET'])
def upgrade():
    return "Uprade Cluster Managaer"
