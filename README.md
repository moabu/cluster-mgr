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
**This HAS to be the root authorized_keys or Cluster Manager will not work**

2) Install the necessary dependencies on the Gluu Cluster Manager machine:

```
sudo apt-get update
sudo apt-get install python-pip python-dev libffi-dev libssl-dev redis-server default-jre
(default-jre is for license requirements. Not necessary if Java already installed)
sudo pip install --upgrade setuptools influxdb
```

3) Install Cluster Manager

```
wget https://github.com/GluuFederation/cluster-mgr/archive/2.0-stable.zip 
unzip 2.0-stable.zip 
cd cluster-mgr-2.0-stable/
sudo python setup.py install
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

10) It is recommended to create a "cluster" user, other than the one you used to install and configure cluster manager. This is a basic security concern, due to the fact that the user ssh'ing into this server would have unfettered access to every server connected to cluster manager. By using a separate user, which will still be able to connect to localhost:5000, you can inhibit potential malicious activity. 

```
ssh -L 5000:localhost:5000 cluster@<server>
```

11) Navigate to the cluster-mgr web GUI on your local machine:

```
http://localhost:5000/
```

# Deploying a Cluster

1) Here is the first screen you'll see on the initial launch where you create the default administrator and password:

`Admin creation screen here`

2) Next you'll be taken to the splash page where you can initiate building a cluster with the `Setup Cluster` button:

`Setup Cluster screen here`

3) Here is you `Settings` screen. You can access this screen again by clicking the `Settings` button on the left menu bar.

`Application Settings Screen`

###### Replication Manager Password will be used in OpenDJ for replication purposes
###### Load Balancer: This will be the hostname of either your NGINX proxy server, or the Load balancing server you'll be using for your cluster. Note, this cannot be changed after you deploy your Gluu servers, so please keep this in mind. To change the hostname, you'll have to redeploy Gluu Severs from scratch.
###### `Add IP Addresses and hostnames to /etc/hosts file on each server`: Use this option if you're using servers without Fully Qualified Domain Names. This will automatically assign hostnames to ip addresses in the `/etc/hosts` files inside and outside the Gluu chroot. Otherwise, you may run into complications with server connectivity unless you manually configure these correctly.

4) Once these are properly configured, click the `Update Configuration button`.

`Gluu Cluster Manager Add Server Prompt`

5) Click `Add Server`

`New Server - Primary Server`

6) You will be taken to the `Add Primary Server` screen. It is called Primary as it will be the base for which the other nodes will pull their Gluu configuration and certificates. After Deployment, all servers will function in a Master-Master configuration.

###### Hostname will be the actual hostname of the server, not the hostname of the NGINX/Proxy server. If you selected the `Add IP Addresses and Hostnames to/etc/hosts file on each server` in the `Settings` menu, then this will be the hostname embedded automatically in the `/etc/hosts` files on this computer.

`Dashboard`

7) After you click `Submit`, you will be taken to the Dashboard.

###### Here you can see all the servers in your cluster, add more servers, edit the hostname and IP address of a server if you entered them incorrectly and also Install Gluu automatically.

8) Click the `Add Server` button and add another node or 2. Note, the admin password set in the Primary server is the same for all the servers.

9) Once you've added all the servers you want in your cluster, back at the dashboard we will click `Install Gluu` on our primary server.

`Install Gluu Server`

###### This screen is the equivalent of the standard `setup.py` installation in Gluu. The first 5 options are necessary for certificate creation.
###### Next are inum configurations for Gluu and LDAP. Please don't touch these unless you know what you're doing.
###### Following that are the modules you want to install. The default ones comes pre-selected.
###### Not seen are LDAP type, which is only one option at this time as OpenLDAP is not support, as well as license agreements.

- Click `Submit`

`Installing Gluu Server`

10) Gluu will now be installed on the server. This may take some time, so please be patient.

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


