import os
from datetime import datetime

from flask import Blueprint
from flask import current_app
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from ..core.license import license_manager
from ..forms import LicenseSettingsForm

license_bp = Blueprint("license", __name__)


def _humanize_timestamp(ts):
    dt = datetime.utcfromtimestamp(ts / 1000)
    return dt.strftime("%Y:%m:%d %H:%M:%S GMT")


@license_bp.route("/")
def index():
    license_data, err = license_manager.validate_license()

    ts_keys = ["creation_date", "expiration_date"]
    for key in ts_keys:
        if key in license_data["metadata"]:
            license_data["metadata"][key] = _humanize_timestamp(
                license_data["metadata"][key])

    if err:
        flash(err, "warning")
    return render_template("license_index.html", license_data=license_data)


@license_bp.route("/settings/", methods=["GET", "POST"])
def settings():
    form = LicenseSettingsForm()

    if request.method == "GET":
        # populate the form using existing settings
        cfg = license_manager.load_license_config()
        form.license_id.data = cfg.get("license_id")
        form.license_password.data = cfg.get("license_password")
        form.public_password.data = cfg.get("public_password")
        form.public_key.data = cfg.get("public_key")

    if form.validate_on_submit():
        license_manager.dump_license_config(form.data)

        # removes old signed_license.txt (if any) as updating the settings
        # means we need to re-obtain and validate the license later
        try:
            os.unlink(current_app.config["LICENSE_SIGNED_FILE"])
        except OSError:
            # likely the file is not exist
            pass
        return redirect(url_for(".index"))
    return render_template("license_settings.html", form=form)
