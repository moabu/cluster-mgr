import os
import json

from flask import Blueprint
from flask import render_template
from flask import redirect
from flask import request
from flask import url_for
from flask import flash
from flask_login import login_required

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.utils import as_boolean
from ..extensions import db
from ..forms import KeyRotationForm
from ..models import KeyRotation
from ..tasks.keyrotation import rotate_keys
from clustermgr.extensions import celery


keyrotation_bp = Blueprint("keyrotation", __name__)
keyrotation_bp.before_request(prompt_license)
keyrotation_bp.before_request(license_reminder)


@keyrotation_bp.route("/")
@login_required
def index():
    keygen_file = os.path.join(celery.conf["JAVALIBS_DIR"], 'keygen.jar')
    
    if not os.path.exists(keygen_file):
        flash("Key generator {} was not found. Key rotation will not work unless the instructions are followed {}".format(
               keygen_file, 'https://gluu.org/docs/cm/installation/#add-key-generator'), 'danger')
        
        return redirect(url_for('index.home'))
    kr = KeyRotation.query.first()
    return render_template("keyrotation_index.html", kr=kr)


@keyrotation_bp.route("/settings/", methods=["GET", "POST"])
@login_required
def settings():
    kr = KeyRotation.query.first()
    if not kr:
        kr = KeyRotation()
        db.session.add(kr)
        db.session.commit()

    kr.jdata = {'backup': True}
    
    if kr.inum_appliance:
        try:
            kr.jdata = json.loads(kr.inum_appliance)
        except:
            pass

    form = KeyRotationForm()

    if request.method == "GET":
        form.interval.data = kr.interval
        form.enabled.data = "true" if kr.enabled else "false"
        form.backup.data = kr.jdata.get('backup')
        # form.type.data = kr.type

    if form.validate_on_submit():

        kr.interval = form.interval.data
        kr.enabled = as_boolean(form.enabled.data)
        kr.jdata['backup'] = as_boolean(form.backup.data)
        kr.inum_appliance = json.dumps(kr.jdata)
        # kr.type = form.type.data
        kr.type = "jks"
        
        db.session.commit()
        
        if kr.enabled:
            # rotate the keys immediately
            rotate_keys.delay()
        return redirect(url_for(".index"))

    # show the page
    return render_template("keyrotation_settings.html",
                           form=form, kr=kr)
