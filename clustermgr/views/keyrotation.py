import os
from flask import Blueprint
from flask import render_template
from flask import redirect
from flask import request
from flask import url_for
from flask import current_app

from flask_login import login_required

from ..core.license import license_reminder
from ..core.license import prompt_license
from ..core.utils import as_boolean
from ..extensions import db
from ..forms import KeyRotationForm
from ..models import KeyRotation
from ..tasks.keyrotation import rotate_keys

keyrotation_bp = Blueprint("keyrotation", __name__)
keyrotation_bp.before_request(prompt_license)
keyrotation_bp.before_request(license_reminder)


@keyrotation_bp.route("/")
@login_required
def index():
    kr = KeyRotation.query.first()
    
    
    keygen_jar_path = os.path.join(current_app.config['DATA_DIR'], 
                                    'javalibs/keygen.jar')
    
    
    keygen_jar_exists = os.path.exists(keygen_jar_path)
    
    return render_template("keyrotation_index.html", 
                            kr=kr, 
                            keygen_jar_exists=keygen_jar_exists,
                            )


@keyrotation_bp.route("/settings/", methods=["GET", "POST"])
@login_required
def settings():
    kr = KeyRotation.query.first()
    form = KeyRotationForm()

    if request.method == "GET" and kr is not None:
        form.interval.data = kr.interval
        form.enabled.data = "true" if kr.enabled else "false"
        # form.type.data = kr.type

    if form.validate_on_submit():
        if not kr:
            kr = KeyRotation()

        kr.interval = form.interval.data
        kr.enabled = as_boolean(form.enabled.data)
        # kr.type = form.type.data
        kr.type = "jks"
        db.session.add(kr)
        db.session.commit()

        if kr.enabled:
            # rotate the keys immediately
            rotate_keys.delay()
        return redirect(url_for(".index"))

    # show the page
    return render_template("keyrotation_settings.html",
                           form=form, kr=kr)
