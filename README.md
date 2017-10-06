# Cluster Manager

GUI tool for managing Gluu Server OpenLDAP replication

**The Cluster-mgr should NOT be internet-facing and installed on a secure adminstrators computer.**

## Installing Cluster Manager

### OS Packages

Install prerequisites packages first. On debian or ubuntu, install them using `apt-get`:

1) Establish an ssh connection from your administrators computer to the Gluu servers for Cluster-mgr:

`ssh-keygen -t rsa`

- This will provide you with a prompt to create a key-pair. Make sure that you **do not input a password here**, so cluster-mgr can open connections to the servers.

- Now copy that key (default `id_rsa.pub`) to the `/root/.ssh/authorized_keys` file. I prefer to open the `id_rsa.pub` file with `vi` then just copy the hash text into the bottom of `authorized_keys`

2) Install necessary modules


```
apt-get install build-essential libssl-dev libffi-dev python-dev redis-server python-setuptools libsasl2-dev  libldap2-dev
```

3) Now clone the github repo

```
cd ~
git clone https://github.com/GluuFederation/cluster-mgr.git
```

4) Install cluster-mgr

```
cd cluster-mgr/
python setup.py install
```

- A successful installation will install a tool called clustermgr-cli.

5) Prepare Databases

```
APP_MODE=dev clustermgr-cli db upgrade
APP_MODE=dev clustermgr-cli db migrate
```

6) Run celery worker on a terminal

```
celery -A clusterapp.celery worker &
```

7) On another terminal run cluster-mgr

```
clustermgr-cli run
```

8) Tunnel into cluster-mgr server

```
ssh -L 9999:localhost:5000 root@server
```

9) Navigate to the cluster-mgr web GUI

```
http://localhost:9999/
```

