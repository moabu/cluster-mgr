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
from flask_login import login_required

from ..extensions import login_manager
from ..forms import LoginForm


auth_bp = Blueprint("auth", __name__)
login_manager.login_view = "auth.login"


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
    cfg_file = os.path.join(current_app.config["DATA_DIR"], "auth.ini")
    user = user_from_config(cfg_file, username)
    return user


@auth_bp.route("/protected/")
@login_required
def protected():
    return 'Logged in as: ' + current_user.username


@auth_bp.route("/login/", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        # Login and validate the user.
        # user should be an instance of your `User` class
        cfg_file = os.path.join(current_app.config["DATA_DIR"], "auth.ini")
        user = user_from_config(cfg_file, form.username.data)

        if user and form.password.data == user.password:
            login_user(user)
            next_ = request.args.get('next')
            return redirect(next_ or url_for('index.home'))

        flash("invalid username or password", "warning")
    return render_template('auth_login.html', form=form)


@auth_bp.route("/logout/")
def logout():
    logout_user()
    return redirect(url_for("index.home"))
