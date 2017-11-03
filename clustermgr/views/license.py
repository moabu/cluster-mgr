import ConfigParser
import json
import os.path
import time
import uuid

import requests
from flask import Blueprint
from flask import current_app
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from ..core.keygen import exec_cmd
from ..forms import LicenseSettingsForm

DEFAULT_VALIDATOR = os.path.join(
    "/usr/share/oxlicense-validator/oxlicense-validator-3.1.1.jar"
)

license_bp = Blueprint("license", __name__)


def get_mac_addr():
    """Gets MAC address according to standard IEEE EUI-48 format.
    """
    mac_num = hex(uuid.getnode()).replace("0x", "").upper()
    return "-".join(mac_num[i:i + 2] for i in range(0, 11, 2))


def _download_signed_license(license_id):
    mac_addr = get_mac_addr()
    resp = requests.post(
        "https://license.gluu.org/oxLicense/rest/generate",
        data={
            "licenseId": license_id,
            "count": 1,
            "macAddress": mac_addr,
        },
        verify=True,
    )
    if resp.ok:
        return resp.json()[0]["license"]
    return ""


def get_signed_license(license_id, sig_file=""):
    sig_file = sig_file or os.path.join(current_app.config["DATA_DIR"], "signed_license.txt")

    if not os.path.isfile(sig_file):
        # get signed license if we don't have one yet
        sig = _download_signed_license(license_id)

        # save it for later use
        with open(sig_file, "w") as fw:
            fw.write(sig)
        return sig

    with open(sig_file) as fr:
        return fr.read()


def decode_signed_license(signed_license, public_key, public_password,
                          license_password, product, current_date):
    validator = DEFAULT_VALIDATOR

    # shell out and get the license data (if any)
    out, err, code = exec_cmd(
        "java -jar {} {} {} {} {} {} {}".format(
            validator,
            signed_license,
            public_key,
            public_password,
            license_password,
            product,
            current_date,
        )
    )

    if code != 0:
        return {}, "Unable to decode signed license. Please check " \
                   "downloaded signed license and/or license.ini file."

    # output example:
    #
    #   Validator expects: java org.xdi.oxd.license.validator.LicenseValidator
    #   {"valid":true,"metadata":{}}
    #
    # but we only care about the last line
    meta = out.splitlines()[-1]

    data = json.loads(meta)
    return data, err


def load_license_config(config_path):
    parser = ConfigParser.SafeConfigParser()
    parser.read(config_path)

    try:
        cfg = dict(parser.items("license"))
    except ConfigParser.NoSectionError:
        cfg = {}
    return cfg


def current_date_millis():
    # TODO: fetch it from license server?
    # resp = requests.get(
    #     "https://license.gluu.org/oxLicense/rest/currentMilliseconds"
    # )
    # if resp.ok:
    #     return resp.json()
    return int(time.time() * 1000)


def dump_license_config(path, data=None):
    data = data or {}
    section = "license"
    options = (
        "license_id",
        "license_password",
        "public_password",
        "public_key",
    )

    parser = ConfigParser.SafeConfigParser()
    parser.add_section(section)

    for opt, val in data.iteritems():
        if opt not in options:
            continue
        parser.set(section, opt, val)

    # parser.set(section, "license_id", data.get("license_id", ""))
    # parser.set(section, "license_password", data.get("license_password", ""))
    # parser.set("license", "public_password", data.get("public_password", ""))
    # parser.set("license", "public_key", data.get("public_key", ""))

    with open(path, "wb") as fw:
        parser.write(fw)


@license_bp.route("/")
def index():
    license_data = {}
    cfg = load_license_config(os.path.join(current_app.config["DATA_DIR"], "license.ini"))

    signed_license = get_signed_license(cfg.get("license_id"))
    license_data, err = decode_signed_license(
        signed_license,
        cfg.get("public_key"),
        cfg.get("public_password"),
        cfg.get("license_password"),
        "de",  # TODO: new product name for cluster manager?
        current_date_millis(),
    )

    valid = license_data.get("valid", False)
    metadata = license_data.get("metadata", {})

    return render_template("license_index.html", valid=valid,
                           metadata=metadata, err=err)


@license_bp.route("/settings/", methods=["GET", "POST"])
def settings():
    cfg_file = os.path.join(current_app.config["DATA_DIR"], "license.ini")
    form = LicenseSettingsForm()

    if request.method == "GET":
        cfg = load_license_config(cfg_file)
        form.license_id.data = cfg.get("license_id")
        form.license_password.data = cfg.get("license_password")
        form.public_password.data = cfg.get("public_password")
        form.public_key.data = cfg.get("public_key")

    if form.validate_on_submit():
        dump_license_config(cfg_file, form.data)
        return redirect(url_for(".index"))
    return render_template("license_settings.html", form=form)
