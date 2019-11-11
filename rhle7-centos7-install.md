# Instal CM on RedHat 7


If you don't have registered RHEL7 repo, write the following content to `/etc/yum.repos.d/centos7.repo`

`# rpm -i https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm`

`# yum repolist`

`# yum install -y java redis python-ldap python-ldap3`

`# pip install clustermgr4` [ If from github then: `pip install https://github.com/GluuFederation/cluster-mgr/archive/4.0.zip` ] 

`# systemctl enable redis`

`# systemctl start redis`


# Install CM on CentOS 7

`# yum install -y epel-release`

`# yum repolist`

`# yum install gcc gcc-c++ make python-devel  openldap-devel python-pip`

`# yum install -y redis`

`# pip install python-ldap`

`# pip install clustermgr`

`# systemctl enable redis`

`# systemctl start redis`
