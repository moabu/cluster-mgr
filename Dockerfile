FROM debian:stretch-slim

MAINTAINER Gluu Inc. <support@gluu.org>

RUN echo "deb http://deb.debian.org/debian stretch main" >> /etc/apt/sources.list

#Required for openJDK-8
RUN mkdir -p /usr/share/man/man1

RUN apt-get upgrade -y  \
    && apt-get update -y  \
    && apt-get install -y\
    git \
    ca-certificates-java \
    openjdk-8-jre-headless \
    wget \
    python-pip \
    python-dev \
    libffi-dev \
    libssl-dev \
    redis-server  \
    && pip install --upgrade \
    setuptools \
    influxdb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create keypair 

RUN mkdir -p $HOME/.ssh \
    && chmod 600 $HOME/.ssh/ \
    && ssh-keygen -b 2048 -t rsa -f $HOME/.ssh/id_rsa -q -N ""
# Download and install Cluster Manager
RUN mkdir $HOME/clustermgr \
    && git clone https://github.com/GluuFederation/cluster-mgr.git $HOME/clustermgr/ \
    && cd $HOME/clustermgr/   \
    && python setup.py install

# Prepare database and license enforcement requirements
RUN mkdir $HOME/.clustermgr/ \
    && clustermgr-cli db upgrade  \
    && mkdir -p $HOME/.clustermgr/javalibs \
    && wget http://ox.gluu.org/maven/org/xdi/oxlicense-validator/3.2.0-SNAPSHOT/oxlicense-validator-3.2.0-SNAPSHOT-jar-with-dependencies.jar -O $HOME/.clustermgr/javalibs/oxlicense-validator.jar

EXPOSE 5000

#Run the program
RUN mkdir -p /opt/scripts
COPY entrypoint.sh /opt/scripts
RUN chmod +x /opt/scripts/entrypoint.sh
