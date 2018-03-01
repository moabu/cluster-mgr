# -*- coding: utf-8 -*-
import os
import uuid

from flask import Blueprint, render_template, redirect, url_for, flash, \
    request, jsonify, session
from flask import current_app as app
from flask_login import login_required
from flask_login import current_user
from werkzeug.utils import secure_filename
from celery.result import AsyncResult
from flask import redirect


from clustermgr.extensions import db, wlogger
from clustermgr.models import AppConfiguration, Server  # , KeyRotation
from clustermgr.forms import WizardStep1


from celery.result import AsyncResult


from clustermgr.core.license import license_reminder
from clustermgr.extensions import celery
from clustermgr.core.license import prompt_license

from clustermgr.core.remote import RemoteClient, FakeRemote

from clustermgr.tasks.wizard import wizard_step1, wizard_step2


wizard = Blueprint('wizard', __name__)
wizard.before_request(prompt_license)
wizard.before_request(license_reminder)


@wizard.route('/step1',methods=['GET', 'POST'])
def step1():
    
    pserver = Server.query.filter_by(primary_server=True).first()
    if pserver:
        flash("Oops this service is not for you.",'warning')
        return redirect(url_for('index.home'))
 
    wform = WizardStep1()
    
    if request.method == 'POST':
        if wform.validate_on_submit():
            replication_pw = uuid.uuid4().hex
            app_conf = AppConfiguration()
            app_conf.nginx_host = wform.new_hostname.data.strip()
            app_conf.replication_pw = replication_pw
            app_conf.nginx_ip = wform.nginx_ip.data.strip() 
            app_conf.modify_hosts = True
            db.session.add(app_conf)
            
            server = Server()
            server.ip = wform.ip.data.strip()
            server.hostname = wform.current_hostname.data.strip()
            server.primary_server = True
            
            db.session.add(app_conf)
            db.session.add(server)
            db.session.commit()
    
            task = wizard_step1.delay()
            print "TASK STARTED", task.id

            servers = Server.query.all()
            return render_template('wizard/wizard_logger.html', step=1,
                           task_id=task.id, servers=servers)
                           

    return render_template( 'wizard/step1.html', wform=wform)

@wizard.route('/step2')
def step2():
    
    task = wizard_step2.delay()
    print "TASK STARTED", task.id

    servers = Server.query.all()
    return render_template('wizard/wizard_logger.html', step=2,
                           task_id=task.id, servers=servers)
