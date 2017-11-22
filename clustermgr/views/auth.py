import ConfigParser

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
    cfg_file = current_app.config["AUTH_CONFIG_FILE"]
    user = user_from_config(cfg_file, username)
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
