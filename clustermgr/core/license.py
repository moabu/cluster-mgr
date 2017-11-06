import ConfigParser
import json
import os
import time
import uuid

import requests

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


def get_signed_license(license_id, sig_file):
    """Gets signed license either from file. If it can't get the signed license
    from a file, download it first.

    :param license_id: License ID.
    :sig_file: Absolute path to file contains signed license.
    """
    sig_file = sig_file

    if not os.path.isfile(sig_file):
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
            sig = ""

        # save it for later use
        with open(sig_file, "w") as fw:
            fw.write(sig)
        return sig

    with open(sig_file) as fr:
        return fr.read()


def decode_signed_license(signed_license, public_key,
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


def load_license_config(cfg_file):
    """Reads the config file and extract the data.

    :param cfg_file: Absolute path to config file.
    :returns: A ``dict`` of configuration items.
    """
    parser = ConfigParser.SafeConfigParser()
    parser.read(cfg_file)

    try:
        cfg = dict(parser.items("license"))
    except ConfigParser.NoSectionError:
        cfg = {}
    return cfg


def current_date_millis():
    """Gets Unix timestamp in milliseconds.

    :returns: An integer of Unix timestamp in milliseconds.
    """
    # TODO: fetch it from license server?
    # resp = requests.get(
    #     "https://license.gluu.org/oxLicense/rest/currentMilliseconds"
    # )
    # if resp.ok:
    #     return resp.json()
    return int(time.time() * 1000)


def dump_license_config(cfg_file, data=None):
    """Writes a config file.

    Example of config file contents:

        [license]
        license_id = 1
        license_password = lpasswd
        public_password = ppasswd
        public_key = pkey

    :param cfg_file: Absolute path to config file.
    :param data: A ``dict`` of data to save to config file.
    """
    data = data or {}

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
    with open(cfg_file, "wb") as fw:
        parser.write(fw)


def validate_license(cfg_file, sig_file):
    """Validates the license.

    The process involves 3 steps:
    1. load the license settings to get the config needed for next steps
    2. get the signed license
    3. decode the signed license to extract its data

    :param cfg_file: Absolute path to config file.
    :param sif_file: Absolute path to file contains downloaded signed license.
    :returns: A tuple of the data and error message from validation process.
    """
    # step 1
    cfg = load_license_config(cfg_file)

    # step 2
    signed_license = get_signed_license(cfg.get("license_id"), sig_file)

    # step 3
    license_data, err = decode_signed_license(
        signed_license,
        cfg.get("public_key"),
        cfg.get("public_password"),
        cfg.get("license_password"),
    )
    return license_data, err
