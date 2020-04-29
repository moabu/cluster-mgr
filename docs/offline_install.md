Offline Installations
----------------------
!!! Note
    If your Cluster Manager VM has no internet access, please follow [these instructons for static build](/static_build.md)

To enable offline installation, you need to put gluu-server package under `~/.clustermgr/gluu_repo`, you can download packages from https://repo.gluu.org/

In all the following instructions, it is assumed that you configured your
system that can install distribution packages from CD/DVD.

On each node:
```
apt-get install python-ldap3
pip install python-psutil
pip install pyDes

```

and install the following pacakges (on host system):
 * curl
 * python2
 * ntpdate
 * stunnel

# csync2 Installation

## cysnc2 installation (CentOS 7):


Obtain csync2 from http://162.243.99.240/icrby8xcvbcv/csync2/csync2-2.0-3.gluu.centos7.x86_64.rpm

inside container:

```
# yum install sqlite-devel xinetd gnutls librsync
# rpm -i csync2-2.0-3.gluu.centos7.x86_64.rpm
```
## cysnc2 installation (RedHat 7):

Obtain csync2 from http://162.243.99.240/icrby8xcvbcv/csync2/csync2-2.0-3.gluu.rhel7.src.rpm

inside container:

```
# yum install sqlite-devel xinetd gnutls librsync
# rpm -i csync2-2.0-3.gluu.rhel7.src.rpm
```


## cysnc2 installation (ubuntu & Debian):

inside container:

```
# apt-get install csync2
```

# Monitoring


Install Influxdb on local (Cluster Manager) machine :

Obtain influxdb from https://repos.influxdata.com/ubuntu/pool/stable/i/influxdb/influxdb_1.7.4-1_amd64.deb

```
# dpkg -i influxdb_1.7.4-1_amd64.deb
```

## CentOS 7 & RedHat 7
Download http://162.243.99.240/icrby8xcvbcv/psutil/python2-psutil-5.7.0-1.el7.x86_64.rpm
and install all nodes:
  
```
rpm -i ython2-psutil-5.7.0-1.el7.x86_64.rpm
```

# Logging

## ubuntu & Debian:
Obtain filebeat from https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-6.6.2-amd64.deb
and install all nodes:
  
```
dpkg -i filebeat-6.6.2-amd64.deb
```

## CentOS 7 & RedHat 7
Obtain filebeat from https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-6.6.2-x86_64.rpm
and install all nodes:
  
```
rpm -i filebeat-6.6.2-x86_64.rpm
```

If you did not installed ifluxd please install as explianed in Monitoring Section.

