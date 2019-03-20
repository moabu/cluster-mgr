In all the following instructions, it is assumed that you configured your
system that can install distribution packages from CD/DVD.

On each node:
```
apt-get install python-ldap3
pip install python-psutil
pip install pyDes

```


# csync2 Installation

##cysnc2 installation (CentOS 7):


Obtain csync2 from https://raw.githubusercontent.com/mbaser/gluu/master/csync2-2.0-3.gluu.centos7.x86_64.rpm

inside container:

```
# yum install sqlite-devel xinetd gnutls librsync
# rpm -i csync2-2.0-3.gluu.centos7.x86_64.rpm 
```

## cysnc2 installation (ubuntu & Debian):

inside container:

```
# apt-get install csync2
```

# Monitoring

## Local Machine (Cluster Manager) Machine

1. Install Influxdb:

Obtain influxdb from https://repos.influxdata.com/ubuntu/pool/stable/i/influxdb/influxdb_1.7.4-1_amd64.deb

```
# dpkg -i influxdb_1.7.4-1_amd64.deb
# apt-get install python-influxdb
# apt-get install python-psutil
```

2.
