from datetime import datetime
from datetime import timedelta

from clustermgr.extensions import mailer, celery
from clustermgr.core.license import license_manager
from clustermgr.core.license import current_date_millis
from flask_mail import Message


EMAIL_BODY = """
Hi {admin_name},

Your Gluu enterprise license is set to expire in {day} days.

If you have already renewed your Gluu support contract, you can ignore this message.

Otherwise please email sales@gluu.org to initiate your organization's support renewal.

Thank you!

Gluu, Inc."""


@celery.task(bind=True)
def send_reminder_email(self):
    data, _ = license_manager.validate_license()

    # license is not exist or invalid
    if "expiration_date" not in data["metadata"]:
        return

    # get expiration_date of license
    exp_date = datetime.utcfromtimestamp(
        data["metadata"]["expiration_date"] / 1000)

    # get current timestamp
    now = datetime.utcfromtimestamp(current_date_millis() / 1000)

    try:
        with open(celery.conf["LICENSE_EMAIL_THRESHOLD_FILE"], "r") as fp:
            last_sent = fp.read()
    except IOError:
        last_sent = ""

    # threshold when email should be send to admin
    # 0, 30, 60, 90 days before license expired
    for day in [0, 30, 60, 90]:
        t = exp_date - timedelta(days=day)

        # if current day+month+year doesn't match the threshold, continue
        if not all([now.day == t.day, now.month == t.month, now.year == t.year]):
            continue

        # if email has been previously sent in the same day, skip the process
        if last_sent == t.strftime("%Y-%m-%d"):
            return

        msg = Message(
            "License expiration reminder",
            recipients=celery.conf["MAIL_DEFAULT_RECIPIENT_ADDRESS"],
        )
        msg.body = EMAIL_BODY.format(
            admin_name=celery.conf["MAIL_DEFAULT_RECIPIENT_USERNAME"],
            day=day,
        )
        mailer.send(msg)

        # mark last sent email
        with open(celery.conf["LICENSE_EMAIL_THRESHOLD_FILE"], "wb") as fp:
            fp.write(t.strftime("%Y-%m-%d"))
        break
