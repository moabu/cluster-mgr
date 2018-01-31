FROM ubuntu

MAINTAINER Gluu Inc. <support@gluu.org>

RUN echo "deb http://us.archive.ubuntu.com/ubuntu/ xenial main universe" >> /etc/apt/sources.list

# Make directories 
RUN mkdir -p /usr/share/man/man1 \
    && mkdir $HOME/clustermgr \
    && mkdir -p $HOME/.ssh \
    && mkdir $HOME/.clustermgr/ \
    && mkdir -p $HOME/.clustermgr/javalibs \
    && mkdir -p /etc/cron.d/ \
    && mkdir -p /opt/scripts
#Do I need an upgrade here??
RUN apt-get upgrade -y \
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
    sudo \
    curl \
    cron \
    apt-transport-https \
    apt-utils \
    && pip install --upgrade \
    setuptools \
    influxdb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Change .ssh permissions
RUN chmod 600 $HOME/.ssh/ \
# Download and install Cluster Manager
    && git clone https://github.com/GluuFederation/cluster-mgr.git $HOME/clustermgr/ \
    && cd $HOME/clustermgr/   \
    && python setup.py install

# Prepare database and license enforcement requirements
RUN clustermgr-cli db upgrade  \
    && wget http://ox.gluu.org/maven/org/xdi/oxlicense-validator/3.2.0-SNAPSHOT/oxlicense-validator-3.2.0-SNAPSHOT-jar-with-dependencies.jar -O $HOME/.clustermgr/javalibs/oxlicense-validator.jar

# Expose the Cluster Manager default port
EXPOSE 5000

# Remove unnecessary packages
RUN apt-get remove --purge -y python-dev \
    libffi-dev \
    libssl-dev \
    wget \
    git

RUN touch /etc/cron.d/monitoring
RUN chmod 0644 /etc/cron.d/monitoring
RUN touch /var/log/cron.log

#Run the program
COPY entrypoint.sh /opt/scripts
RUN chmod +x /opt/scripts/entrypoint.sh
CMD ["/opt/scripts/entrypoint.sh"]
