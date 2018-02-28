import ConfigParser
import json
import os
import time
from datetime import datetime
from datetime import timedelta
from functools import wraps

import requests
from flask import _app_ctx_stack
from flask import flash
from flask import g as fg
from flask import redirect
from flask import url_for
from flask import current_app
from flask import request

from clustermgr.core.utils import exec_cmd
from clustermgr.core.utils import get_mac_addr


def current_date_millis():
    """Gets Unix timestamp in milliseconds.

    :returns: An integer of Unix timestamp in milliseconds.
    """
    # resp = requests.get(
    #     "https://license.gluu.org/oxLicense/rest/currentMilliseconds"
    # )
    # if resp.ok:
    #     return int(resp.json())
    return int(time.time() * 1000)


class LicenseManager(object):
    def __init__(self, app=None, redirect_endpoint=""):
        self.redirect_endpoint = redirect_endpoint
        self.app = app
        if app:
            self.init_app(app, redirect_endpoint)

    def init_app(self, app, redirect_endpoint):
        self.app = app
        self.redirect_endpoint = redirect_endpoint

        app.config.setdefault(
            "LICENSE_CONFIG_FILE",
            "/usr/share/oxlicense-validator/license.ini",
        )
        app.config.setdefault(
            "LICENSE_SIGNED_FILE",
            "/usr/share/oxlicense-validator/signed_license",
        )
        # Absolute path to external program which able to validate license.
        app.config.setdefault(
            "LICENSE_VALIDATOR",
            "/usr/share/oxlicense-validator/oxlicense-validator.jar",
        )
        # Default product name.
        app.config.setdefault(
            "LICENSE_PRODUCT_NAME",
            "cluster_manager",
        )
        app.config.setdefault(
            "LICENSE_ENFORCEMENT_ENABLED",
            True,
        )

        app.extensions = getattr(app, "extensions", {})
        app.extensions["license_manager"] = self

    def license_required(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            app = self._get_app()
            if app.config["LICENSE_ENFORCEMENT_ENABLED"]:
                license_data, err = self.validate_license()
                now = current_date_millis()

                invalid = license_data["valid"] is not True
                expired = now > license_data["metadata"].get("expiration_date")
                inactive = license_data["metadata"].get("active", False) is False

                if err or invalid or expired or inactive:
                    flash("The previously requested URL requires a valid license. "
                          "Please make sure you have a valid license.",
                          "warning")

                    # determine where to redirect when license is invalid
                    if not self.redirect_endpoint:
                        redirect_url = "/"
                    else:
                        redirect_url = url_for(self.redirect_endpoint)
                    return redirect(redirect_url)
            return func(*args, **kwargs)
        return wrapper

    def _get_app(self):
        if self.app:
            return self.app

        ctx = _app_ctx_stack.top
        if ctx:
            return ctx.app

        raise RuntimeError("application not registered on license_manager "
                           "instance and no application bound "
                           "to current context")

    def validate_license(self):
        """Validates the license.

        The process involves 3 steps:
        1. load the license settings to get the config needed for next steps
        2. get the signed license
        3. decode the signed license to extract its data

        :returns: A tuple of the data and error message from validation process.
        """
        license_data = {"valid": False, "metadata": {}}
        err = ""

        # step 1
        cfg = self.load_license_config()

        # step 2
        signed_license, err = self.get_signed_license(cfg.get("license_id"))
        if err:
            return license_data, err

        # step 3
        license_data, err = self.decode_signed_license(
            signed_license,
            cfg.get("public_key"),
            cfg.get("public_password"),
            cfg.get("license_password"),
        )
        if err:
            # error message returned from decode_signed_license is a long
            # java program errors, hence replace them with user-friendly
            # message
            err = "Unable to validate the license."
        return license_data, err

    def dump_license_config(self, data):
        """Writes a config file.

        Example of config file contents:

            [license]
            license_id = 1
            license_password = lpasswd
            public_password = ppasswd
            public_key = pkey
            accepted = true

        :param data: A ``dict`` of data to save to config file.
        """
        # section and options that needs to exist in config file
        section = "license"
        options = (
            "license_id",
            "license_password",
            "public_password",
            "public_key",
            "accepted",
        )

        parser = ConfigParser.SafeConfigParser()

        # set all required section and options
        parser.add_section(section)
        for opt, val in data.iteritems():
            if opt not in options:
                continue
            parser.set(section, opt, val)

        # write the options into a file
        app = self._get_app()
        with open(app.config["LICENSE_CONFIG_FILE"], "wb") as fw:
            parser.write(fw)

    def load_license_config(self):
        """Reads the config file and extract the data.

        :returns: A ``dict`` of configuration items.
        """
        app = self._get_app()
        parser = ConfigParser.SafeConfigParser()
        parser.read(app.config["LICENSE_CONFIG_FILE"])

        try:
            cfg = dict(parser.items("license"))
        except ConfigParser.NoSectionError:
            cfg = {}
        return cfg

    def get_signed_license(self, license_id):
        """Gets signed license either from file. If it can't get the signed
        license from a file, download it first.

        :param license_id: License ID.
        """
        err = ""
        sig = ""
        app = self._get_app()

        if not os.path.isfile(app.config["LICENSE_SIGNED_FILE"]):
            # download signed license if we don't have one yet
            resp = requests.post(
                "https://license.gluu.org/oxLicense/rest/generate",
                data={
                    "licenseId": license_id,
                    "count": 1,
                    "macAddress": get_mac_addr(),
                },
                verify=True,
            )
            if resp.ok:
                sig = resp.json()[0]["license"]
            else:
                err = resp.text

            # save it for later use
            with open(app.config["LICENSE_SIGNED_FILE"], "w") as fw:
                fw.write(sig)
            return sig, err

        with open(app.config["LICENSE_SIGNED_FILE"]) as fr:
            return fr.read(), err

    def decode_signed_license(self, signed_license, public_key,
                              public_password, license_password,):
        """Decodes signed license.

        Signed license is encoded using Java object serialization, hence
        we need external program to decode it.

        :param signed_license: Encoded signed license.
        :param public_key: Public key needed to validate the license.
        :param public_password: Public password needed to validate the license.
        :param license_password: License password needed to validate
                                 the license.
        :param product: Product name as defined in license.
        :returns: A tuple of ``dict`` contains license data and
                  error message (if any).
        """
        app = self._get_app()
        data = {"valid": False, "metadata": {}}

        # shell out and get the license data (if any)
        out, err, code = exec_cmd(
            "java -jar {} {} {} {} {} {} {}".format(
                app.config["LICENSE_VALIDATOR"],
                signed_license,
                public_key,
                public_password,
                license_password,
                app.config["LICENSE_PRODUCT_NAME"],
                current_date_millis(),
            )
        )

        if code != 0:
            return data, err

        # output example:
        #
        #   Validator expects: java org.xdi.oxd.license.validator.LicenseValidator
        #   {"valid":true,"metadata":{}}
        #
        # but we only care about the last line where the json data is defined
        meta = out.splitlines()[-1]

        data = json.loads(meta)
        return data, err

# create an instance so we can import it globally
license_manager = LicenseManager()


def license_reminder():
    """Sets human-readable expiration date.

    The value will be stored in ``flask.g`` object, so template can
    obtain the value.
    """
    # license enforcement disabled
    if not current_app.config["LICENSE_ENFORCEMENT_ENABLED"]:
        return

    msg = ""
    license_data, _ = license_manager.validate_license()

    # determine when license will be expired
    exp_date = license_data["metadata"].get("expiration_date")
    if exp_date:
        # expiration timestamp
        exp_date = datetime.utcfromtimestamp(int(exp_date) / 1000)
        exp_date_str = exp_date.strftime("%Y-%m-%d %H:%M:%S")

        # reminder should start 3 months before license expired
        exp_threshold = exp_date - timedelta(days=90)

        # current timestamp
        now = datetime.utcfromtimestamp(current_date_millis() / 1000)

        if now > exp_date:
            # license has been expired
            msg = "Your license has been expired since {} GMT.".format(exp_date_str)
        elif now > exp_threshold:
            # license will be expired soon
            msg = "Your license will be expired at {} GMT.".format(exp_date_str)

    # store in global so template can fetch the value
    fg.license_reminder_msg = msg


def prompt_license():
    # license enforcement disabled
    if not current_app.config["LICENSE_ENFORCEMENT_ENABLED"]:
        return

    # avoid redirect loop
    if request.endpoint == "license.prompt":
        return

    # if license already accepted
    cfg = license_manager.load_license_config()
    if cfg.get("accepted", "false").lower() == "true":
        return

    # prompt for license ack
    return redirect(url_for("license.prompt"))


def license_required():
    if not current_app.config["LICENSE_ENFORCEMENT_ENABLED"]:
        return

    license_data, err = license_manager.validate_license()
    now = current_date_millis()

    invalid = license_data["valid"] is not True
    expired = now > license_data["metadata"].get("expiration_date")
    inactive = license_data["metadata"].get("active", False) is False

    if any([err, invalid, expired, inactive]):
        flash("The previously requested URL ({}) requires a valid license. "
              "Please make sure you have a valid license.".format(request.url),
              "warning")
        return redirect(url_for("license.index"))
