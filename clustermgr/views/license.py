import os
from datetime import datetime

from flask import Blueprint
from flask import current_app
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from flask_login import login_required

from ..core.license import license_manager, prompt_license
from ..forms import LicenseSettingsForm
from ..forms import LicenseAckForm


license_bp = Blueprint("license", __name__)
license_bp.before_request(prompt_license)


def _humanize_timestamp(ts, date_fmt="%Y:%m:%d %H:%M:%S GMT"):
    """Formats Unix timestamp to use a user-friendly string.

    :param ts: Unix timestamp in milliseconds.
    :param date_fmt: Python's date time format string.
    :returns: String of formatted timestamp.
    """
    dt = datetime.utcfromtimestamp(ts / 1000)
    return dt.strftime(date_fmt)


@license_bp.route("/")
@login_required
def index():
    license_data, err = license_manager.validate_license()

    if "creation_date" in license_data["metadata"]:
        license_data["metadata"]["creation_date"] = _humanize_timestamp(
            license_data["metadata"]["creation_date"])

    if "expiration_date" in license_data["metadata"]:
        license_data["metadata"]["expiration_date"] = _humanize_timestamp(
            license_data["metadata"]["expiration_date"])

    if "products" in license_data["metadata"]:
        license_data["metadata"]["products"] = license_data["metadata"]["products"][0]

    return render_template("license_index.html", license_data=license_data,
                           err_msg=err)


@license_bp.route("/settings/", methods=["GET", "POST"])
@login_required
def settings():
    form = LicenseSettingsForm()
    cfg = license_manager.load_license_config()

    if request.method == "GET":
        # populate the form using existing settings
        form.license_id.data = cfg.get("license_id")
        form.license_password.data = cfg.get("license_password")
        form.public_password.data = cfg.get("public_password")
        form.public_key.data = cfg.get("public_key")

    if form.validate_on_submit():
        data = form.data
        data["accepted"] = cfg.get("accepted", "false")
        license_manager.dump_license_config(data)

        # removes old signed_license.txt (if any) as updating the settings
        # means we need to re-obtain and validate the license later
        try:
            os.unlink(current_app.config["LICENSE_SIGNED_FILE"])
        except OSError:
            # likely the file is not exist
            pass
        return redirect(url_for(".index"))
    return render_template("license_settings.html", form=form)


@license_bp.route("/prompt/", methods=["GET", "POST"])
def prompt():
    form = LicenseAckForm()

    if form.validate_on_submit():
        if form.accept.data is True:
            cfg = license_manager.load_license_config()
            cfg["accepted"] = "true"
            license_manager.dump_license_config(cfg)
            return redirect(url_for(".settings"))
        if form.decline.data is True:
            flash("License must be accepted in order to use the application.",
                  "warning")
    return render_template("license_prompt.html", form=form)
