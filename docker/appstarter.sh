#!/bin/sh
set -e

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

# a workaround to catch SIG properly
exec clustermgr-cli run -h 0.0.0.0 -p 5000
