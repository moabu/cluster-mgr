import os, sys
from change_gluu_host import Installer, FakeRemote, ChangeGluuHostname

name_changer = ChangeGluuHostname(
    old_host='c2.gluu.org',
    new_host='c3.gluu.org',
    cert_city='MyCity',
    cert_mail='admin@gluu.org',
    cert_state='NA',
    cert_country='US',
    server='c3.gluu.org',
    ldap_password="secret",
    os_type='Ubuntu',
    local=True,
    )

r = name_changer.startup()
if not r:
    sys.exit(1)

name_changer.change_appliance_config()
name_changer.change_clients()
name_changer.change_uma()
name_changer.change_httpd_conf()
name_changer.create_new_certs()
name_changer.change_host_name()
