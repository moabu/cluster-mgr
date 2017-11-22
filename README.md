# Cluster Manager

GUI tool for managing Gluu Server and OpenLDAP replication.

Currently only supports installation on Ubuntu 14 and 16. It can, however, configure cluster replication on Debian and CentOS.

#### The Gluu Cluster Manager should preferably be installed on a secure adminstrators computer or a VM as it will have SSH access to all the servers in the cluster.

- After configuration, the Gluu Cluster Manager no longer needs to be actively connected to the cluster for them to work properly. It can however be used to monitor and manage your cluster for modifications at any time.

## Installing Cluster Manager

1) First we must enable the machine that Gluu Cluster Manager is installed on the ability to establish an ssh connection to the servers that are going to be added to the cluster. This includes the NGINX/Load-balancing server:

`ssh-keygen -t rsa`

- This will provide you with a prompt to create a key-pair. Make sure that you **do not input a password here**, so cluster-mgr can open connections to the servers.

- Now copy that key (default is `id_rsa.pub`) to the `/root/.ssh/authorized_keys` file of all servers in the cluster, including your NGINX server (if you're not going to use another load-balancing service). 
- I prefer to open the `id_rsa.pub` file with `vi` then just copy the hash text into the bottom of `authorized_keys`

2) Install the necessary dependencies on the Gluu Cluster Manager machine:

```
apt-get update
apt-get install python-pip python-dev libffi-dev libssl-dev redis-server
pip install --upgrade setuptools
```

3) Install cluster-mgr

```
pip install --pre clustermgr
```

- There may be a few innocuous warnings here, but this is normal.

4) Prepare Databases

```
clustermgr-cli db upgrade
```

5) Run celery worker on one terminal

```
clustermgr-celery &
```

6) Open another terminal to run clustermgr-cli

```
clustermgr-cli run
```

7) Tunnel into cluster-mgr server

```
ssh -L 9999:localhost:5000 root@server
```

- If you're using a windows machine, like me, you can tunnel in with a saved PuTTY session that can already connect. Load that configuration in `PuTTY Configuration`, then on the left side go to `Connections` -> `SSH` -> `Tunnels`. In `Source port` input `9999` and in Destination input `localhost:5000`, then hit `Add`. This will create a tunnel from your machine, accessed through `localhost:9999`, into the server as `localhost:5000`.

8) Navigate to the cluster-mgr web GUI

```
http://localhost:9999/
```

