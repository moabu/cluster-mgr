import ConfigParser
import socket

from flask import current_app
from flask import Blueprint
from flask import request
from flask import url_for
from flask import redirect
from flask import render_template
from flask import flash
from flask_login import UserMixin
from flask_login import login_user
from flask_login import logout_user
from flask_login import current_user
from oxdpython import Client
from oxdpython.exceptions import OxdServerError

from ..extensions import login_manager
from ..forms import LoginForm


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
    parser = ConfigParser.SafeConfigParser()
    parser.read(cfg_file)

    try:
        cfg = dict(parser.items("user"))
    except ConfigParser.NoSectionError:
        return

    if username != cfg["username"]:
        return

    user = User(cfg["username"], cfg["password"])
    return user


@login_manager.user_loader
def load_user(username):
    user = User(username, "")
    return user


@auth_bp.route("/login/", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index.home"))

    form = LoginForm()
    if form.validate_on_submit():
        cfg_file = current_app.config["AUTH_CONFIG_FILE"]
        user = user_from_config(cfg_file, form.username.data)

        if user and form.password.data == user.password:
            next_ = request.values.get('next')
            login_user(user)
            return redirect(next_ or url_for('index.home'))

        flash("Invalid username or password.", "warning")
    return render_template('auth_login.html', form=form)


@auth_bp.route("/logout/")
def logout():
    logout_user()
    return redirect(url_for("index.home"))


@auth_bp.route("/oxd_login/")
def oxd_login():
    if current_user.is_authenticated:
        return redirect(url_for("index.home"))

    config = current_app.config["OXD_CLIENT_CONFIG_FILE"]
    oxc = Client(config)

    try:
        auth_url = oxc.get_authorization_url()
    except OxdServerError as exc:
        print exc  # TODO: use logging
        flash("Failed to process the request due to error in OXD server.", "warning")
    except socket.error as exc:
        print exc  # TODO: use logging
        flash("Unable to connect to OXD server.", "warning")
    else:
        return redirect(auth_url)
    return redirect(url_for("index.home"))


@auth_bp.route("/oxd_login_callback/")
def oxd_login_callback():
    """Callback for OXD authorization_callback.
    """
    config = current_app.config["OXD_CLIENT_CONFIG_FILE"]
    oxc = Client(config)
    code = request.args.get('code')
    state = request.args.get('state')

    try:
        # these following API calls may raise RuntimeError caused by internal
        # error in oxd server.
        tokens = oxc.get_tokens_by_code(code, state)
        resp = oxc.get_user_info(tokens["access_token"])

        # ``user_name`` item is in ``user_name`` scope, hence
        # accessing this attribute may raise KeyError
        username = resp["user_name"][0]

        role = resp["role"][0].strip("[]")
        if role != "cluster_manager":
            flash("Invalid user's role.", "warning")
        else:
            # all's good, let's log the user in.
            user = User(username, "")
            login_user(user)
    except KeyError as exc:
        print exc  # TODO: use logging
        flash("Either user_name or permission scope is not enabled in OpenID "
              "Connect configuration or user's info doesn't contain role attribute.",
              "warning")
    except OxdServerError as exc:
        print exc  # TODO: use logging
        flash("Failed to process the request due to error in OXD server.", "warning")
    except socket.error as exc:
        print exc  # TODO: use logging
        flash("Unable to connect to OXD server.", "warning")
    return redirect(url_for("index.home"))


@auth_bp.route("/oxd_logout_callback")
def oxd_logout_callback():
    """Callback for OXD client_frontchannel.
    """
    # TODO: decide whether we need this callback
    logout_user()
    return redirect(url_for("index.home"))


@auth_bp.route("/oxd_post_logout")
def oxd_post_logout():
    """Callback for OXD post_logout.
    """
    # TODO: decide whether we need this callback
    logout_user()
    return redirect(url_for("index.home"))
