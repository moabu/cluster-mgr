"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
import os

from flask import Blueprint, render_template, url_for, flash, redirect, \
    jsonify, request, session

from flask_login import login_required
from flask_menu import register_menu
from wtforms import HiddenField

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.license import license_required

from clustermgr.models import GServer, ConfigParam, AppConfiguration, CacheServer
from clustermgr.forms import ServerForm, OxdSettingsForm

oxd_cluster = Blueprint('oxd', __name__)
oxd_cluster.before_request(prompt_license)
oxd_cluster.before_request(license_required)
oxd_cluster.before_request(license_reminder)

@oxd_cluster.route('/oxdCluster')
@register_menu(oxd_cluster, '.oxdCluster', 'oxd Cluster', order=1, icon='fa fa-folder')
def menuIndex():
    return redirect( url_for('oxd.home') )


@oxd_cluster.route('/servers')
@register_menu(oxd_cluster, '.oxdCluster.servers', 'Servers', order=1, icon='fa fa-server')
@login_required
def home():
    oxd_settings = ConfigParam.get('oxd_settings', {})
    if not oxd_settings:
        flash("Please first configure oxd Cluster.", 'warning')
        return redirect( url_for('oxd.configure', next_url='oxd.add_server') )

    servers = GServer.get_servers('oxd')
    for server in servers:
        server.os = server.data.get('os')

    return render_template('oxd/dashboard.html',
                    servers=servers,
                    oxd_settings=oxd_settings,
                    )

@oxd_cluster.route('/servers/addserver', methods=['GET', 'POST'])
@login_required
def add_server():
    sid = request.args.get('sid')

    if sid:
        setattr(ServerForm, 'sid', HiddenField(default=sid))

    form = ServerForm()
    del form.ldap_password
    del form.ldap_password_confirm

    if request.method == 'GET':
        if sid:
            oxd_server = GServer.get_server(form.sid.data)
            if oxd_server:
                form.hostname.data = oxd_server.hostname
                form.ip.data = oxd_server.ip

    elif request.method == 'POST' and form.validate_on_submit():
        if sid and form.sid.data:
            oxd_server = GServer.get_server(form.sid.data)
        else:
            oxd_server = GServer.new('oxd')
        oxd_server.hostname = form.hostname.data
        oxd_server.ip = form.ip.data
        oxd_server.save()
        if sid:
            flash("oxd server was saved", 'success')
        else:
            flash("oxd server was added", 'success')
        return redirect( url_for('oxd.home') )

    return render_template('oxd/server.html',
                    form=form,
                    sid=sid,
                    )

@oxd_cluster.route('/configure', methods=['GET', 'POST'])
@register_menu(oxd_cluster, '.oxdCluster.configure', 'Configure', order=2, icon='fa fa-server')
@login_required
def configure():
    next_url = request.args.get('next_url')
    
    form = OxdSettingsForm()
    app_conf = AppConfiguration.query.first()
    cache_server = CacheServer.query.first()
    oxd_settings = ConfigParam.get('oxd_settings', {})

    if not(app_conf and not app_conf.use_ldap_cache and cache_server and cache_server.installed):
        del form.use_gluu_cluster_redis

    if request.method == 'GET':
        form.oxd_version.data = oxd_settings.get('version')
        op_host_default = 'https://' + app_conf.nginx_host if (app_conf and app_conf.nginx_host) else ''
        form.op_host.data = oxd_settings.get('op_host', op_host_default)
        form.scope.data = oxd_settings.get('scope','openid, profile, email')
        form.use_gluu_cluster_redis.data = oxd_settings.get('use_gluu_cluster_redis')
    elif request.method == 'POST' and form.validate_on_submit():
        oxd_settings['version'] = form.oxd_version.data
        oxd_settings['op_host'] = form.op_host.data
        oxd_settings['scope'] = form.scope.data
        oxd_settings['use_gluu_cluster_redis'] = form.use_gluu_cluster_redis.data
    
        ConfigParam.set('oxd_settings',oxd_settings)
        
        flash("oxd cluster configuration was saved", 'success')
        
        if next_url:
            return redirect( url_for(next_url) )
    
    
    return render_template('oxd/settings.html',
                    form=form,
                    oxd_settings=oxd_settings,
                    next_url=next_url
                    )
                    
                                        
