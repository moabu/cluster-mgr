# Building Claster Manager Statically for RHEL8

In this guide we will explain how to create static Cluster Manager package that
can run on a machine that has no internet connection. For this you need a CentOS 8 machine
(or VM) that has internet access.

## On CentOS 8 Machine Having Internet

This machine (VM) is required for building Cluster Manager. After build, you won't
need anymore.


`yum install epel-release`

`yum repolist`

!!! Note
    If your Gluu Server nodes will be Red Hat 8, please enable epel release each node before attempting to install Gluu Server via CM.

`yum install gcc gcc-c++ libffi-devel make python3-devel openssl-devel python3-pip`

Update pip, setuptools and wheel

```
pip3 install --upgrade pip
pip3 install --upgrade setuptools
pip3 install --upgrade wheel
```

### Build Cluster Manager

First create directories

```
mkdir /tmp/bin
mkdir /opt/clustermgr
```

Execute the following commands to install Cluster Manager to `/opt/clustermgr` with all dependencies

```
pip3 install --upgrade --target=/opt/clustermgr https://github.com/GluuFederation/redislite/archive/master.zip
cp /opt/clustermgr/bin/* /tmp/bin
pip3 install --upgrade --target=/opt/clustermgr https://github.com/GluuFederation/cluster-mgr/archive/4.3.zip
cp /tmp/bin/* /opt/clustermgr/bin
```
You need to copy `/opt/clustermgr` directory to RHEL8 that has no internet access. So let us package:

`# tar -zcf clustermgr4.tgz /opt/clustermgr`

Now you can copy `clustermgr4.tgz` to RHEL8 that has no internet access.

### Upgrading Cluster Manager
If you built Cluster Manager before and there is an update, you can upgrade current static build as:

You need to create new `clustermgr4.tgz` and copy to RHEL8 that has no internet access.

## On RHEL8 Machine Has no Internet Access

Install python3

`yum install python3`

On this machine you need java-1.8 installed. Extract `clustermgr4.tgz` package:

`# tar -zxf clustermgr4.tgz -C /`

To start clustermanager use the following command:

```
/opt/clustermgr/bin/clustermgr4-cli start
```
You can stop as follows:

```
/opt/clustermgr/bin/clustermgr4-cli stop
```

Please follow [these instuctions](./offline_install.md) for offline installation
