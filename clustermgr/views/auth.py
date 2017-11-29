import ConfigParser
import os

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


@auth_bp.route("/oxd/")
def oxd():
    if current_user.is_authenticated:
        return redirect(url_for("index.home"))

    config = os.path.join(current_app.config["DATA_DIR"], "oxd-client.ini")
    oxc = Client(config)

    oxd_id = oxc.config.get("oxd", "id")
    client_id = oxc.config.get("client", "client_id")
    client_secret = oxc.config.get("client", "client_secret")

    if not all([oxd_id, client_id, client_secret]):
        # TODO: bugs in oxdpython makes the client/site registered twice
        oxc.setup_client()

    response = oxc.get_client_token()
    auth_url = oxc.get_authorization_url(protection_access_token=response.access_token)
    return redirect(auth_url)


@auth_bp.route("/userinfo/")
def userinfo():
    config = os.path.join(current_app.config["DATA_DIR"], "oxd-client.ini")
    oxc = Client(config)
    response = oxc.get_client_token()
    code = request.args.get('code')
    state = request.args.get('state')

    try:
        # these following API calls may raise RuntimeError caused by internal
        # error in oxd server.
        tokens = oxc.get_tokens_by_code(code, state, response.access_token)
        resp = oxc.get_user_info(tokens.access_token, response.access_token)

        # ``preferred_username`` attribute is in ``profile`` scope, hence
        # accessing this attribute may raise AttributeError
        username = resp.preferred_username[0]

        # all's good, let's log the user in.
        user = User(username, "")
        login_user(user)
    except AttributeError:
        flash("Profile scope is not enabled in Gluu Server.", "warning")
    except RuntimeError:
        flash("Failed to get user info from Gluu Server.", "warning")
    return redirect(url_for("index.home"))
