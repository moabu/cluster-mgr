Licensed under the [GLUU SUPPORT LICENSE](./LICENSE). Copyright Gluu 2017.

# Cluster Manager

#### GUI tool for managing Gluu Server and OpenLDAP replication.

Cluster Manager currently only supports installation on Ubuntu 14 and 16. It can, however, be used to configure Gluu Server clusters on Ubuntu, Debian, and CentOS.

##### Gluu Cluster Manager should be installed on a secure administrators computer or a VM as it will have SSH access to all servers in the cluster.

After configuration, Cluster Manager no longer needs to be actively connected to the cluster for them to work properly. It can however be used to monitor and manage your cluster for modifications at any time.

##### The necessary ports that need to be opened in a default cluster installation are as follows:

<table>
<tr><th> Gluu Servers </th><th> Load Balancer </th></tr>
<tr><td>

|22| 80 | 443|
|--|--|--|
|1636| 7777 |  |

</td><td>

|22|80|
|--|--|
|443|22|

</td></tr> </table>

## Installing Cluster Manager

1) First we must enable the machine that Gluu Cluster Manager is installed on the ability to establish an ssh connection to the servers that are going to be added to the cluster. This includes the NGINX/Load-balancing server:

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
sudo pip install --pre clustermgr
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

9) Create default authentication config file at `$HOME/.clustermgr/auth.ini` for initial setup

```
[user]
username = your_desired_name
password = your_desired_password
```

The default authentication method can be disabled by removing the file.
Note, we recommend to disable [default authentication](https://github.com/GluuFederation/cluster-mgr/wiki/User-Authentication#using-default-admin-user) after [OXD authentication](https://github.com/GluuFederation/cluster-mgr/wiki/User-Authentication#using-oxd-and-gluu-server) has been setup properly.

10) Tunnel into cluster-mgr server

```
ssh -L 9999:localhost:5000 root@server
```

- If you're using a windows machine, like me, you can tunnel in with a saved PuTTY session that can already connect. Load that configuration in `PuTTY Configuration`, then on the left side go to `Connections` -> `SSH` -> `Tunnels`. In `Source port` input `9999` and in Destination input `localhost:5000`, then hit `Add`. This will create a tunnel from your machine, accessed through `localhost:9999`, into the server as `localhost:5000`.

11) Navigate to the cluster-mgr web GUI and login with your `auth.ini` credentials.

```
http://localhost:9999/
```


## Configuring a Cluster


![Start](https://github.com/GluuFederation/cluster-mgr/raw/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-29-55.png)

This is the initial screen you will see. From here click `Setup Cluster`.

![Settings](https://github.com/GluuFederation/cluster-mgr/raw/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-30-08.png)

You will now be taken to the Settings menu, also accessible from the left side menu.

There are several options:

Gluu Server version (3.0.1, 3.0.2, 3.1.1)

- Replication Manager DN: This will be the domain name of the domain name which manages replication in OpenLDAP. You can name this anything you want.

- Password: The password will be used only for the replication DN. Your administrator password for oxAuth will be identified elsewhere.

- Load Balancer Hostname: You will need to put the Fully Qualified Domain Name (FQDN) of the server that will be handling proxying between all of your nodes. If you are going to use NGINX as your proxy, this will be where Cluster Manager installs NGINX to.

- Access Log Purge: The access log is where all the changes made on the OpenLDAP servers are stored. OpenLDAP monitors the access log to determine whether an entry should be replicated or not. The default purging parameter is set to check 24 hours for any entry that is older than 24 hours.

- IP address for replication hostname: You can click this radio box to change from using a FQDN to IP addresses in the OpenLDAP replication configuration.

Once you have everything filled out click `Update Configuration` and you will be taken to the following screen to add a server.

![Add_Server_1](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-31-07.png)

This screen is pretty self explanatory, the only thing to mention is that your `LDAP Admin Password` is also the password for your oxTrust Admin page. Please make this as strong as possible.

After hitting `submit` you will be taken to the Dashboard page. Here you can add more servers, change your Gluu Version (Not recommended after installing Gluu) and also install Gluu automatically.

![Dashboard_1](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-31-28.png)

The term `Primary` next to my first servers hostname, is to identify the base server where replication and settings will be configured from. After everything is setup, all the servers will serve the same function.

It is recommended that you add all the servers for your cluster at this time, before continuing with installation and further configuration.


![Add_Server_2](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-31-55.png)

Now we should click `Install Gluu` on the `Primary` server. You'll be taken to the following screen.

![Install_Gluu_Config](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-35-09.png)

###### If you see `Error : OS type has not been identified. Ending server installation process.`, this usually means your Cluster Manager machine cannot SSH into your server. Please make sure that the public key from your Cluster Manager machine is in the `authorized_keys` file on every server you want to work with. If you still experience this issue, remove the server and add it again, so that Cluster Manager will attempt to reconnect.

The input fields here are used primarily for your certificates to be installed inside Gluu. Also you'll see some inum settings, but unless you know what you're doing, you shouldn't touch these.

There are also options to install additional modules, Passport, Shibboleth, etc.. as needed.

A successful installation looks as follows:

![Install_Gluu_1](https://github.com/GluuFederation/cluster-mgr/blob/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-40-29_Cropped.png)

Install all the servers and your dashboard should look like this:

![Dashboard_Installed](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-49-49.png)

###### Note that cluster manager can install NGINX with the necessary default configurations to proxy your connections. That option is located under the `Cluster` option as seen here:

![Install_NGINX](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-50-01_Cropped.png)

Install NGINX now, or click the `LDAP Replication` menu and you'll be taken to the follow screen:

![LDAP_Replication](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-51-05.png)

Deploy the configuration on the first server. A successful installation looks like this:

![Successful_Replication_Configuration](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-54-43.png)

Once you deploy all configurations, you'll see something similar to this screen:

![Nodes_Deployed](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-57-52.png)

You'll need to click `Add` on all the providers that are crossed out. This should add the other LDAP servers replication properties to the server missing them. To test if replication is working, click the `Add Test User` option on one server and fill out the form. Then on the other servers click `Search Test User`. If everything is replicating properly, that entry will show up there.

![Add_User](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-58-14.png)

![Search_User](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-58-51.png)

###### A rare issue is that sometimes the providers aren't replicating properly. Please `Remove` all the providers and then add them back. This usually fixes the problem.

### If you're using 3.0.2, you're done here. If you're using 3.1.x, you will have to configure your cache for replication.

Click the `Cache Management` menu option on the left. You'll see this screen:

![Cache_Management_1](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_10-59-15.png)

Clicking `Fetch cache methods` will show you what caching mechanism you're currently using on your clusters. By default there is none, so we must click `Setup Redis` to start the process of properly configuring caching.

Upon successful completion of installing all the necessary components on the servers, you'll see this:

![Install_Modules](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_11-05-07.png)

Click `Configure Cache Cluster` to continue.

A successful install:

![Configure_Cache](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_11-05-55.png)


And lastly click `Finish Cache Clustering` to reload all the modules and intake the configuration changes.

![Restart_Services](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_11-09-47.png)

That's it. Your cluster is fully configured. Please navigate to the hostname you identified as your load balancer. Log in with your administrator and password.

# LOGGING

Aside from the standard logs inside the Cluster Manager GUI, the terminal you run `clustermgr-celery &` on will present logs and any errors or complications. Below is an example where I didn't properly configure my Cluster Manager machine to ssh in to one of the nodes of my cluster:

![Failed_Connection](https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/manual_install/images/Cluster%20Manager%20Docs/2017-11-27_13-35-13.png)

You can also see that after I corrected the problem, public key access was successful (I had to click install Gluu twice before it updated).

# Configuration

By default the installation of a cluster on 3.1.1 installs 5 services. These services are:

1) Gluu Server

2) Redis-Server

###### Installed outside the chroot on all servers.
###### A value key-store known for it's high performance.
###### Configuration file located at /etc/redis/redis.conf or /etc/redis.conf on the **Gluu** servers.

3) Stunnel

###### Used to protect communications between oxAuth and the caching services, Redis and Twemproxy.
###### Configuration file located at /etc/stunnel/stunnel.conf on **all** servers

4) NGINX

###### Used to proxy communication to the instances of Gluu
###### Configuration file located at /etc/nginx/nginx.conf on the load balancing server (if installed).

5) Twemproxy

###### Used for cache failover, round-robin proxying and caching performance with Redis.
###### The configuration file for this program can be found in /etc/nutcracker/nutcracker.yml on the proxy server
