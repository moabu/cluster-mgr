```
rpm -i https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm
yum repolist
yum install -y wget curl
yum install gcc gcc-c++ make python3-devel openldap-devel python3-pip libffi-devel openssl-devel
yum install java-11-openjdk-headless


pip3 install --upgrade pip
pip3 install --upgrade setuptools
pip3 install --upgrade psutil
pip3 install --upgrade python3-ldap
pip3 install https://github.com/GluuFederation/redislite/archive/master.zip
pip3 install https://github.com/GluuFederation/cluster-mgr/archive/4.3.zip
```