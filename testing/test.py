from change_gluu_host import Installer, FakeRemote, ChangeGluuHostname

name_changer = ChangeGluuHostname(
    old_host='c3.gluu.org',
    new_host='c2.gluu.org',
    cert_city='MyCity',
    cert_mail='admin@gluu.org',
    cert_state='NA',
    cert_country='US',
    server='c2.gluu.org',
    ldap_password='topsecret',
    os_type='CentOS',
    local=True,
    )
    
name_changer.startup()
name_changer.change_appliance_config()
name_changer.change_clients()
name_changer.change_uma()
name_changer.change_httpd_conf()
name_changer.create_new_certs()
name_changer.change_host_name()
