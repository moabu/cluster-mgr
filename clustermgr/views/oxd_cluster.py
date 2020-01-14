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

oxd_cluster = Blueprint('oxd', __name__, template_folder='templates/oxd')
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
    return "test"
