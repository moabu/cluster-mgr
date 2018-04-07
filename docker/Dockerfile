FROM alpine:3.7

LABEL maintainer="Gluu Inc. <support@gluu.org>"

# install alpine packages
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
    py2-psutil \
    py2-pyldap

# install InfluxDB
RUN wget -q https://dl.influxdata.com/influxdb/releases/influxdb-1.4.3-static_linux_amd64.tar.gz -P /tmp \
    && mkdir -p /etc/influxdb/ \
    && mkdir -p /root/influxdb/meta \
    && mkdir -p /opt \
    && tar -zxf /tmp/influxdb-1.4.3-static_linux_amd64.tar.gz -C /opt \
    && rm -f /tmp/influxdb-1.4.3-static_linux_amd64.tar.gz \
    && sed  's/dir = "\/var\/lib\/influxdb\/meta"/dir = "\/root\/influxdb\/meta"/g' < /opt/influxdb-1.4.3-1/influxdb.conf > /etc/influxdb/influxdb.conf

WORKDIR /app

# to force download master.zip, run `docker build` with `--build-arg`
ARG CM_DOWNLOAD_TS=1519846997

# install clustermgr package
RUN wget -q https://github.com/GluuFederation/cluster-mgr/archive/master.zip \
    && unzip -qq master.zip \
    && cd cluster-mgr-master \
    && python setup.py install \
    && rm -rf /app/cluster-mgr-master \
    && rm -f /app/master.zip \
    && mkdir -p /root/.clustermgr

# port for Flask app
EXPOSE 5000

# switch to production mode
ENV APP_MODE prod

# entrypoint
COPY appstarter.sh /app/appstarter.sh
CMD ["sh", "appstarter.sh"]
