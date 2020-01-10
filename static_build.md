# Building Claster Manager Statically on RHEL7

In this guid we will explain how to create static Cluster Manager package that
can run on a machine that has no internet connection. For this you need a REHEL machine
(or VM) that has internet access.

## On RHEL7 Machine Having Internet

This machine (VM) is required for building Cluster Manager. After build, you won't
need anymore.

### Preliminary
We need a couple of software to build Cluster Manager. If you don't have registered RHEL7 repo, write the following content to `/etc/yum.repos.d/centos7.repo`

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


### Build Cluster Manager

Execute the following commands to install Cluster Manager to `/opt/clustermgr` with all dependencies

`# pip install python-ldap==2.4.15 --install-option="--install-scripts=/opt/clustermgr/bin" --target=/opt/clustermgr/clustermgr`

`# pip install  https://github.com/GluuFederation/cluster-mgr/archive/4.0.zip --install-option="--install-scripts=/opt/clustermgr/bin" --target=/opt/clustermgr/clustermgr` 

You need to copy `/opt/clustermgr` directory to RHEL7 that has no internet access. So let us package:

`# tar -zcf clustermgr4.tgz /opt/clustermgr`

Now you can copy `clustermgr4.tgz` to RHEL7 that has no internet access.

## On RHEL7 Machine Has no Internet Access

On this machine you need to java-1.8 and redis installed. Extract `clustermgr4.tgz` package:

`# tar -zxf clustermgr4.tgz -C /`

Enable and start redis

`# systemctl enable redis`

`# systemctl start redis`

To start clustermanager use the following command:

`# PYTHONPATH=/opt/clustermgr/clustermgr:/opt/clustermgr/bin PATH=$PATH:/opt/clustermgr/bin /opt/clustermgr/bin/clustermgr4-cli start`

You can stop as follows:

`# PYTHONPATH=/opt/clustermgr/clustermgr:/opt/clustermgr/bin PATH=$PATH:/opt/clustermgr/bin /opt/clustermgr/bin/clustermgr4-cli stop`

