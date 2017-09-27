"""A Flask blueprint with the views and logic dealing with the Cache Management
of Gluu Servers"""
from flask import Blueprint, render_template, url_for, flash, redirect, \
    request, session


cache_mgr = Blueprint('cachemgr', __name__, template_folder='templates')


@cache_mgr.route('/')
def index():
    return 'Home of cache manager'
