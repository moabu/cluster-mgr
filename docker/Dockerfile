FROM alpine:3.7
RUN apk add --no-cache --update \
    openjdk8-jre-base \
    python \
    py-pip \
    ca-certificates \
    redis \
    py-flask \
    py-redis \
    py2-sqlalchemy \
    py2-flask-wtf \
    py2-cryptography \
    py2-requests \
    py2-paramiko \
    py2-ldap3 \
    py2-psutil

WORKDIR /app
ADD . /app

RUN wget https://github.com/GluuFederation/cluster-mgr/archive/master.zip && \
    unzip master.zip && \
    cd cluster-mgr-master && \ 
    python setup.py install && \
    rm -r -f /app/cluster-mgr-master && \
    rm -f /app/master.zip && \
    mkdir /etc/influxdb/ && \
    mkdir /opt

RUN wget https://dl.influxdata.com/influxdb/releases/influxdb-1.4.3-static_linux_amd64.tar.gz -O /tmp/influxdb-1.4.3-static_linux_amd64.tar.gz && \
    tar -zxf /tmp/influxdb-1.4.3-static_linux_amd64.tar.gz -C /opt && rm -f /tmp/influxdb-1.4.3-static_linux_amd64.tar.gz && \
    sed  's/dir = "\/var\/lib\/influxdb\/meta"/dir = "\/root\/influxdb\/meta"/g' < /opt/influxdb-1.4.3-1/influxdb.conf > /etc/influxdb/influxdb.conf

EXPOSE 5000
CMD ["sh", "appstarter.sh"]

