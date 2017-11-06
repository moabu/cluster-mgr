import os

from flask import Blueprint
from flask import current_app
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from ..core.license import dump_license_config
from ..core.license import load_license_config
from ..core.license import validate_license
from ..forms import LicenseSettingsForm

license_bp = Blueprint("license", __name__)


@license_bp.route("/")
def index():
    license_data = {"valid": False, "metadata": {}}
    cfg_file = os.path.join(current_app.config["DATA_DIR"], "license.ini")
    sig_file = os.path.join(current_app.config["DATA_DIR"],
                            "signed_license.txt")

    license_data, err = validate_license(cfg_file, sig_file)

    if err:
        flash("Unable to validate the license. Please check the settings.",
              "warning")
    return render_template("license_index.html", license_data=license_data)


@license_bp.route("/settings/", methods=["GET", "POST"])
def settings():
    cfg_file = os.path.join(current_app.config["DATA_DIR"], "license.ini")
    sig_file = os.path.join(current_app.config["DATA_DIR"],
                            "signed_license.txt")

    form = LicenseSettingsForm()

    if request.method == "GET":
        # populate the form using existing settings
        cfg = load_license_config(cfg_file)
        form.license_id.data = cfg.get("license_id")
        form.license_password.data = cfg.get("license_password")
        form.public_password.data = cfg.get("public_password")
        form.public_key.data = cfg.get("public_key")

    if form.validate_on_submit():
        dump_license_config(cfg_file, form.data)

        # removes old signed_license.txt (if any) as updating the settings
        # means we need to re-obtain and validate the license later
        try:
            os.unlink(sig_file)
        except OSError:
            pass

        return redirect(url_for(".index"))
    return render_template("license_settings.html", form=form)
