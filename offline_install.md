cysnc2 installation (CentOS 7):
-------------------------------
inside container:

download csync2 from https://raw.githubusercontent.com/mbaser/gluu/master/csync2-2.0-3.gluu.centos7.x86_64.rpmta
yum install sqlite-devel xinetd gnutls librsync
rpm -i csync2-2.0-3.gluu.centos7.x86_64.rpm 

cysnc2 installation (ubuntu & Debian):
--------------------------------------
inside container:

apt-get install csync2
