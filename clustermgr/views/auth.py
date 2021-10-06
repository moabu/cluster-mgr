import configparser
import os
import socket
import hashlib
import requests
import json
from urllib.parse import urljoin

from flask import current_app, make_response
from flask import Blueprint
from flask import request
from flask import url_for
from flask import redirect
from flask import render_template
from flask import flash
from flask import session
from flask_login import UserMixin
from flask_login import login_user
from flask_login import logout_user
from flask_login import current_user
from flask import g

from ..extensions import login_manager
from ..forms import LoginForm, SignUpForm, OxdConfigForm
from ..models import Server


auth_bp = Blueprint("auth", __name__)

login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


class User(UserMixin):
    def __init__(self, username, password):
        self.username = username
        self.password = password

    def get_id(self):
        return self.username


def user_from_config(cfg_file, username):
    parser = configparser.SafeConfigParser()
    parser.read(cfg_file)

    try:
        cfg = dict(parser.items("user"))
    except configparser.NoSectionError:
        return

    if username != cfg["username"]:
        return

    user = User(cfg["username"]+'@local', cfg["password"])
    return user


@login_manager.user_loader
def load_user(username):
    user = User(username, "")
    return user


@auth_bp.route("/login/", methods=["GET", "POST"])
def login():

    cfg_file = current_app.config["AUTH_CONFIG_FILE"]

    if not os.path.exists(cfg_file):
        return redirect(url_for('auth.signup'))

    if current_user.is_authenticated:
        return redirect(url_for("index.home"))

    form = LoginForm()
    if form.validate_on_submit():

        user = user_from_config(cfg_file, form.username.data)

        enc_password = hashlib.sha224(form.password.data.encode()).hexdigest()

        if user and enc_password == user.password:
            next_ = request.values.get('next')
            login_user(user)
            if not next_ == 'None':
                return redirect(next_)
            return redirect(url_for('index.home'))

        flash("Invalid username or password.", "warning")

    server_num = Server.query.count()
    
    if os.path.exists(os.path.join(current_app.config['DATA_DIR'], 'oxd_config.json')):
        oxd_login = url_for("auth.oxd_login")
    else:
        oxd_login = None
    
    return render_template('auth_login.html', form=form, server_num=server_num,
        oxd_login = oxd_login
    )


@auth_bp.route("/logout/")
def logout():
    logout_user()

    pw_file = os.path.join(current_app.config['DATA_DIR'], '.pw')

    if os.path.exists(pw_file):
            os.remove(pw_file)

    if session.get('oxd_session'):
        oxd_config = get_oxd_config()
        oxd_access_token = get_client_token(oxd_config)
        post_logout_redirect_uri = urljoin(request.host_url, url_for('auth.oxd_logout_callback'))

        data = {
            "oxd_id": oxd_config['oxd_id'],
            "post_logout_redirect_uri": post_logout_redirect_uri,
        }

        result = post_data(
                urljoin(oxd_config['oxd_server'], 'get-logout-uri'), 
                data, 
                oxd_access_token
            )

        logout_redirect_uri = result['uri']
        session.clear()
        return redirect(result['uri'])

    else:

        return redirect(url_for("auth.login"))


def get_oxd_config():
    
    oxd_config_json_fn = os.path.join(current_app.config['DATA_DIR'], 'oxd_config.json')
    
    if not os.path.exists(oxd_config_json_fn):
        return {}
    
    with open(oxd_config_json_fn) as f:
        oxd_config = json.load(f)

    return oxd_config
    
def post_data(end_point, data, access_token=''):
    """Posts data to oxd server"""
    headers = {
                'Content-type': 'application/json', 
                'Authorization': "Bearer " + access_token
        }

    result = requests.post(
                    end_point, 
                    data=json.dumps(data), 
                    headers=headers, 
                    verify=False
                    )

    return result.json()

def get_client_token(oxd_config):
    data = {
      "op_host": oxd_config['op_host'],
      "scope": ["openid", "oxd", "profile", "user_name", "permission"],
      "client_id": oxd_config['client_id'],
      "client_secret": oxd_config['client_secret'],
      "authentication_method": "",
      "algorithm": "",
      "key_id": ""
    }

    result = post_data(
                urljoin(oxd_config['oxd_server'], 'get-client-token'), 
                data
            )

    return result['access_token']

@auth_bp.route("/oxd/authorization_url/")
def oxd_login():
    if current_user.is_authenticated:
        return redirect(url_for("index.home"))

    oxd_config = get_oxd_config()
    oxd_access_token = get_client_token(oxd_config)
    session['access_token'] = oxd_access_token

    data = {
      "oxd_id": oxd_config['oxd_id'],
      "scope": ["openid", "oxd", "profile", "user_name", "permission"],
      "acr_values": [],
    }

    result = post_data(
                urljoin(oxd_config['oxd_server'], 'get-authorization-url'),
                data, 
                oxd_access_token
            )

    return redirect(result['authorization_url'])


@auth_bp.route("/oxd/login")
def oxd_login_callback():
    oxd_config = get_oxd_config()
    data = {
        "oxd_id": oxd_config['oxd_id'],
        "code": request.args['code'],
        "state": request.args['state']
    }

    result = post_data(
            urljoin(oxd_config['oxd_server'], 'get-tokens-by-code'), 
            data, 
            session['access_token']
            )

    data = {
        "oxd_id": oxd_config['oxd_id'],
        "access_token": result['access_token']
    }

    result = post_data(
            urljoin(oxd_config['oxd_server'], 'get-user-info'),
            data, 
            session['access_token']
            )

    if result.get('user_name'):
        username = result['user_name']
    elif result.get('preferred_username'):
        username = result['preferred_username']
    else:
        username = None

    if result.get('sub') and username:
        if result['user_name'] == 'admin' or 'clusteradmin' in result.get('role', []):
            user = User(result['user_name']+'@openid', None)
            login_user(user)
            session['oxd_session'] = result
            next_ = request.values.get('next','').strip()
            if next_:
                return redirect(next_)

            return redirect(url_for('index.home'))

    
    logout_user()
    flash("Invalid username or password.", "warning")
    return redirect(url_for("index.home"))


@auth_bp.route("/oxd/logout")
def oxd_logout_callback():
    """Callback for OXD client_frontchannel.
    """
    # TODO: decide whether we need this callback
    logout_user()
    return redirect(url_for("index.home"))


@auth_bp.route("/signup", methods=['GET', 'POST'])
def signup():

    if request.method == 'POST':
        form = SignUpForm(request.form)
        if form.validate():

            config_file = current_app.config["AUTH_CONFIG_FILE"]

            username = form.username.data.strip()
            password = form.password.data.strip()

            enc_password = hashlib.sha224(form.password.data.encode()).hexdigest()

            config = configparser.RawConfigParser()
            config.add_section('user')
            config.set('user', 'username', username)
            config.set('user', 'password', enc_password)

            with open(config_file, 'w') as configfile:
                config.write(configfile)

            user = user_from_config(config_file, username)
            login_user(user)
            return redirect(url_for('index.home'))

        else:
            flash("Please correct errors and re-submit the form")

    else:
        form = SignUpForm(request.form)

    return render_template('auth_signup.html', form=form)

@auth_bp.route("/oxd/configuration/", methods=['GET', 'POST'])
def oxd_login_configuration():
    form = OxdConfigForm()
    oxd_config_json_fn = os.path.join(current_app.config['DATA_DIR'], 'oxd_config.json')
    register_client = not os.path.exists(oxd_config_json_fn)

    if register_client:
        form.oxd_id.validators = []
        form.client_id.validators = []
        form.client_secret.validators = []

        del form._fields['oxd_id']
        del form._fields['client_id']
        del form._fields['client_secret']
    else:
        oxd_config = get_oxd_config()
        form.op_host.data = oxd_config['op_host']
        form.oxd_server.data = oxd_config['oxd_server']
        form.oxd_id.data = oxd_config['oxd_id']
        form.client_id.data = oxd_config['client_id']
        form.client_secret.data = oxd_config['client_secret']
        
    if request.method == 'POST':
        if request.form.get('register_client'):

            data = {
                  "redirect_uris": [ 
                                urljoin(request.host_url, "auth/oxd/login"),
                                request.host_url
                            ],
                  "op_host": form['op_host'].data,
                  "post_logout_redirect_uris": [urljoin(request.host_url, "auth/oxd/logout")],
                  "application_type": "web",
                  "response_types": ["code"],
                  "grant_types": ["authorization_code", "client_credentials"],
                  "scope": ["openid", "oxd", "user_name", "permission"],
                  "acr_values": [""],
                  "client_name": "Cluster Manager Oxd Client",
                  "client_jwks_uri": "",
                  "client_token_endpoint_auth_method": "",
                  "client_request_uris": [""],
                  "client_frontchannel_logout_uris": [""],
                  "client_sector_identifier_uri": "",
                  "contacts": [""],
                  "ui_locales": [""],
                  "claims_locales": [""],
                  "claims_redirect_uri": [],
                  "client_id": "",
                  "client_secret": "",
                  "trusted_client": True
                }

            result = post_data(
                urljoin(form['oxd_server'].data, 'register-site'), 
                data, 
                ''
            )
            
            if 'client_secret' in result:
                result['oxd_server'] = form['oxd_server'].data
                with open(oxd_config_json_fn, 'w') as w:
                    w.write(json.dumps(result, indent=2))
            
                flash("Oxd client successfully registered", 'success')
            
                return redirect(url_for('index.home'))
            else:
                flash(
                    "An error ocurred while registerin client. oxd response: {}".format(json.dumps(result)),
                    'warning'
                    )
                
    return render_template('oxd_config.html', form=form, register_client=register_client)
    

