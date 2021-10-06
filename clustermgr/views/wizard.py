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
from clustermgr.models import AppConfiguration, Server
from clustermgr.forms import WizardStep1

from clustermgr.core.license import license_reminder
from clustermgr.extensions import celery
from clustermgr.core.license import prompt_license

from clustermgr.tasks.wizard import wizard_step1, wizard_step2


wizard = Blueprint('wizard', __name__)
wizard.before_request(prompt_license)
wizard.before_request(license_reminder)


wizard_steps = ['Analyzing Server', 'Changing Hostname']


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
            app_conf.nginx_ssh_port = wform.nginx_ssh_port.data
            app_conf.modify_hosts = True
            db.session.add(app_conf)
            
            server = Server()
            server.ip = wform.ip.data.strip()
            server.hostname = wform.current_hostname.data.strip()
            server.ssh_port = wform.ssh_port.data
            server.primary_server = True
            
            db.session.add(app_conf)
            db.session.add(server)
            db.session.commit()
    
            task = wizard_step1.delay()
            print("TASK STARTED", task.id)

            title = "Incorporating Existing Server"

            whatNext = wizard_steps[1]
            nextpage = url_for('wizard.step2')

            return render_template('logger_single.html',
                       title=title,
                       steps=wizard_steps,
                       task=task,
                       cur_step=1,
                       auto_next=False,
                       multiserver=False,
                       nextpage=nextpage,
                       whatNext=whatNext
                       )


    return render_template( 'wizard/step1.html', wform=wform)

@wizard.route('/step2')
def step2():
    
    task = wizard_step2.delay()

    title = "Incorporating Existing Server"

    whatNext = "Add Gluu Server"
    nextpage = url_for('server.index')

    return render_template('logger_single.html',
               title=title,
               steps=wizard_steps,
               task=task,
               cur_step=2,
               auto_next=False,
               multiserver=False,
               nextpage=nextpage,
               whatNext=whatNext
               )
