import ConfigParser
import json
import os
import time
import uuid
from datetime import datetime
# from datetime import timedelta
from functools import wraps

import requests
from flask import _app_ctx_stack
from flask import flash
from flask import g as fg
from flask import redirect
from flask import url_for

from .keygen import exec_cmd

# Absolute path to external program which able to validate license.
DEFAULT_VALIDATOR = os.path.join(
    "/usr/share/oxlicense-validator/oxlicense-validator-3.1.1.jar"
)

# Default product name.
DEFAULT_PRODUCT_NAME = "de"  # TODO: change it to another name?


def get_mac_addr():
    """Gets MAC address according to standard IEEE EUI-48 format.

    :returns: A string of uppercased MAC address.
    """
    mac_num = hex(uuid.getnode()).replace("0x", "").upper()
    return "-".join(mac_num[i:i + 2] for i in range(0, 11, 2))


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
        self._cfg_file = None
        self._sig_file = None
        self.redirect_endpoint = redirect_endpoint

        self.app = app
        if app is not None:
            self.init_app(app, redirect_endpoint)

    def init_app(self, app, redirect_endpoint):
        self.app = app
        self.redirect_endpoint = redirect_endpoint
        app.extensions = getattr(app, "extensions", {})
        app.extensions["license_manager"] = self

    @property
    def cfg_file(self):
        if not self._cfg_file:
            app = self._get_app()
            self._cfg_file = os.path.join(app.config["DATA_DIR"],
                                          "license.ini")
        return self._cfg_file

    @property
    def sig_file(self):
        if not self._sig_file:
            app = self._get_app()
            self._sig_file = os.path.join(app.config["DATA_DIR"],
                                          "signed_license.txt")
        return self._sig_file

    def license_required(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            license_data, err = self.validate_license()

            if err or license_data.get("valid", False) is False:
                flash("The previously requested URL requires a valid license. "
                      "Please make sure you have a valid license by entering "
                      "the correct license settings.",
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

        :param cfg_file: Absolute path to config file.
        :param sig_file: Absolute path to file contains signed license.
        :returns: A tuple of the data and error message from validation process.
        """
        license_data = {"valid": False, "metadata": {}}
        err = ""

        # step 1
        cfg = self.load_license_config()

        # step 2
        signed_license, err = self.get_signed_license(cfg.get("license_id"))

        if not err:
            # step 3
            license_data, err = self.decode_signed_license(
                signed_license,
                cfg.get("public_key"),
                cfg.get("public_password"),
                cfg.get("license_password"),
            )
        return license_data, err

    def dump_license_config(self, data):
        """Writes a config file.

        Example of config file contents:

            [license]
            license_id = 1
            license_password = lpasswd
            public_password = ppasswd
            public_key = pkey

        :param data: A ``dict`` of data to save to config file.
        """
        # section and options that needs to exist in config file
        section = "license"
        options = (
            "license_id",
            "license_password",
            "public_password",
            "public_key",
        )

        parser = ConfigParser.SafeConfigParser()

        # set all required section and options
        parser.add_section(section)
        for opt, val in data.iteritems():
            if opt not in options:
                continue
            parser.set(section, opt, val)

        # write the options into a file
        with open(self.cfg_file, "wb") as fw:
            parser.write(fw)

    def load_license_config(self):
        """Reads the config file and extract the data.

        :returns: A ``dict`` of configuration items.
        """
        parser = ConfigParser.SafeConfigParser()
        parser.read(self.cfg_file)

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

        if not os.path.isfile(self.sig_file):
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
            with open(self.sig_file, "w") as fw:
                fw.write(sig)
            return sig, err

        with open(self.sig_file) as fr:
            return fr.read(), err

    def decode_signed_license(self, signed_license, public_key,
                              public_password, license_password,):
        """Decodes signed license.

        Signed license is encoded using Java object serialization, hence
        we need external program to decode it.

        :param signed_license: Encoded signed license.
        :param public_key: Public key needed to validate the license.
        :param public_password: Public password needed to validate the license.
        :param license_password: License password needed to validate the license.
        :param product: Product name as defined in license.
        """
        data = {"valid": False, "metadata": {}}

        # shell out and get the license data (if any)
        out, err, code = exec_cmd(
            "java -jar {} {} {} {} {} {} {}".format(
                DEFAULT_VALIDATOR,
                signed_license,
                public_key,
                public_password,
                license_password,
                DEFAULT_PRODUCT_NAME,
                current_date_millis(),
            )
        )

        if code != 0:
            err = "Unable to decode signed license. Please check the settings."
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
    expired_at = ""
    license_data, _ = license_manager.validate_license()

    # determine when license will be expired
    exp_date = license_data["metadata"].get("expiration_date")
    if exp_date:
        # expiration timestamp
        exp_date = datetime.utcfromtimestamp(int(exp_date) / 1000)
        # reminder should start a week before license expired
        # exp_threshold = exp_date - timedelta(days=7)
        # # current timestamp
        # now = datetime.utcnow()

        # if now >= exp_threshold:
        expired_at = exp_date.strftime("%Y-%m-%d %H:%M:%SZ")

    # store in global so template can fetch the value
    fg.license_expired_at = expired_at
