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
from clustermgr.models import ConfigParam
from clustermgr.forms import WizardStep1

from clustermgr.core.license import license_reminder
from clustermgr.extensions import celery
from clustermgr.core.license import prompt_license

from clustermgr.core.remote import RemoteClient, FakeRemote

from clustermgr.tasks.wizard import wizard_step1, wizard_step2


wizard = Blueprint('wizard', __name__)
wizard.before_request(prompt_license)
wizard.before_request(license_reminder)


wizard_steps = ['Analyzing Server', 'Changing Hostname']


@wizard.route('/step1',methods=['GET', 'POST'])
def step1():
    """
    pserver = ConfigParam.get_primary_server()
    if pserver:
        flash("Oops this service is not for you.",'warning')
        return redirect(url_for('index.home'))
    """
    wform = WizardStep1()

    if 1:
    #if request.method == 'POST':
            """
            if wform.validate_on_submit():
                replication_pw = uuid.uuid4().hex
                ldap_replication = ConfigParam.get('ldap_replication')
                if not ldap_replication:
                    ldap_replication = ConfigParam.new(
                        'ldap_replication',
                        data={
                            'password': replication_pw,
                            'use_ip': False
                            }
                        )
                    ldap_replication.save()

                load_balancer = ConfigParam.get_or_new('load_balancer')

                load_balancer.data.hostname =  wform.new_hostname.data.strip()
                load_balancer.data.ip = wform.nginx_ip.data.strip()
                load_balancer.data.external = False
                load_balancer.save()

                server = ConfigParam.new(
                        'gluuserver', 
                        data={
                            'hostname': wform.current_hostname.data.strip(),
                            'ip': wform.ip.data.strip(),
                            'primary': True,
                            'mmr': False,
                            }
                        )

                server.save()
                """
            task = wizard_step1.delay()

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
    print("TASK STARTED", task.id)

    
    title = "Incorporating Existing Server"

    whatNext = "Install Nginx Proxy Server"
    nextpage = url_for('cluster.install_nginx')

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
