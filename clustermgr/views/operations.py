# -*- coding: utf-8 -*-
import os
from time import strftime
import json
from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session, current_app
from flask import current_app as app
from flask_login import login_required
from flask_login import current_user
from celery.result import AsyncResult
from clustermgr.models import AppConfiguration, Server


from clustermgr.core.license import license_reminder
from clustermgr.core.license import prompt_license


from clustermgr.forms import httpdCertificatesForm
from clustermgr.core.clustermgr_installer import Installer

from clustermgr.tasks.cluster import update_httpd_certs_task

operations = Blueprint('operations', __name__)
operations.before_request(prompt_license)
operations.before_request(license_reminder)

msg_text = ''

@operations.route('/httpdcerts')
def httpd_certs():

    app_config = AppConfiguration.query.first()
    
    server = Server.query.filter_by(primary_server=True).first()

    installer = Installer(server, app_config.gluu_version, ssh_port=server.ssh_port)
    httpd_key = installer.get_file(os.path.join(installer.container, 'etc/certs/httpd.key'))

    httpd_crt = installer.get_file(os.path.join(installer.container, 'etc/certs/httpd.crt'))
    
    cert_form = httpdCertificatesForm()
    cert_form.httpd_key.data = httpd_key
    cert_form.httpd_crt.data = httpd_crt
    
    return render_template('httpd_certificates.html', cert_form=cert_form)


@operations.route('/updatehttpdcertificate', methods=['POST'])
def update_httpd_certificate():
    cert_form = httpdCertificatesForm()
    httpd_key = cert_form.httpd_key.data
    httpd_crt = cert_form.httpd_crt.data
    
    task = update_httpd_certs_task.delay(httpd_key, httpd_crt)
    print("TASK STARTED", task.id)
    head = "Updating HTTPD Certificate"
    nextpage = "index.home"
    whatNext = "Go to Dashboard"
    return render_template("logger_single.html", heading=head, server="",
                           task=task, nextpage=nextpage, whatNext=whatNext)
