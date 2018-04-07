Licensed under the [GLUU SUPPORT LICENSE](./LICENSE). Copyright Gluu 2018.

# Cluster Manager (Beta)

### This documentation is no longer maintained. Please visit the [official documentation page](https://gluu.org/docs/cm/) for the most up to date instructions.

## Overview
Cluster Manager is a GUI tool for installing and managing a highly available, clustered Gluu Server infrastructure.

## Prerequisites

- A minimum of four (4) machines. One machine will be used for cluster manager, which could be localhost on the installers computer. This machine can be very lightweight and will only be used for proxying TCP and HTTP traffic. It will act as a proxy for the other three servers where Gluu will be installed. 

- Cluster Manager currently supports installation on Ubuntu 14 and 16. However, it can be used to configure Gluu Server clusters on Ubuntu, CentOS, RHEL, and Debian.

- Cluster Manager should be installed on a secure administrators computer or a VM, as it will have SSH access to all servers in the cluster.

- After configuration, Cluster Manager no longer needs to be actively connected to the cluster. However, in order to take advantage of Cluster Managers monitoring, configuration, and logging features, Cluster Manager must be connected to the cluster. 

### External ports

The necessary external ports that need to be opened in a default cluster installation are as follows:

<table>
  <tr><th> Gluu Servers </th><th> Load Balancer </th> <th> Cluster Manager </th></tr>
<tr><td>

|22| 443 | 30865 | -- |
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

- 22 will be used by Cluster Manager to pull logs and make adjustments to the systems.

- 80 and 443 are self explanatory. 443 must be open between the Load Balancer and the Gluu Server/oxAuth.

- 1636, 4444 and 8989 are necessary for LDAP usage and replication. These should be open between Gluu Server nodes.

- 30865 is the default port for csync2 file system replication.

- 7777 and 8888 are for securing communication between the Proxy server and the Gluu servers with stunnel.

## Installing Cluster Manager

### SSH & Keypairs

Give Cluster Manager the ability to establish an ssh connection to the servers in the cluster. This includes the NGINX/Load-balancing server:

`ssh-keygen -t rsa`

- This will initiate a prompt to create a key-pair. **Do not input a password here**. Cluster Manager must be able to open connections to the servers.

- Copy the key (default is `id_rsa.pub`) to the `/root/.ssh/authorized_keys` file of all servers in the cluster, including the NGINX server (unless another load-balancing service will be used).

**This HAS to be the root authorized_keys or Cluster Manager will not work**

### Install dependencies  

Install the necessary dependencies on the Gluu Cluster Manager machine:

```
sudo apt-get update
sudo apt-get install python-pip python-dev libffi-dev libssl-dev python-ldap redis-server default-jre
(default-jre is for license requirements. Not necessary if Java already installed)
sudo pip install --upgrade setuptools influxdb
```

### Install the package

Install cluster manager using the following command:

```
pip install clustermgr
```

There may be a few innocuous warnings, but this is normal.

### Prepare Database

Prepare the database using the following commands:

```
clustermgr-cli db upgrade
```

### Add license validator 

Prepare the license validator by using the following commands:

```
mkdir -p $HOME/.clustermgr/javalibs
wget http://ox.gluu.org/maven/org/xdi/oxlicense-validator/3.2.0-SNAPSHOT/oxlicense-validator-3.2.0-SNAPSHOT-jar-with-dependencies.jar -O $HOME/.clustermgr/javalibs/oxlicense-validator.jar
```

!!! Note
    Licenses files are not currently enforced. It is on the honor system! In future versions, a license file may be required.  

### Run Celery

Run celery scheduler and workers in separate terminals:

```
# Terminal 1
clustermgr-beat &

# Terminal 2
clustermgr-celery &
```

### Run clustermgr

Open another terminal to run clustermgr as:

```
clustermgr.sh
```

### Create Credentials

When Cluster Manager is run for the first time, it will prompt creation of an administrator user name and password. This creates an authentication config file at `$HOME/.clustermgr/auth.ini`. The default authentication method can be disabled by removing the file.

### Intstall oxd (optional)

We recommend utilizing the [oxd client software](https://github.com/GluuFederation/cluster-mgr/wiki/User-Authentication#using-oxd-and-gluu-server) to leverage Gluu for authentication to Cluster Manager.  After oxd has been installed and configured, [default authentication](https://github.com/GluuFederation/cluster-mgr/wiki/User-Authentication#using-default-admin-user) can be disabled. 

### Create new user
It is recommended to create an additional "cluster" user, other than the one used to install and configure cluster manager. 

This is a basic security precaution, due to the fact that the user ssh'ing into this server has unfettered access to every server connected to cluster manager. By using a separate user, which will still be able to connect to localhost:5000, an administrator can give an operator limited access to a server, while still being able to take full control of Cluster Manager. 

```
ssh -L 5000:localhost:5000 cluster@<server>
```

### Login

Navigate to the cluster-mgr web GUI on your local machine:

```
http://localhost:5000/
```
## Deploying a default Gluu Server Cluster

### To deploy a functioning cluster, it is necessary to do a few things.

Here is the first screen you'll see on the initial launch where you create the default administrator and password:

![Admin_Creation](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-01.png)


Next you'll be taken to the splash page where you can initiate building a cluster with the `Setup Cluster` button:

![Setup Cluster](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-02.png)

Here is you `Settings` screen. You can access this screen again by clicking the `Settings` button on the left menu bar.

![Application Settings Screen](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-03.png)

###### Replication Manager Password will be used in OpenDJ for replication purposes
###### Load Balancer: This will be the hostname of either your NGINX proxy server, or the Load balancing server you'll be using for your cluster. Note, this cannot be changed after you deploy your Gluu servers, so please keep this in mind. To change the hostname, you'll have to redeploy Gluu Severs from scratch.
###### `Add IP Addresses and hostnames to /etc/hosts file on each server`: Use this option if you're using servers without Fully Qualified Domain Names. This will automatically assign hostnames to ip addresses in the `/etc/hosts` files inside and outside the Gluu chroot. Otherwise, you may run into complications with server connectivity unless you manually configure these correctly.

Once these are properly configured, click the `Update Configuration button`.

![Add Server Prompt](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-04.png)

Click `Add Server`

![New Server - Primary Server](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-05.png)

You will be taken to the `Add Primary Server` screen. It is called Primary as it will be the base for which the other nodes will pull their Gluu configuration and certificates. After Deployment, all servers will function in a Master-Master configuration.

###### Hostname will be the actual hostname of the server, not the hostname of the NGINX/Proxy server. If you selected the `Add IP Addresses and Hostnames to/etc/hosts file on each server` in the `Settings` menu, then this will be the hostname embedded automatically in the `/etc/hosts` files on this computer.

![Dashboard](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-06.png)

After you click `Submit`, you will be taken to the Dashboard.

###### Here you can see all the servers in your cluster, add more servers, edit the hostname and IP address of a server if you entered them incorrectly and also Install Gluu automatically.

Click the `Add Server` button and add another node or 2. Note, the admin password set in the Primary server is the same for all the servers.

Once you've added all the servers you want in your cluster, back at the dashboard we will click `Install Gluu` on our primary server.

![Install Primary Gluu Server](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-07.png)

###### This screen is the equivalent of the standard `setup.py` installation in Gluu. The first 5 options are necessary for certificate creation.
###### Next are inum configurations for Gluu and LDAP. Please don't touch these unless you know what you're doing.
###### Following that are the modules you want to install. The default ones comes pre-selected.
###### Not seen are LDAP type, which is only one option at this time as OpenLDAP is not support, as well as license agreements.

- Click `Submit`

![Installing Gluu Server](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-09.png)

###### Gluu will now be installed on the server. This may take some time, so please be patient.

Once completed, repeat the process for the other servers.

When all the installations have completed, you'll want to install NGINX. Do this by clicking `Cluster` on the left menu and selecting `Install Nginx`.

After that you'll be taken to the `LDAP Replication` screen where you can enable and disable LDAP replication. There is also a `Deploy All` button to be used for initial deployments. Click it and wait for the process to finish.

![Deploying LDAP Replication](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-10.png)

###### You can also see the replication status and other replication information on this screen once you've deployed OpenDJ replication.

![Replication Deployed screen](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-11.png)

From here we need to enable file system replication. Do this by clicking `Replication` on the left menu and selecting `File system Replication`. Click `Install File System Replication` This installs and configures csync2 and replicates necessary configuration files if they're changed by oxTrust.

![File System Replication](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-12.png)

###### You can also add replication paths for other file systems, if you deem it necessary.

The last step for a functioning cluster configuration is the `Cache Management` option on the left menu. Click that and follow through the steps for deploying Cache Management.

![Cache Management](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-13.png_

###### We have to configure oxAuth to utilize an external, network capable caching service because of the nature of clustering. oxAuth caches short-lived tokens and in a balanced cluster, all the instances of oxAuth need access to the cache. To allow this capability, and still enable high-availability, Redis is installed outside the chroot on every Gluu server. Configuration settings inside of LDAP are also changed to allow access to these instances of Redis.

###### Redis also doesn't utilize encrypted communication, so we will install and configure stunnel on all our servers to protect our information with SSL.

###### Twemproxy is also installed on the NGINX/Proxy server as a means for redundancy since Twemproxy can detect redis server communication failure, giving you high availability.

![Successful Cache Management Installation](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-14.png)

Once this task is completed, you have a fully functional Gluu Server cluster. Please navigate to the hostname of the proxy server you provided in the `Settings` option.

## Additional Management Components

We've added a couple additional services to help deal with Gluu Server clusters. These are process monitoring and logging management. `Monitoring` and `Logging Management`, respectively, found on the left-hand menu.

Installation is a breeze, just click `Setup Monitoring` and `Setup Logging`

![Monitoring Screen](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-15.png)

###### Monitoring gives you an easily accessible means to quickly take a glimpse at your servers performance and potential issues.

![Logging Screen](https://github.com/GluuFederation/cluster-mgr/blob/master/images/Cluster_Manager-16.png)

###### Logging is also another powerful tool to gather all of your Gluu logs from all the nodes for troubleshooting. These logs can be sorted by log type (oxAuth, oxTrust, HTTPD[Apache2], OpenDJ and Redis), Host and also string search filters for easy sorting.


## Logging for Cluster Manager Errors and Troubleshooting

Cluster Manager displays most logs about what's happening on the system it's interacting with and these can be seen directly in the GUI as seen above. There is also additional information that can be derived about what is going on in cluster manager in the terminals you launched `clustermgr-celery` and `clustermgr-cli run`. 

```
INFO:werkzeug:127.0.0.1 - - [02/Feb/2018 08:11:12] "GET /log/0a4c3f1f-e2c2-4d0a-81ff-08c808cf6269 HTTP/1.1" 200 -
[2018-02-02 08:11:12,749: INFO/ForkPoolWorker-2] Connected (version 2.0, client OpenSSH_7.4)
[2018-02-02 08:11:13,083: INFO/ForkPoolWorker-2] Authentication (publickey) successful!
[2018-02-02 08:11:13,476: INFO/ForkPoolWorker-2] [chan 0] Opened sftp connection (server version 3)
```

###### Here's a standard successful connection message.

Most of the time it's rudimentary status checks like this:

```
INFO:werkzeug:127.0.0.1 - - [02/Feb/2018 08:07:59] "GET /log/0a4c3f1f-e2c2-4d0a-81ff-08c808cf6269 HTTP/1.1" 200 -
127.0.0.1 - - [02/Feb/2018 08:08:00] "GET /log/0a4c3f1f-e2c2-4d0a-81ff-08c808cf6269 HTTP/1.1" 200 -
INFO:werkzeug:127.0.0.1 - - [02/Feb/2018 08:08:00] "GET /log/0a4c3f1f-e2c2-4d0a-81ff-08c808cf6269 HTTP/1.1" 200 -
127.0.0.1 - - [02/Feb/2018 08:08:01] "GET /log/0a4c3f1f-e2c2-4d0a-81ff-08c808cf6269 HTTP/1.1" 200 -
```
But it will throw errors if there's a problem in a process. These should give you a good idea of what complication you're running into and can help with troubleshooting issues.

While patience is recommended, sometimes the process hangs irreparably. To get Cluster Manager back on track in an instance like this is to stop and restart the process. You can do this simply and rather heavy handedly like so:

`ps aux | grep clustermgr | awk \'{print $2}\' | sudo xargs kill -9`

And then restart the processes (In one terminal, if you like):

`clustermgr-beat & clustermgr-celery & clustermgr-cli run`

## Configuration

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


