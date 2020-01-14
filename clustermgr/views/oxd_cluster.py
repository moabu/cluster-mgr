"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
import os

from flask import Blueprint, render_template, url_for, flash, redirect, \
    jsonify, request, session

from flask_login import login_required
from flask_menu import register_menu


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
    return redirect(url_for('oxd_cluster.home'))


@oxd_cluster.route('/servers')
@register_menu(oxd_cluster, '.oxdCluster.servers', 'Servers', order=1, icon='fa fa-server')
@login_required
def home():
    servers = []
    oxd_version = ConfigParam.get('oxd_version')

    return render_template('oxd/dashboard.html',
                    servers=servers,
                    oxd_version=oxd_version,
                    )

@oxd_cluster.route('/servers/addserver')
@login_required
def add_server():
    form = ServerForm()

    return render_template('oxd/server.html',
                    form=form,
                    
                    )

@oxd_cluster.route('/settings', methods=['GET', 'POST'])
@register_menu(oxd_cluster, '.oxdCluster.settings', 'Settings', order=2, icon='fa fa-server')
@login_required
def settings():
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
    elif request.method == 'POST':
        oxd_settings['version'] = form.oxd_version.data
        oxd_settings['op_host'] = form.op_host.data
        oxd_settings['scope'] = form.scope.data
        oxd_settings['use_gluu_cluster_redis'] = form.use_gluu_cluster_redis.data
    
        ConfigParam.set('oxd_settings',oxd_settings)
    
    return render_template('oxd/settings.html',
                    form=form,
                    oxd_settings = oxd_settings,
                    )
                    
                                        
