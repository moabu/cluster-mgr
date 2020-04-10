
import requests as http_requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
http_requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from flask import Blueprint, render_template, url_for, flash, redirect, \
    session, request
from flask_login import login_required
from flask_menu import register_menu


from clustermgr.models import Server, AppConfiguration
from clustermgr.tasks.cluster import installNGINX
from clustermgr.forms import LoadBalancerForm
from clustermgr.extensions import db

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.license import license_required

load_balancer = Blueprint('loadbalancer', __name__, template_folder='templates')
load_balancer.before_request(prompt_license)
load_balancer.before_request(license_required)
load_balancer.before_request(license_reminder)

def checkNginxStatus(nginxhost):
    try:
        r=  http_requests.get('https://{}/clustermgrping'.format(nginxhost),
                                                        verify=False)
        if r.status_code == 200:
            return True, r.text.split()
    except:
        pass

    return False, []


@load_balancer.route('/menuindex')
@register_menu(load_balancer, '.gluuServerCluster.loadBalancer', 'Load Balancer', order=1, icon='fa fa-balance-scale')
def menuIndex():
    return redirect(url_for('load_balancer.install_nginx'))





@load_balancer.route('/install')
@register_menu(load_balancer, '.gluuServerCluster.loadBalancer.installNginx', 'Install', order=1)
@login_required
def install_nginx():
    """Initiates installation of nginx load balancer"""
    app_conf = AppConfiguration.query.first()

    if (not app_conf) or (not app_conf.nginx_host):
        flash("Please first configure Load Balancer")
        return redirect(url_for('load_balancer.setup_nginx'))

    if not request.args.get('next') == 'install':
        status = checkNginxStatus(app_conf.nginx_host)
        if status[0]:
            return render_template("load_balancer_install.html", 
                                servers=status[1])
        else:
            servers = Server.query.all()
            return render_template("load_balancer_about_to_install.html", 
                                            servers=servers, app_conf=app_conf)

    # Start nginx  installation celery task
    task = installNGINX.delay(app_conf.nginx_host)

    print("Install NGINX TASK STARTED", task.id)
    head = "Configuring NGINX Load Balancer on {0}".format(app_conf.nginx_host)
    nextpage = url_for('replication.multi_master_replication')
    whatNext = "LDAP Replication"

    return render_template('logger_single.html', title=head, server=app_conf.nginx_host,
                           task=task, nextpage=nextpage, whatNext=whatNext)

@load_balancer.route('/configure', methods=['GET', 'POST'])
@register_menu(load_balancer, '.gluuServerCluster.loadBalancer.setupNginx', 'Configure', order=2)
@login_required
def setup_nginx():
    cform = LoadBalancerForm()
    app_config = AppConfiguration.query.first()
    primary_server = Server.query.filter_by(primary_server=True).first()
    is_primary_deployed = True if primary_server and primary_server.gluu_server else False
        
    if not app_config:
        app_config = AppConfiguration()
        app_config.external_load_balancer = False
        db.session.add(app_config)

    submit_text = "Update" if app_config.nginx_host else "Save"

    if request.method == 'GET':
        cform.nginx_host.data = app_config.nginx_host
        cform.nginx_ip.data = app_config.nginx_ip
        cform.external_load_balancer.data = app_config.external_load_balancer
    else:
        if cform.external_load_balancer.data:
            cform.nginx_ip.validators= []

        if cform.validate_on_submit():
            app_config.nginx_host = cform.nginx_host.data

            if cform.external_load_balancer.data:
                app_config.nginx_ip = ''
                cform.nginx_ip.data = ''
            else:
                app_config.nginx_ip = cform.nginx_ip.data
                
            app_config.external_load_balancer = cform.external_load_balancer.data
            db.session.commit()
            flash("Load Balancer configuration {}d".format(submit_text.lower()), "success")

    return render_template("load_balancer_setup.html",
                            cform=cform,
                            submit_text=submit_text,
                            is_primary_deployed=is_primary_deployed,
                            )
