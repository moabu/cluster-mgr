# Cluster Manager

GUI tool for managing Gluu Server and OpenLDAP replication.

#### The Cluster-mgr should NOT be internet-facing and preferably installed on a secure adminstrators computer or a VM on Digital Ocean or Amazon you can turn off when you're not using it. After the inital set-up, cluster-mgr is not required to be connected to the servers anymore.

## Installing Cluster Manager

### OS Packages

Install prerequisites packages first. On debian or ubuntu, install them using `apt-get`:

1) First we must enable whatever computer/VM that cluster-mgr is installed on to establish an ssh connection to the servers that are going to be added to the cluster:

`ssh-keygen -t rsa`

- This will provide you with a prompt to create a key-pair. Make sure that you **do not input a password here**, so cluster-mgr can open connections to the servers.

- Now copy that key (default `id_rsa.pub`) to the `/root/.ssh/authorized_keys` file. I prefer to open the `id_rsa.pub` file with `vi` then just copy the hash text into the bottom of `authorized_keys`

2) Install necessary modules on the machine being used for cluster-mgr (Preferably not the Gluu servers or anything internet-facing)

```
apt-get install build-essential libssl-dev libffi-dev python-dev redis-server python-setuptools libsasl2-dev  libldap2-dev redis-server
```

3) Now clone the github repo on that same machine.

```
cd ~
git clone https://github.com/GluuFederation/cluster-mgr.git
```

4) Install cluster-mgr

```
cd cluster-mgr/
python setup.py install
```

- There may be a few errors here, but this is normal.

- A successful installation will install a tool called clustermgr-cli.

5) Prepare Databases

```
APP_MODE=dev clustermgr-cli db upgrade
APP_MODE=dev clustermgr-cli db migrate
```

6) Run celery worker on a new terminal

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

- If you're using a windows machine, like me, you can tunnel in with a PuTTY session that can already connect then go to `Connections` -> `SSH` -> `Tunnels`. In `Source port` input 9999 and in Destination input `localhost:5000`, then hit `Add`. This will create a tunnel from your machine, accessed through `localhost:9999` into to the server as `localhost:5000`.

9) Navigate to the cluster-mgr web GUI

```
http://localhost:9999/
```

