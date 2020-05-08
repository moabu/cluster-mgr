
import requests as http_requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
http_requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from flask import Blueprint, render_template, url_for, flash, redirect, \
    session, request
from flask_login import login_required
from flask_menu import register_menu


from clustermgr.models import ConfigParam
from clustermgr.tasks.cluster import installNGINX
from clustermgr.forms import LoadBalancerForm
from clustermgr.extensions import db

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.license import license_required

load_balancer = Blueprint('load_balancer', __name__, template_folder='templates')
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
    lb_config = ConfigParam.get('load_balancer')

    if (not lb_config) or (not lb_config.data.get('hostname')):
        flash("Please first configure Load Balancer")
        return redirect(url_for('load_balancer.configure'))

    if not request.args.get('next') == 'install':
        status = checkNginxStatus(lb_config.data.hostname)
        if status[0]:
            return render_template("load_balancer_install.html", 
                                servers=status[1])
        else:
            servers = ConfigParam.get_servers()
            return render_template("load_balancer_about_to_install.html", 
                                            servers=servers, lb_config=lb_config)

    # Start nginx  installation celery task
    task = installNGINX.delay(lb_config.data.hostname)

    print("Install NGINX TASK STARTED", task.id)
    head = "Configuring NGINX Load Balancer on {0}".format(lb_config.data.hostname)
    nextpage = url_for('replication.multi_master_replication')
    whatNext = "LDAP Replication"

    return render_template('logger_single.html', title=head, server=lb_config.data.hostname,
                           task=task, nextpage=nextpage, whatNext=whatNext)

@load_balancer.route('/configure', methods=['GET', 'POST'])
@register_menu(load_balancer, '.gluuServerCluster.loadBalancer.setupNginx', 'Configure', order=2)
@login_required
def configure():
    cform = LoadBalancerForm()
    next_url = request.args.get('next')
    primary_server = ConfigParam.get_primary_server()
    submit_text = "Update Configuration"
    is_primary_deployed = True if primary_server and primary_server.data.get('gluu_server') else False
    load_balancer_config = ConfigParam.get('load_balancer')

    if not load_balancer_config:
        submit_text = "Save Configuration"
        load_balancer_config = ConfigParam.new('load_balancer', data={'hostname':'', 'ip':'', 'external': False})

    if request.method == 'GET':
        if next_url:
            submit_text = "Save and Continue" 
        cform.nginx_host.data = load_balancer_config.data.hostname
        cform.nginx_ip.data = load_balancer_config.data.ip
        cform.external_load_balancer.data = load_balancer_config.data.external
    else:
        #if cform.external_load_balancer.data:
        #    cform.nginx_ip.validators= []

        if cform.validate_on_submit():
            load_balancer_config.data.hostname = cform.nginx_host.data
            load_balancer_config.data.external = cform.external_load_balancer.data
            if cform.external_load_balancer.data:
                load_balancer_config.data.ip = ''
            else:
                load_balancer_config.data.ip = cform.nginx_ip.data
                
            load_balancer_config.save()

            flash("Load Balancer configuration saved".format("success"))
            
            if next_url:
                return redirect(next_url)

    return render_template("load_balancer_config.html",
                            cform=cform,
                            submit_text=submit_text,
                            is_primary_deployed=is_primary_deployed,
                            next=request.args.get('next'),
                            )
