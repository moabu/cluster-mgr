
# Install CM on CentOS 8

```
yum install -y epel-release
yum repolist
yum remove python2-pyasn1 python2-pyasn1-modules
yum install gcc gcc-c++ libffi-devel make python2 python2-devel openssl-devel openldap-devel python2-pip java-1.8.0-openjdk-headless

pip2 install --upgrade setuptools==42.0.0
pip2 install --upgrade psutil==5.7.2
pip2 install https://github.com/GluuFederation/redislite/archive/master.zip
pip2 https://github.com/GluuFederation/cluster-mgr/archive/4.2.zip
```

# Instal CM on RedHat 7


If you don't have registered RHEL7 repo, write the following content to `/etc/yum.repos.d/centos7.repo`

```
[centos]
name=CentOS-7
baseurl=http://ftp.heanet.ie/pub/centos/7/os/x86_64/
enabled=1
gpgcheck=1
gpgkey=http://ftp.heanet.ie/pub/centos/7/os/x86_64/RPM-GPG-KEY-CentOS-7

```

`# rpm -i https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm`

`# yum repolist`

!!! Note
    If your Gluu Server nodes will be Red Hat 7, please enable epel release each node (by repeating above steps) before attempting to install Gluu Server via CM.

`# yum install gcc gcc-c++ libffi-devel make python-devel openssl-devel openldap-devel python-pip`

`# yum install -y java-1.8.0-openjdk-headless redis`

`# pip install python-ldap`

`# pip install clustermgr4` [ If from github then: `pip install https://github.com/GluuFederation/cluster-mgr/archive/4.0.zip` ] 

`# systemctl enable redis`

`# systemctl start redis`


# Install CM on CentOS 7

`# yum install -y epel-release`

`# yum repolist`

`# yum install gcc gcc-c++ libffi-devel make python-devel openssl-devel openldap-devel python-pip java-1.8.0-openjdk-headless`

`# yum install -y redis`

`# pip install python-ldap`

`# pip install clustermgr4`

`# systemctl enable redis`

`# systemctl start redis`
