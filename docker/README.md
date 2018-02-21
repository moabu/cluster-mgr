- create a direcory and change to there
```
    mkdir clusermgrdocker
    cd clusermgrdocker
```


- get Dockerfile and appstarter.sh
```
    wget https://raw.githubusercontent.com/GluuFederation/cluster-mgr/master/docker/Dockerfile
    wget https://github.com/GluuFederation/cluster-mgr/blob/master/docker/appstarter.sh
```


- build docker
```
    docker build -t clustermgr .
```


- create dockeroot and .ssh direcory
```
    mkdir -p $HOME/clustermgrroot/.ssh
```


- copy your id_rsa and id_rsa.pub to clustermgrroot/.ssh
```
    cp $HOME/.ssh/* $HOME/clustermgrroot/.ssh
```


- run docker container
```
    docker run -p 5000:5000 -v /root/clustermgrroot:/root/ clustermgr
```
