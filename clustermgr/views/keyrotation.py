import os

from flask import Blueprint
from flask import render_template
from flask import redirect
from flask import request
from flask import url_for
from flask import flash
from flask_login import login_required
from flask_menu import register_menu

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.utils import as_boolean
from ..extensions import db
from ..forms import KeyRotationForm
from ..models import ConfigParam
from ..tasks.keyrotation import rotate_keys
from clustermgr.extensions import celery


keyrotation_bp = Blueprint("keyrotation", __name__)
keyrotation_bp.before_request(prompt_license)
keyrotation_bp.before_request(license_reminder)

def isKEyRatationMenuVisible():
    keygen_file = os.path.join(celery.conf["JAVALIBS_DIR"], 'keygen.jar')
    
    return os.path.isfile(keygen_file)

@keyrotation_bp.route("/")
@register_menu(keyrotation_bp, '.gluuServerCluster.keyRotation', 'Key Rotation', order=7, icon='fa fa-key', visible_when=isKEyRatationMenuVisible)
@login_required
def index():
    kr = ConfigParam.get('keyrotation')
    if not kr:
        kr = ConfigParam.new(
                    'keyrotation', 
                    data={
                        'interval': 24,
                        'enabled': False,
                        'rotated_at': 0,
                        }
                    )
        kr.save()

    return render_template("keyrotation_index.html", kr=kr)


@keyrotation_bp.route("/settings/", methods=["GET", "POST"])
@login_required
def settings():
    kr = ConfigParam.get('keyrotation')
    form = KeyRotationForm()

    if request.method == "GET" and kr is not None:
        form.interval.data = kr.data.interval
        form.enabled.data = "true" if kr.data.enabled else "false"
        # form.type.data = kr.type

    if form.validate_on_submit():
        kr.data.interval = form.interval.data
        kr.data.enabled = as_boolean(form.enabled.data)
        # kr.type = form.type.data
        kr.data.type = "jks"
        kr.save()

        if kr.data.enabled:
            # rotate the keys immediately
            rotate_keys.delay()
        return redirect(url_for(".index"))

    # show the page
    return render_template("keyrotation_settings.html",
                           form=form, kr=kr)
