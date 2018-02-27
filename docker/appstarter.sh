#!/bin/sh
set -e

CUSTOM_CONFIG=/root/.clustermgr/instance/config.py

# run influxdb
/opt/influxdb-1.4.3-1/influxd &

# run redis server
redis-server /etc/redis.conf &

# upgrade database schema
clustermgr-cli db upgrade &

# run celery worker
clustermgr-celery &

# run celery beat
clustermgr-beat &

if [ ! -f $CUSTOM_CONFIG ]; then
    mkdir -p $(dirname $CUSTOM_CONFIG)
    echo "DEBUG = False" > $CUSTOM_CONFIG
    echo "SECRET_KEY = '$(cat /dev/urandom | tr -dc [:alnum:] | fold -w 32 | head -n 1)'" >> $CUSTOM_CONFIG
    echo "LICENSE_ENFORCEMENT_ENABLED = False" >> $CUSTOM_CONFIG
fi

# a workaround to catch SIG properly
exec clustermgr-cli run -h 0.0.0.0 -p 5000
