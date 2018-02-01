Licensed under the [GLUU SUPPORT LICENSE](./LICENSE). Copyright Gluu 2018.

# Cluster Manager 2.0 Beta

#### GUI tool for installing and managing a highly available Gluu Server cluster.

Cluster Manager currently only supports installation on Ubuntu 14 and 16. It can, however, be used to configure Gluu Server clusters on Ubuntu and CentOS.

##### Gluu Cluster Manager should be installed on a secure administrators computer or a VM as it will have SSH access to all servers in the cluster.

After configuration, Cluster Manager no longer needs to be actively connected to the cluster for them to work properly. It can however be used to monitor your Gluu server health, make adjustments to your cluster configuration, and review Gluu Server logs as well as monitor server performance.

##### The necessary external ports that need to be opened in a default cluster installation are as follows:

<table>
  <tr><th> Gluu Servers </th><th> Load Balancer </th> <th> Cluster Manager </th></tr>
<tr><td>

|22| --| 443| 808* |
|--| -- | -- | -- |
|1636| 4444 | 8989 | 7777|

</td><td>

|22| 80 |
|--|--|
|443 | 8888 |

</td>

</td><td>

|22|
|--|
|1636|

</td></tr> 

</table>

22 will be used by Cluster Manager to pull logs and make adjustments to the systems. 80 and 443 are self explanatory. 1636, 4444 and 8989 are necessary for LDAP usage and replication. 7777 and 8888 are for securing communication between the Proxy server and the Gluu servers with stunnel.

## Installing Cluster Manager

1) First we must give Gluu Cluster Manager the ability to establish an ssh connection to the servers that are going to be added to the cluster. This includes the NGINX/Load-balancing server:

`ssh-keygen -t rsa`

- This will provide you with a prompt to create a key-pair. Make sure that you **do not input a password here**, so Cluster Manager can open connections to the servers.

- Now copy that key (default is `id_rsa.pub`) to the `/root/.ssh/authorized_keys` file of all servers in the cluster, including your NGINX server (if you're not going to use another load-balancing service).
- I prefer to open the `id_rsa.pub` file with `vi` then just copy the hash text into the bottom of `authorized_keys`

2) Install the necessary dependencies on the Gluu Cluster Manager machine:

```
sudo apt-get update
sudo apt-get install python-pip python-dev libffi-dev libssl-dev redis-server default-jre
(default-jre is for license requirements. Not necessary if Java already installed)
sudo pip install --upgrade setuptools influxdb
```

3) Install Cluster Manager

```
wget https://github.com/GluuFederation/cluster-mgr/archive/master.zip 
unzip master.zip 
cd cluster-mgr-master/
python setup.py instsall
```

- There may be a few innocuous warnings here, but this is normal.

4) Prepare Databases

```
clustermgr-cli db upgrade
```

6) Prepare oxlicense-validator

```
mkdir -p $HOME/.clustermgr/javalibs
wget http://ox.gluu.org/maven/org/xdi/oxlicense-validator/3.2.0-SNAPSHOT/oxlicense-validator-3.2.0-SNAPSHOT-jar-with-dependencies.jar -O $HOME/.clustermgr/javalibs/oxlicense-validator.jar
```

7) Run celery scheduler and workers in separate terminals

```
# Terminal 1
clustermgr-beat &

# Terminal 2
clustermgr-celery &
```

8) Open another terminal to run clustermgr-cli

```
clustermgr-cli run
```

9) On your first run of Gluu Cluster Manager, it will prompt you to create an administrator user name and password. This creates an authentication config file at `$HOME/.clustermgr/auth.ini`. The default authentication method can be disabled by removing the file.

Note, we recommend disabling [default authentication](https://github.com/GluuFederation/cluster-mgr/wiki/User-Authentication#using-default-admin-user) after [OXD authentication](https://github.com/GluuFederation/cluster-mgr/wiki/User-Authentication#using-oxd-and-gluu-server) has been setup properly.

10) Tunnel into cluster-mgr server

```
ssh -L 5000:localhost:5000 root@server
```

11) Navigate to the cluster-mgr web GUI on your local machine:

```
http://localhost:5000/
```

## Configuring a Cluster



# LOGGING


# Configuration

By default the installation of a cluster installs 5 services to manage high availabilty. These services are:

1) Gluu Server

2) Redis-Server

###### Installed outside the chroot on all servers.
###### A value key-store known for it's high performance.
###### Configuration file located at /etc/redis/redis.conf or /etc/redis.conf on the **Gluu** servers.

3) Stunnel

###### Used to protect communications between oxAuth and the caching services, Redis and Twemproxy.
###### Configuration file located at /etc/stunnel/stunnel.conf on **all** servers
###### Runs on port 8888 of your NGINX/Proxy server and 7777 on your Gluu servers.
###### For security Redis runs on localhost. Stunnel faciliates SSL communication over the internet for Redis which doesn't come default with encrypted traffic.

4) Twemproxy

###### Used for cache failover, round-robin proxying and caching performance with Redis.
###### The configuration file for this program can be found in /etc/nutcracker/nutcracker.yml on the proxy server.
###### Runs locally on port 2222 of your NGINX/Proxy server.
###### Because of demand for high availability, Twemproxy is a must as it automates detection of Redis server failure and redirects traffic to working instances.
###### Please note that Twemproxy will not reintroduce failed servers. You can manually or create a script that automates the task of restarting twemproxy, which will reset the "down" flag of that server.

5) NGINX

###### Used to proxy communication to the instances of Gluu
###### Configuration file located at /etc/nginx/nginx.conf on the load balancing server (if installed).
###### Can be set to round-robin instances of oxAuth for balancing load across servers by changing the nginx.conf to use `backend` instead of `backend_id`. Note this breaks SCIM functionality if one of the servers goes down and redundancy isn't built into the logic of your SCIM client.


