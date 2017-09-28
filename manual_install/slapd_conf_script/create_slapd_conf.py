import ConfigParser, os
import hashlib
import os
cur_dir=os.path.dirname(os.path.abspath(__file__))

config = ConfigParser.ConfigParser()
config.readfp(open('syncrepl.cfg'))


syncrepl_temp = open(os.path.join(cur_dir, "ldap_templates", "syncrepl.temp")).read()

nginx_tmp = open(os.path.join(cur_dir, "ldap_templates", "nginx.temp")).read()


def makeLdapPassword(passwd):
    salt=os.urandom(4)
    sha=hashlib.sha1(passwd)
    sha.update(salt)    
    digest= (sha.digest()+ salt).encode('base64').strip()
    ssha_passwd = '{SSHA}'+ digest

    return ssha_passwd

ldp_servers = []

s_id = 1
for ldp in config.sections():

    if ldp.startswith('server_'):

        if config.get(ldp, 'enable').lower() in ('yes', 'true', 'on', '1'):

            ldp_servers.append( {
                'id': s_id,
                'fqn_hostname':    config.get(ldp, 'fqn_hostname'),
                'ldap_password': config.get(ldp, 'ldap_password'),
                   })
            s_id +=1

nginx = config.get('nginx', 'fqn_hostname')
nginx_backends = []

for ldp in ldp_servers:
    cur_ldp = ldp
    slapd_tmp=open(os.path.join(cur_dir, "ldap_templates", "slapd.conf")).read()
    repls=''
    rootpwd = makeLdapPassword(ldp['ldap_password'])


    slapd_tmp = slapd_tmp.replace('{#ROOTPW#}', rootpwd)
    slapd_tmp = slapd_tmp.replace('{#SERVER_ID#}', str(ldp['id']))

    nginx_backends.append('  server {0}:443;'.format(ldp['fqn_hostname']))

    for ldpc in ldp_servers:
        if ldpc == ldp:
            pass
        else:
            provider_id = str(ldpc['id']).zfill(3)
            repls_tmp = syncrepl_temp.replace('{#PROVIDER_ID#}', provider_id)
            repls_tmp = repls_tmp.replace('{#PROVIDER_PWD#}', ldpc['ldap_password'])
            repls_tmp = repls_tmp.replace('{#PROVIDER_ADDR#}', ldpc['fqn_hostname'])


            repls += repls_tmp

    slapd_tmp = slapd_tmp.replace('{#SYNCREPL#}', repls)

    conf_file_name = '{}.conf'.format(ldp['fqn_hostname'].replace('.','_'))

    with open(conf_file_name,'w') as f:
        f.write(slapd_tmp)
        print "Configuration file for", ldp['fqn_hostname'], "was created as", conf_file_name


nginx_tmp = nginx_tmp.replace('{#NGINX#}', nginx)
nginx_tmp = nginx_tmp.replace('{#SERVERS#}', '\n'.join(nginx_backends))

with open('nginx.conf','w') as f:
    f.write(nginx_tmp)
    print "Configuration file for nginx was created as nginx.conf"
